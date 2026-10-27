"""Synthetic development app: real SQLite and PublicationService, no real clients."""
from html import escape
from flask import Flask, Response
from .deliveries import DeliveryStore
from .publications import PublicationService
from .telegram_client import SendResult
from .web_manager import register_manager

CHATS=[dict(id='demo-cine',label='Cine · pruebas',kind='channel'),dict(id='demo-series',label='Series · pruebas',kind='channel'),dict(id='demo-private',label='Laboratorio privado',kind='private')]
TITLES=['Órbita de invierno','La última estación','El mapa del silencio','Marea de cristal','Horizonte rojo','El jardín nocturno','Tiempo prestado','La ciudad invisible','Archivo Boreal','Los días del faro','La frontera azul','Código Aurora','Ecos del mañana','Distrito lunar']

class DemoCatalog:
    def __init__(self):
        self.items=[dict(Id=('m'+str(i+1) if i<8 else 's'+str(i-7)),Name=t,Type='Movie' if i<8 else 'Series',ProductionYear=2020+i%6,Overview='Una historia ficticia para explorar la biblioteca y preparar publicaciones sin conectar con servicios reales.') for i,t in enumerate(TITLES)]
    def reconciliation_libraries(self):
        return [dict(id='demo-movies',label='Películas de prueba',item_types=['Movie']),dict(id='demo-episodes',label='Episodios de prueba',item_types=['Episode'])]
    def reconciliation_items(self):
        movies=[dict(i,DateCreated='2026-10-05T10:00:00Z',LibraryId='demo-movies') for i in self.items if i['Type']=='Movie']
        episodes=[dict(Id='e'+str(n),Name='Capítulo '+str(n),Type='Episode',SeriesId='s1',SeriesName='Archivo Boreal',ParentIndexNumber=1,IndexNumber=n,DateCreated='2026-10-12T10:00:00Z',LibraryId='demo-episodes',ProductionYear=2026,Overview='Episodio sintético de conciliación.') for n in range(1,27)]
        episodes[-1]['DateCreated']=None
        episodes[-2]['DateCreated']='2026-09-01T10:00:00Z'
        return movies+episodes
    def reconciliation_page(self,*,start_index,limit,library_id,item_types,scenario='complete'):
        items=[i for i in self.reconciliation_items() if i['Type'] in item_types and (not library_id or i['LibraryId']==library_id)]
        if start_index and scenario=='timeout':raise TimeoutError('Synthetic timeout')
        page=items[start_index:start_index+limit]
        if start_index and scenario=='partial':page=[]
        if start_index and scenario=='duplicates':page=items[:limit]
        return dict(Items=page,TotalRecordCount=len(items))
    def list(self,query=''):
        return [i for i in self.items if query.casefold() in i['Name'].casefold()]
    def get(self,item_id):
        return next((i.copy() for i in self.items+self.reconciliation_items() if i['Id']==item_id),None) or self.missing()
    def missing(self):
        raise ValueError('Contenido no disponible')
    def present(self,item):
        return dict(id=item['Id'],title=item['Name'],kind='movie' if item['Type']=='Movie' else 'series',year=item['ProductionYear'],overview=item['Overview'],image_url='/api/artwork/'+item['Id'])
    def caption(self,item):
        return item['Name']+'\n'+('Película' if item['Type']=='Movie' else ('Episodio '+str(item.get('IndexNumber','')) if item['Type']=='Episode' else 'Serie'))+'\n\n[DEMO · publicación simulada]'
    def artwork(self,item_id):
        item=self.get(item_id)
        hue=(sum(ord(c) for c in item_id)*37)%360
        title=escape(item['Name'])
        svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600" viewBox="0 0 400 600"><defs><linearGradient id="g" x2="1" y2="1"><stop stop-color="hsl({hue},55%,22%)"/><stop offset="1" stop-color="#090e18"/></linearGradient></defs><rect width="400" height="600" fill="url(#g)"/><circle cx="200" cy="225" r="120" fill="none" stroke="hsl({hue},75%,65%)" stroke-width="2"/><circle cx="200" cy="225" r="80" fill="hsl({hue},50%,38%)"/><path d="M0 400L400 180V600H0" fill="#090e18" opacity=".6"/><text x="28" y="470" fill="#fff" font-family="sans-serif" font-size="24">{title}</text><text x="28" y="515" fill="#e5c58a" font-family="sans-serif" font-size="14">EMBY · COLECCIÓN DEMO</text></svg>'
        return Response(svg,mimetype='image/svg+xml')

class DemoTelegram:
    def __init__(self,store):self.store=store
    def send(self,caption,image,chat_ids):
        results=[]
        with self.store.connection() as db:
            for chat in chat_ids:
                attempt=db.execute('SELECT a.id,a.delivery_id FROM attempts a JOIN deliveries d ON d.id=a.delivery_id WHERE d.chat_id=? AND a.finished_at IS NULL ORDER BY a.id DESC LIMIT 1',(chat,)).fetchone()
                count=db.execute('SELECT count(*) FROM attempts WHERE delivery_id=?',(attempt['delivery_id'],)).fetchone()[0]
                status='uncertain' if chat=='demo-private' else 'failed' if chat=='demo-series' and count==1 else 'sent'
                results.append(SendResult(chat,status,100000+attempt['id'] if status=='sent' else None, 'DemoTimeout' if status=='uncertain' else 'DemoForbidden' if status=='failed' else None))
        return results

def create_demo_app(db_path, password='emby-demo-003', secret_key=None):
    app=Flask(__name__,static_folder=None)
    app.secret_key=secret_key
    store=DeliveryStore(str(db_path))
    catalog=DemoCatalog()
    publications=PublicationService(store,DemoTelegram(store),lambda item:None)
    app.extensions.update(delivery_store=store,publications=publications,demo_catalog=catalog)
    register_manager(app,store,publications,catalog,CHATS,password=password,mode='demo',allow_sends=True)
    # Idempotent seed keys mean restarting never adds another publication.
    for item_id,chat in [('m1','demo-cine'),('m2','demo-series'),('m3','demo-private')]:
        item=catalog.get(item_id)
        publications.publish(item,catalog.caption(item),[chat],'demo-seed:'+item_id,source='demo-seed',actor='demo')
    item=catalog.get('s1')
    publications.prepare(item,catalog.caption(item),['demo-series'],'demo-seed:s1','demo-seed','demo')
    item=catalog.get('e3')
    publications.prepare(item,catalog.caption(item),['demo-cine'],'demo-seed:e3','demo-seed','demo')
    @app.get('/')
    def root():
        from flask import redirect
        return redirect('/manager/')
    @app.get('/health')
    def health():return dict(status='ok',mode='demo',real_sends=False)
    return app
