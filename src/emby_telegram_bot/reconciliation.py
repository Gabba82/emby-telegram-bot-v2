"""Read-only Emby reconciliation. Snapshots never trigger publications."""
from __future__ import annotations
import json
import secrets
import time
from collections import Counter
from datetime import datetime, timezone

STATUSES=('delivered','failed','pending','uncertain','history_unknown','possible_omission')
LIBRARY_SOURCES=('automatic','manual','panel-demo','panel-operational','demo-seed','reconciliation-demo','reconciliation-operational')


def timestamp(value):
    if value is None or value=='':return None
    if not isinstance(value,str):raise ValueError('Invalid date')
    # Emby can emit 7 fractional second digits; Python accepts/truncates them.
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def classify(item, evidence, *, history_from, date_from, date_to, complete):
    """Evidence is already filtered by real item id, destination and library event."""
    if item.get('Type') not in ('Movie','Episode'):
        return dict(status='history_unknown',reason='Tipo de contenido no compatible con la conciliación.',eligible=False,can_prepare=False,delivery_id=None,attempt_count=0)
    try:added=timestamp(item.get('DateCreated'))
    except (ValueError,TypeError):added=None
    start=timestamp(history_from); lower=timestamp(date_from); upper=timestamp(date_to)
    in_scope=bool(not added or ((not lower or added>=lower) and (not upper or added<=upper)))
    eligible=bool(in_scope and added and start and added>=start)
    sent=next((r for r in evidence if r['status']=='sent'),None)
    known=sent or (evidence[0] if evidence else None)
    if known:
        status='delivered' if sent else known['status']
        reason={'delivered':'Entrega confirmada en el historial de biblioteca.','failed':'El último intento consta como fallido.','pending':'Intención registrada, pendiente de intento.','uncertain':'Hay un intento sin confirmación fiable.'}[status]
    elif not in_scope:status,reason='history_unknown','Contenido fuera del ámbito de fechas o tipos seleccionado.'
    elif not added:status,reason='history_unknown','Emby no proporciona una fecha de incorporación fiable.'
    elif not start:status,reason='history_unknown','No se ha establecido un inicio conocido del historial.'
    elif added<start:status,reason='history_unknown','Contenido anterior al inicio conocido del historial; no se presume una omisión.'
    elif not complete:status,reason='history_unknown','Consulta incompleta: no se puede concluir una posible omisión.'
    else:status,reason='possible_omission','Dentro del período registrado y sin evidencia de publicación; requiere revisión manual.'
    return dict(status=status,reason=reason,eligible=eligible,can_prepare=bool(in_scope and status!='delivered' and (known or eligible)),delivery_id=known['id'] if known else None,attempt_count=known.get('attempt_count',0) if known else 0)


