"""Administrative HTTP adapter over the existing publication ledger and service."""
from __future__ import annotations
import json
import secrets
import time
import sqlite3
from collections import Counter, defaultdict
from functools import wraps
from pathlib import Path
from flask import Blueprint, jsonify, request, session, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash


def register_manager(app, store, publications, catalog, chats, *, password, mode='operational', allow_sends=False, chat_directory=None):
    if mode not in ('demo', 'operational') or not password:
        raise ValueError('Explicit panel mode and administrative password required')
    app.secret_key = app.secret_key or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Strict', MAX_CONTENT_LENGTH=32768)
    bp = Blueprint('manager', __name__)
    assets = Path(__file__).with_name('panel_static')
    password_hash = generate_password_hash(password)
    failures = defaultdict(list)
    def current_chats():
        return chat_directory.list() if chat_directory is not None else chats

    def current_labels():
        return {chat['id']: chat['label'] for chat in current_chats()}

    def result_summary(results):
        counts=Counter(row.get('status') for row in results)
        return {key:counts[key] for key in ('sent','failed','pending','uncertain','skipped')}

    with store.connection() as db:
        db.execute('CREATE TABLE IF NOT EXISTS panel_batches (id TEXT PRIMARY KEY, owner TEXT NOT NULL, plan TEXT NOT NULL, status TEXT NOT NULL, results TEXT, expires REAL NOT NULL)')
        # A process can stop after claiming a batch and before completing it. Never
        # replay such work automatically: preserve its partial trace as interrupted.
        for row in db.execute("SELECT id,results FROM panel_batches WHERE status='executing'").fetchall():
            try:
                result=json.loads(row['results']) if row['results'] else {}
            except (TypeError,ValueError):
                result={}
            result=dict(result) if isinstance(result,dict) else {}
            result.setdefault('batch_id',row['id'])
            result['status']='interrupted'
            result['results']=result.get('results') if isinstance(result.get('results'),list) else []
            result['summary']=result_summary(result['results'])
            db.execute("UPDATE panel_batches SET status='interrupted',results=? WHERE id=?",(json.dumps(result),row['id']))

    def error(code, message, status=400):
        return jsonify(error=code, message=message), status

    def expire_session():
        if session.get('admin') and time.time() - session.get('login_at', 0) > 1800:
            session.clear()

    def info():
        expire_session()
        session.setdefault('csrf', secrets.token_urlsafe(32))
        return dict(authenticated=bool(session.get('admin')), csrf_token=session['csrf'], mode=mode, sends_enabled=allow_sends, user='admin' if session.get('admin') else None)

    def admin(fn):
        @wraps(fn)
        def call(*args, **kwargs):
            expire_session()
            if not session.get('admin'):
                return error('unauthorized', 'Inicia sesión administrativa.', 401)
            return fn(*args, **kwargs)
        return call

    @bp.before_request
    def guard():
        if request.path.startswith('/api/') and request.method == 'POST':
            if not request.is_json or not isinstance(request.get_json(silent=True), dict):
                return error('invalid_json', 'Se requiere un objeto JSON.')
            if not secrets.compare_digest(request.headers.get('X-CSRF-Token', ''), session.get('csrf', secrets.token_hex(32))):
                return error('csrf', 'La sesión ha cambiado. Recarga la página.', 403)

    @bp.after_request
    def headers(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        return response

    @bp.errorhandler(ValueError)
    def bad_input(exc):
        return error('invalid_request', 'Solicitud no válida.')

    @bp.errorhandler(sqlite3.Error)
    def database_error(exc):
        return error('storage_unavailable', 'El historial no está disponible. No se ha confirmado la operación.', 503)

    @bp.errorhandler(Exception)
    def unavailable(exc):
        from werkzeug.exceptions import HTTPException
        if isinstance(exc, HTTPException):
            return error('http_error', 'Solicitud no válida.', exc.code)
        app.logger.error('Panel failure type=%s', type(exc).__name__)
        return error('service_unavailable', 'No se pudo completar la consulta. Revisa el estado antes de repetir una acción.', 503)

    @bp.get('/manager/')
    def index():
        return send_from_directory(assets, 'index.html')

    @bp.get('/manager/static/<path:name>')
    def static_file(name):
        return send_from_directory(assets, name)

    @bp.get('/api/session')
    def get_session():
        return jsonify(info())

    @bp.post('/api/login')
    def login():
        ip = request.remote_addr or 'local'
        failures[ip] = [t for t in failures[ip] if time.time()-t < 300]
        if len(failures[ip]) >= 5:
            return error('rate_limited', 'Espera cinco minutos antes de volver a intentarlo.', 429)
        value = request.json.get('password')
        if not isinstance(value, str) or len(value) > 256 or not check_password_hash(password_hash, value):
            failures[ip].append(time.time())
            return error('invalid_password', 'Contraseña incorrecta.', 401)
        session.clear()
        session.update(admin=True, owner=secrets.token_urlsafe(24), login_at=time.time())
        return jsonify(info())

    @bp.post('/api/logout')
    def logout():
        session.clear()
        return jsonify(info())

    @bp.get('/api/chats')
    @admin
    def get_chats():
        return jsonify(chats=current_chats())

    @bp.post('/api/chats/<chat_id>/alias')
    @admin
    def set_chat_alias(chat_id):
        if chat_directory is None:
            return error('aliases_unavailable', 'Los alias persistentes no están disponibles en este modo.', 409)
        if set(request.json) != {'alias'}:
            raise ValueError()
        return jsonify(chat=chat_directory.set_alias(chat_id, request.json['alias']))

    def page_number():
        page = int(request.args.get('page', '1'))
        if page < 1 or page > 100000:
            raise ValueError()
        return page

    def public_row(row, labels=None):
        keys = ('id','operation_id','item_id','title','chat_id','status','message_id','error_type','source','actor','created_at','updated_at','attempt_count')
        labels=labels or current_labels()
        return dict({k: row[k] for k in keys}, chat_label=labels.get(row['chat_id'], row['chat_id']))

    @bp.get('/api/catalog')
    @admin
    def get_catalog():
        page = page_number()
        individual=request.args.get('individual')=='1'
        items = catalog.individual_list(request.args.get('query','')[:200]) if individual and hasattr(catalog,'individual_list') else catalog.list(request.args.get('query','')[:200])
        kind, chat, status = (request.args.get(k,'') for k in ('kind','chat_id','status'))
        chat_list=current_chats()
        output = []
        for raw in items:
            item = catalog.individual_present(raw) if individual and hasattr(catalog,'individual_present') else catalog.present(raw)
            item['states'] = {c['id']: store.item_status(item['id'], c['id']) for c in chat_list}
            if kind not in ('','all',item['kind']):
                continue
            if status and status not in ([item['states'].get(chat)] if chat else item['states'].values()):
                continue
            output.append(item)
        return jsonify(items=output[(page-1)*12:page*12], page=page, pages=max(1,(len(output)+11)//12), total=len(output))

    @bp.get('/api/artwork/<item_id>')
    @admin
    def artwork(item_id):
        return catalog.artwork(item_id)

    @bp.get('/api/history')
    @admin
    def history():
        page = page_number()
        clauses, params = [], []
        for name, col in [('status','d.status'),('chat_id','d.chat_id'),('item_id','o.item_id')]:
            value = request.args.get(name)
            if value:
                clauses.append(col+'=?'); params.append(value)
        where = ' AND '.join(clauses) or '1'
        with store.connection() as db:
            total = db.execute('SELECT count(*) FROM deliveries d JOIN operations o ON o.id=d.operation_id WHERE '+where, params).fetchone()[0]
            rows = store._rows(db, where, tuple(params)+ (10,(page-1)*10), 'LIMIT ? OFFSET ?')
        labels=current_labels()
        return jsonify(items=[public_row(r,labels) for r in rows], total=total,page=page,pages=max(1,(total+9)//10))

    @bp.get('/api/deliveries/<int:delivery_id>')
    @admin
    def detail(delivery_id):
        return jsonify(delivery=public_row(store.get(delivery_id)), attempts=store.attempts(delivery_id))

    def latest(item_id, chat_id, reconciliation=False):
        with store.connection() as db:
            where='o.item_id=? AND d.chat_id=?'
            params=(item_id,chat_id)
            if reconciliation:
                from .reconciliation import LIBRARY_SOURCES
                where+=' AND o.source IN ('+','.join('?' for _ in LIBRARY_SOURCES)+')'
                params+=LIBRARY_SOURCES
            rows = store._rows(db, where, params)
        return next((r for r in rows if r['status']=='sent'), rows[0] if rows else None)

    @bp.post('/api/prepare')
    @admin
    def prepare():
        labels=current_labels()
        body = request.json
        ids, targets = body.get('item_ids'), body.get('chat_ids')
        if not isinstance(ids,list) or not isinstance(targets,list) or not 1<=len(ids)<=20 or not 1<=len(targets)<=8:
            raise ValueError()
        if any(not isinstance(v,str) for v in ids+targets) or len(set(ids))!=len(ids) or len(set(targets))!=len(targets) or any(t not in labels for t in targets):
            raise ValueError()
        strategy, decisions = body.get('mode','recover'), body.get('decisions',{})
        if strategy not in ('recover','resend') or not isinstance(decisions,dict) or any(v not in ('send','skip') for v in decisions.values()):
            raise ValueError()
        pairs=[(catalog.get(item_id),chat) for item_id in ids for chat in targets]
        return jsonify(build_plan(pairs,strategy,decisions))

    def current_delivery(item_id,chat_id):
        delivery=latest(item_id,chat_id)
        if delivery is None:
            return dict(state='history_unknown',delivery_id=None,last_attempt=None,updated_at=None,
                        result='No existe historial local para este contenido y destino.')
        attempts=store.attempts(delivery['id'])
        attempt=attempts[-1] if attempts else None
        return dict(state=delivery['status'],delivery_id=delivery['id'],message_id=delivery['message_id'],
                    error_type=delivery['error_type'],updated_at=delivery['updated_at'],
                    attempt_count=delivery['attempt_count'],last_attempt={k:attempt.get(k) for k in
                    ('id','status','message_id','error_type','created_at','finished_at') if k in attempt} if attempt else None,
                    result='Mensaje confirmado por Telegram.' if delivery['status']=='sent' else
                    'El último intento falló y puede reintentarse.' if delivery['status']=='failed' else
                    'La publicación puede haberse aceptado; reenviar podría duplicarla.' if delivery['status']=='uncertain' else
                    'Todavía no consta un intento finalizado.')

    @bp.post('/api/individual-recovery/prepare')
    @admin
    def individual_prepare():
        labels=current_labels()
        body=request.json
        if set(body)-{'item_id','chat_id','decision'}:
            raise ValueError()
        item_id,chat_id,decision=body.get('item_id'),body.get('chat_id'),body.get('decision')
        if not isinstance(item_id,str) or not isinstance(chat_id,str) or chat_id not in labels or decision not in (None,'send','skip'):
            raise ValueError()
        decisions={} if decision is None else {item_id+'|'+chat_id:decision}
        plan=build_plan([(catalog.get(item_id),chat_id)],'recover',decisions,flow='individual')
        plan['current']=current_delivery(item_id,chat_id)
        # Persist the enriched plan so a refresh shows the same audited preview.
        with store.connection() as db:
            db.execute('UPDATE panel_batches SET plan=? WHERE id=?',(json.dumps(plan),plan['batch_id']))
        return jsonify(plan)

    def build_plan(pairs,strategy,decisions,scope=None,flow='batch'):
        labels=current_labels()
        rows=[]
        for item,chat in pairs:
            item_id=item['Id']
            base_caption=catalog.caption(item)
            caption = base_caption
            previous = latest(item_id,chat,scope is not None)
            state = previous['status'] if previous else 'history_unknown'
            key = item_id+'|'+chat
            decision = decisions.get(key)
            action = 'send'
            if strategy=='recover' and state=='sent':
                action='skip'
            elif strategy=='resend' and state=='sent' and decision!='send':
                action='skip'
            elif decision=='skip':
                action='skip'
            elif state in ('uncertain','history_unknown') and decision!='send':
                action='decision'
            elif strategy=='recover' and previous:
                action='retry'
                caption = previous['caption']
            rows.append(dict(key=key,item_id=item_id,title=item['Name'],chat_id=chat,chat_label=labels[chat],state=state,action=action,delivery_id=previous['id'] if previous else None,caption=caption,preview=caption.replace('[[EMBY_BOT_EXPANDABLE_START]]','').replace('[[EMBY_BOT_EXPANDABLE_END]]',''),caption_length=len(caption),caption_valid=len(caption)<=1024,duplicate_risk=state in ('sent','uncertain','history_unknown') and action in ('send','retry'),item={k:item[k] for k in ('Id','Name','Type','SeriesId','SeriesName','ParentId','ParentIndexNumber','IndexNumber') if k in item},explicit=decision=='send'))
        counts=Counter(r['action'] for r in rows)
        summary=dict(send=counts['send']+counts['retry'],skip=counts['skip'],decision=counts['decision'],duplicates=sum(r['duplicate_risk'] for r in rows))
        batch_id=secrets.token_urlsafe(24)
        expires=time.time()+900
        plan=dict(batch_id=batch_id,status='prepared',mode=strategy,flow=flow,expires_at=expires,rows=rows,summary=summary,can_confirm=not counts['decision'] and summary['send']>0 and all(r['caption_valid'] for r in rows if r['action'] in ('send','retry')))
        if scope:plan['scope']=scope
        with store.connection() as db:
            db.execute('INSERT INTO panel_batches VALUES (?,?,?, ?,NULL,?)',(batch_id,session['owner'],json.dumps(plan), 'prepared',expires))
        return plan

    def batch(batch_id):
        with store.connection() as db:
            row=db.execute('SELECT * FROM panel_batches WHERE id=?',(batch_id,)).fetchone()
        if row is None:
            return None,error('not_found','Lote no encontrado.',404)
        if row['owner']!=session['owner']:
            return None,error('forbidden','Este lote pertenece a otra sesión.',403)
        return dict(row),None

    @bp.get('/api/batches/<batch_id>')
    @admin
    def get_batch(batch_id):
        row,err=batch(batch_id)
        if err:return err
        result=json.loads(row['results']) if row['results'] else json.loads(row['plan'])
        result['status']=row['status']
        return jsonify(result)

    @bp.post('/api/batches/<batch_id>/confirm')
    @admin
    def confirm(batch_id):
        if not allow_sends:
            return error('sends_disabled','Las acciones de envío están desactivadas.',403)
        row,err=batch(batch_id)
        if err:return err
        if row['status']=='completed':return jsonify(json.loads(row['results']))
        if row['status']=='executing':return error('in_progress','La operación ya está en curso. Consulta su resultado antes de repetirla.',409)
        plan=json.loads(row['plan'])
        if row['status']!='prepared' or row['expires']<time.time():
            return error('batch_unavailable','La operación ya no se puede confirmar. Consulta su resultado y prepara una nueva.',409)
        if plan.get('flow')=='individual' and (plan.get('mode')!='recover' or len(plan.get('rows',[]))!=1):
            return error('invalid_individual_operation','La recuperación individual debe contener exactamente un contenido y un destino.',409)
        if request.json.get('confirm') is not True or not plan['can_confirm'] or (plan['summary']['duplicates'] and request.json.get('accept_duplicate_risk') is not True):
            return error('confirmation_required','Confirma las decisiones y el riesgo de duplicados.',409)
        if plan.get('scope'):
            record=reconciliation.get(plan['scope']['run_id'])
            if not record or reconciliation.config()['history_from']!=record['run']['scope']['history_from']:
                return error('stale_scope','El ámbito del historial ha cambiado. Repite la conciliación.',409)
        # A preview cannot authorize a newly uncertain delivery.
        for r in plan['rows']:
            if r['action']=='retry' and store.get(r['delivery_id'])['status']=='uncertain' and not r['explicit']:
                return error('stale_plan','El estado cambió. Prepara el lote de nuevo.',409)
        results=[]
        result=dict(batch_id=batch_id,status='interrupted',results=results,summary={})
        with store.connection() as db:
            if db.execute("UPDATE panel_batches SET status='executing',results=? WHERE id=? AND status='prepared'",(json.dumps(result),batch_id)).rowcount!=1:
                return error('in_progress','El lote ya está en curso.',409)
        try:
            for r in plan['rows']:
                entry={k:r[k] for k in ('key','item_id','title','chat_id','chat_label','delivery_id')}
                current=latest(r['item_id'],r['chat_id'],bool(plan.get('scope')))
                if r['action']=='skip' or (plan['mode']=='recover' and current and current['status']=='sent'):
                    entry.update(status='skipped',message_id=None,error_type=None)
                else:
                    key='panel:'+batch_id+':'+r['key']
                    if r['action']=='retry':
                        delivery=publications.retry(r['delivery_id'],key,allow_uncertain=r['explicit'])
                    else:
                        delivery=publications.publish(r['item'],r['caption'],[r['chat_id']],key,source='panel-'+mode,actor='admin')[0]
                    entry.update(status=delivery['status'],message_id=delivery['message_id'],error_type=delivery['error_type'],delivery_id=delivery['id'])
                results.append(entry)
                with store.connection() as db:
                    db.execute('UPDATE panel_batches SET results=? WHERE id=?',(json.dumps(result),batch_id))
            result['status']='completed'
        finally:
            result['summary']=result_summary(results)
            with store.connection() as db:
                db.execute('UPDATE panel_batches SET status=?,results=? WHERE id=?',(result['status'],json.dumps(result),batch_id))
        return jsonify(result)

    from .reconciliation import ReconciliationService, STATUSES, classify
    reconciliation=ReconciliationService(store,catalog,current_chats,mode)
    app.extensions['reconciliation']=reconciliation

    @bp.get('/api/reconciliation/config')
    @admin
    def reconciliation_config():return jsonify(reconciliation.config())

    @bp.post('/api/reconciliation/config')
    @admin
    def reconciliation_configure():
        if 'history_from' not in request.json:raise ValueError()
        return jsonify(reconciliation.configure(request.json['history_from']))

    @bp.post('/api/reconciliation/runs')
    @admin
    def reconciliation_run():return jsonify(reconciliation.run(request.json))

    @bp.get('/api/reconciliation/runs')
    @admin
    def reconciliation_history():return jsonify(reconciliation.history(page_number()))

    @bp.get('/api/reconciliation/runs/<run_id>')
    @admin
    def reconciliation_detail(run_id):
        record=reconciliation.get(run_id)
        if record is None:return error('not_found','Consulta no encontrada.',404)
        page=page_number();status=request.args.get('status','');chat=request.args.get('chat_id','');query=request.args.get('query','')[:200].casefold()
        if status and status not in STATUSES:raise ValueError()
        rows=[r for r in record['rows'] if (not status or r['status']==status) and (not chat or r['chat_id']==chat) and (not query or query in (r['title']+' '+(r.get('series_name') or '')).casefold())]
        return jsonify(run=record['run'],items=rows[(page-1)*20:page*20],total=len(rows),page=page,pages=max(1,(len(rows)+19)//20))

    @bp.post('/api/reconciliation/runs/<run_id>/prepare')
    @admin
    def reconciliation_prepare(run_id):
        record=reconciliation.get(run_id)
        if record is None:return error('not_found','Consulta no encontrada.',404)
        keys=request.json.get('keys');decisions=request.json.get('decisions',{})
        if not isinstance(keys,list) or not 1<=len(keys)<=20 or any(not isinstance(k,str) for k in keys) or len(set(keys))!=len(keys):raise ValueError()
        if not isinstance(decisions,dict) or any(k not in keys or v not in ('send','skip') for k,v in decisions.items()):raise ValueError()
        rows={r['key']:r for r in record['rows']};items={i['Id']:i for i in record['items']}
        if any(k not in rows for k in keys):raise ValueError()
        config=reconciliation.config();scope=record['run']['scope']
        if config['history_from']!=scope['history_from']:return error('stale_scope','El inicio del historial ha cambiado. Repite la conciliación.',409)
        pairs=[]
        for key in keys:
            row=rows[key];item=items[row['item_id']]
            # Recheck current evidence, while retaining the original scan scope.
            previous=latest(row['item_id'],row['chat_id'],True)
            current=classify(item,[previous] if previous else [],history_from=config['history_from'],date_from=scope['date_from'],date_to=scope['date_to'],complete=record['run']['complete'])
            if not row['can_prepare'] or (not current['can_prepare'] and current['status']!='delivered'):
                return error('outside_scope','Este elemento no permite recuperación en el ámbito consultado.',409)
            pairs.append((item,row['chat_id']))
        plan=build_plan(pairs,'recover',decisions,dict(type='reconciliation',run_id=run_id,keys=keys))
        plan['recovery_items']=[dict(id=i['Id'],title=i.get('Name','Contenido'),kind='episode' if i['Type']=='Episode' else 'movie',year=i.get('ProductionYear'),overview=i.get('Overview',''),image_url='/api/artwork/'+i['Id'] if mode=='demo' else None) for i in {i['Id']:i for i,c in pairs}.values()]
        return jsonify(plan)

    app.register_blueprint(bp)

class EmbyCatalog:
    """Bounded recent/search browser; omitted-content discovery belongs to EMBY-004."""
    def __init__(self, emby):self.emby=emby
    def reconciliation_libraries(self):return self.emby.get_libraries()
    def reconciliation_page(self,*,scenario='complete',**kwargs):return self.emby.get_library_page(**kwargs)
    def list(self, query=''):
        items=self.emby.search_items(query,limit=60) if query else self.emby.get_recently_added_items(limit=60)
        return [i for i in items if i.get('Type') in ('Movie','Series')]
    def individual_list(self,query=''):
        items=self.emby.search_items(query,limit=60,include_item_types='Movie,Episode') if query else self.emby.get_library_page(start_index=0,limit=60,item_types=('Movie','Episode')).get('Items',[])
        return [i for i in items if i.get('Type') in ('Movie','Episode')]
    def get(self,item_id):
        if not item_id or len(item_id)>100 or not all(c.isalnum() or c in '-_' for c in item_id):raise ValueError()
        item=self.emby.get_item_by_id(item_id)
        if not item or item.get('Type') not in ('Movie','Series','Episode'):raise ValueError()
        return item
    def present(self,item):
        return dict(id=str(item['Id']),title=item.get('Name','Contenido'),kind='movie' if item['Type']=='Movie' else 'series',year=item.get('ProductionYear'),overview=item.get('Overview',''),image_url='/api/artwork/'+str(item['Id']))
    def individual_present(self,item):
        episode=item.get('Type')=='Episode'
        season=item.get('ParentIndexNumber');number=item.get('IndexNumber')
        prefix=(item.get('SeriesName','Serie')+' · '+(('T'+str(season)) if season is not None else '')+(('E'+str(number).zfill(2)) if number is not None else '')+' · ') if episode else ''
        return dict(id=str(item['Id']),title=prefix+item.get('Name','Contenido'),kind='episode' if episode else 'movie',year=item.get('ProductionYear'),overview=item.get('Overview',''),image_url='/api/artwork/'+str(item['Id']))
    def caption(self,item):
        from .formatting import build_search_item_caption
        return build_search_item_caption(item)
    def artwork(self,item_id):
        from flask import Response
        image=self.emby.get_item_image(self.get(item_id))
        if image and image.startswith(b'\xff\xd8'):return Response(image,mimetype='image/jpeg')
        if image and image.startswith(b'\x89PNG'):return Response(image,mimetype='image/png')
        return Response(status=404)