def collect_pages(fetch, library_ids, item_types, *, page_size=200, max_pages=1000, deadline_seconds=60):
    """Advance by RAW page length, never by deduplicated length. Fail closed."""
    items={}; issues=[]; pages=0; duplicates=0; scanned=0; unexpected=Counter(); started=time.monotonic()
    def issue(code,message):
        if not any(i['code']==code for i in issues):issues.append(dict(code=code,message=message))
    for library in library_ids or [None]:
        offset=0; expected=None; seen=set()
        while True:
            if pages>=max_pages or time.monotonic()-started>deadline_seconds:
                issue('ScanLimit','Se alcanzó el límite de consulta; los resultados son parciales.');break
            try:payload=fetch(start_index=offset,limit=page_size,library_id=library,item_types=item_types)
            except Exception as exc:
                issue(type(exc).__name__,'No se pudo completar una página de Emby. Vuelve a consultar; no se ha enviado nada.');break
            pages+=1
            if not isinstance(payload,dict) or not isinstance(payload.get('Items'),list):
                issue('InvalidResponse','Emby devolvió una página no válida.');break
            raw=payload['Items']; total=payload.get('TotalRecordCount')
            if isinstance(total,bool) or not isinstance(total,int) or total<0:
                issue('MissingTotal','La respuesta no permite verificar el total de la biblioteca.');break
            if expected is None:expected=total
            elif total!=expected:
                issue('ChangingLibrary','El total cambió durante la consulta. Repite la conciliación.');expected=max(expected,total)
            if len(raw)>page_size:
                issue('OversizedPage','Emby no respetó el tamaño solicitado de página.');break
            valid_in_page=0
            for raw_item in raw:
                if not isinstance(raw_item,dict) or not isinstance(raw_item.get('Id'),str) or not raw_item['Id']:
                    issue('InvalidItem','Se recibió un elemento sin identificador fiable.');continue
                if raw_item.get('Type') not in item_types:
                    unexpected[str(raw_item.get('Type') or 'desconocido')]+=1;continue
                key=raw_item['Id'];scanned+=1
                if key in items:duplicates+=1
                if key in seen:issue('RepeatedItems','Se repitieron identificadores en la paginación; la consulta puede haber cambiado.')
                else:valid_in_page+=1
                seen.add(key)
                safe={k:raw_item[k] for k in ('Id','Name','Type','DateCreated','SeriesId','SeriesName','ParentId','ParentIndexNumber','IndexNumber','ProductionYear','Overview','LibraryId') if k in raw_item}
                safe['LibraryId']=safe.get('LibraryId') or library or ''
                items.setdefault(key,safe)
            offset+=len(raw)
            if offset>=expected:
                if offset>expected:issue('InconsistentTotal','El número de elementos no coincide con el total declarado.')
                break
            if not raw or not valid_in_page:
                issue('PrematureEnd','La paginación terminó antes de alcanzar el total de Emby.');break
    if unexpected:
        detail=', '.join(f'{name}: {count}' for name,count in sorted(unexpected.items()))
        issues.insert(0,dict(code='UnexpectedType',message=f'Emby devolvió tipos fuera de la consulta ({detail}). La lectura se considera parcial.',types=dict(unexpected)))
    return dict(items=list(items.values()),complete=not issues,issues=issues,pages=pages,duplicates=duplicates,scanned=scanned,unexpected_types=dict(unexpected))


class ReconciliationService:
    def __init__(self,store,catalog,chats,mode):
        self.store,self.catalog,self.chats,self.mode=store,catalog,chats,mode
        with store.connection() as db:
            db.executescript('''CREATE TABLE IF NOT EXISTS reconciliation_config (id INTEGER PRIMARY KEY CHECK(id=1),history_from TEXT);
            CREATE TABLE IF NOT EXISTS reconciliation_runs (id TEXT PRIMARY KEY,created_at TEXT NOT NULL,summary_json TEXT NOT NULL,rows_json TEXT NOT NULL,items_json TEXT NOT NULL);''')
            db.execute('INSERT OR IGNORE INTO reconciliation_config VALUES (1,?)',('2026-10-01T00:00:00Z' if mode=='demo' else None,))
    def current_chats(self):
        return self.chats() if callable(self.chats) else self.chats
    def config(self):
        with self.store.connection() as db:history=db.execute('SELECT history_from FROM reconciliation_config WHERE id=1').fetchone()[0]
        return dict(mode=self.mode,history_from=history,chat_ids=[c['id'] for c in self.current_chats()],libraries=self.catalog.reconciliation_libraries(),defaults=dict(date_from='2026-10-01T00:00:00Z' if self.mode=='demo' else None,date_to='2026-10-31T23:59:59Z' if self.mode=='demo' else None,item_types=['Movie','Episode']))
    def configure(self,value):
        if value is not None:timestamp(value)
        with self.store.connection() as db:db.execute('UPDATE reconciliation_config SET history_from=? WHERE id=1',(value,))
        return self.config()
    def run(self,scope):
        config=self.config(); labels={c['id']:c['label'] for c in self.current_chats()}
        chats=scope.get('chat_ids',config['chat_ids']);types=scope.get('item_types',['Movie','Episode'])
        library_config={v['id']:v for v in config['libraries']}
        libs=scope.get('library_ids')
        if libs is None:libs=list(library_config)
        if not isinstance(chats,list) or not chats or len(chats)>8 or any(not isinstance(c,str) or c not in labels for c in chats) or len(set(chats))!=len(chats):raise ValueError()
        if not isinstance(libs,list) or not libs or len(libs)>20 or any(not isinstance(c,str) or c not in library_config for c in libs) or len(set(libs))!=len(libs):raise ValueError()
        if not isinstance(types,list) or not types or any(v not in ('Movie','Episode') for v in types) or len(set(types))!=len(types):raise ValueError()
        lower,upper=scope.get('date_from'),scope.get('date_to')
        if lower is not None:timestamp(lower)
        if upper is not None:timestamp(upper)
        if lower and upper and timestamp(lower)>timestamp(upper):raise ValueError()
        scenario=scope.get('scenario','complete')
        if scenario not in ('complete','timeout','partial','duplicates') or (self.mode!='demo' and scenario!='complete'):raise ValueError()
        active_libs=[library_id for library_id in libs if any(item_type in types for item_type in library_config[library_id]['item_types'])]
        def fetch(**kwargs):
            supported=library_config[kwargs['library_id']]['item_types']
            kwargs['item_types']=[item_type for item_type in kwargs['item_types'] if item_type in supported]
            return self.catalog.reconciliation_page(scenario=scenario,**kwargs)
        snapshot=(collect_pages(fetch,active_libs,types,page_size=7 if self.mode=='demo' else 200)
                  if active_libs else dict(items=[],complete=True,issues=[],pages=0,duplicates=0,scanned=0,unexpected_types={}))
        scope=dict(chat_ids=chats,library_ids=libs,item_types=types,date_from=lower,date_to=upper,history_from=config['history_from'],scenario=scenario)
        rows=[]
        with self.store.connection() as db:
            for item in snapshot['items']:
                if item.get('Type') not in types:continue
                for chat in chats:
                    placeholders=','.join('?' for _ in LIBRARY_SOURCES)
                    evidence=self.store._rows(db,f'o.item_id=? AND d.chat_id=? AND o.source IN ({placeholders})',(item['Id'],chat)+LIBRARY_SOURCES)
                    c=classify(item,evidence,history_from=config['history_from'],date_from=lower,date_to=upper,complete=snapshot['complete'])
                    rows.append(dict(key=item['Id']+'|'+chat,item_id=item['Id'],title=item.get('Name') or 'Contenido',item_type=item['Type'],series_name=item.get('SeriesName'),season=item.get('ParentIndexNumber'),episode=item.get('IndexNumber'),added_at=item.get('DateCreated'),library_id=item.get('LibraryId',''),chat_id=chat,chat_label=labels[chat],event='library',**c))
        counts=Counter(r['status'] for r in rows)
        run_id=secrets.token_urlsafe(24)
        summary=dict(run_id=run_id,status='complete' if snapshot['complete'] else 'partial' if snapshot['items'] else 'failed',complete=snapshot['complete'],total=len(rows),scanned=snapshot['scanned'],duplicates=snapshot['duplicates'],pages=snapshot['pages'],unexpected_types=snapshot['unexpected_types'],issues=snapshot['issues'],summary={k:counts[k] for k in STATUSES},scope=scope,created_at=datetime.now(timezone.utc).isoformat())
        with self.store.connection() as db:db.execute('INSERT INTO reconciliation_runs VALUES (?,?,?,?,?)',(run_id,summary['created_at'],json.dumps(summary),json.dumps(rows),json.dumps(snapshot['items'])))
        return summary
    def get(self,run_id):
        with self.store.connection() as db:record=db.execute('SELECT * FROM reconciliation_runs WHERE id=?',(run_id,)).fetchone()
        if record is None:return None
        return dict(run=json.loads(record['summary_json']),rows=json.loads(record['rows_json']),items=json.loads(record['items_json']))
    def history(self,page=1):
        with self.store.connection() as db:
            total=db.execute('SELECT count(*) FROM reconciliation_runs').fetchone()[0]
            rows=db.execute('SELECT summary_json FROM reconciliation_runs ORDER BY created_at DESC,id DESC LIMIT 10 OFFSET ?',((page-1)*10,)).fetchall()
        return dict(items=[json.loads(r[0]) for r in rows],total=total,page=page,pages=max(1,(total+9)//10))
