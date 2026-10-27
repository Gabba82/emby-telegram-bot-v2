"""Focused invariants for complete scans and classification, with no network."""
import pytest
from emby_telegram_bot.reconciliation import collect_pages, classify
from emby_telegram_bot.reconciliation import ReconciliationService
from emby_telegram_bot.deliveries import DeliveryStore
from emby_telegram_bot.emby_client import EmbyClient


def test_raw_offsets_and_cross_library_duplicates():
    calls=[]
    def fetch(**kw):
        calls.append((kw['library_id'],kw['start_index']))
        data=[dict(Id=str(i),Type='Movie') for i in range(5)]
        return dict(Items=data[kw['start_index']:kw['start_index']+kw['limit']],TotalRecordCount=5)
    result=collect_pages(fetch,['a','b'],['Movie'],page_size=2)
    assert result['complete'] and len(result['items'])==5 and result['duplicates']==5
    assert calls==[(lib,n) for lib in ['a','b'] for n in [0,2,4]]


@pytest.mark.parametrize('payload', [None,{},dict(Items=[]),dict(Items=[],TotalRecordCount=True),dict(Items=[],TotalRecordCount=-1),dict(Items=[{}],TotalRecordCount=1)])
def test_malformed_pages_never_complete(payload):
    result=collect_pages(lambda **kw:payload,[],['Movie'])
    assert not result['complete'] and result['issues']


def test_repeated_pages_stop_without_loop():
    result=collect_pages(lambda **kw:dict(Items=[dict(Id='x',Type='Movie')],TotalRecordCount=999),[],['Movie'],page_size=1)
    assert result['pages']==2 and not result['complete'] and result['duplicates']==1


def test_timeout_preserves_known_page_sanitizes_error():
    def fetch(**kw):
        if kw['start_index']:raise TimeoutError('https://secret/?api_key=private')
        return dict(Items=[dict(Id='x',Type='Movie')],TotalRecordCount=2)
    result=collect_pages(fetch,[],['Movie'],page_size=1)
    assert len(result['items'])==1 and not result['complete']
    assert 'secret' not in str(result) and 'private' not in str(result)


@pytest.mark.parametrize('date,complete,start,expected', [
 ('2026-10-05T00:00:00Z',True,'2026-10-01','possible_omission'),
 ('2026-09-05T00:00:00Z',True,'2026-10-01','history_unknown'),
 (None,True,'2026-10-01','history_unknown'),
 ('garbage',True,'2026-10-01','history_unknown'),
 ('2026-10-05T00:00:00Z',False,'2026-10-01','history_unknown'),
 ('2026-10-05T00:00:00Z',True,None,'history_unknown'),
])
def test_omission_requires_reliable_history_and_complete_scan(date,complete,start,expected):
    row=classify(dict(Type='Episode',DateCreated=date),[],history_from=start,date_from=None,date_to=None,complete=complete)
    assert row['status']==expected


def test_confirmed_delivery_survives_later_failure():
    rows=[dict(id=2,status='failed'),dict(id=1,status='sent',attempt_count=1)]
    result=classify(dict(Type='Movie'),rows,history_from=None,date_from=None,date_to=None,complete=False)
    assert result['status']=='delivered' and not result['can_prepare'] and result['delivery_id']==1


def test_classification_rejects_unsupported_type_even_with_evidence():
    result=classify(dict(Type='Playlist',DateCreated='2026-10-05T00:00:00Z'),[dict(id=1,status='sent')],history_from='2026-10-01',date_from=None,date_to=None,complete=True)
    assert result['status']=='history_unknown'
    assert not result['eligible'] and not result['can_prepare'] and result['delivery_id'] is None


def test_client_requests_raw_episode_pagination(monkeypatch):
    calls=[]
    class Response:
        def json(self):return dict(Items=[],TotalRecordCount=0)
    client=EmbyClient('http://synthetic.invalid','synthetic-key',3)
    monkeypatch.setattr(client,'_get',lambda path,params: calls.append((path,params)) or Response())
    client.get_library_page(start_index=400,limit=200,library_id='lib',item_types=['Episode'])
    path,params=calls[0]
    assert path=='Items' and params['StartIndex']==400 and params['Limit']==200
    assert params['IncludeItemTypes']=='Episode' and params['Recursive']=='true' and params['ParentId']=='lib'


def test_libraries_expose_only_compatible_media_folders(monkeypatch):
    class Response:
        def json(self):return dict(Items=[
            dict(Id='movies',Name='Pelis',CollectionType='movies',Path='/private/movies'),
            dict(Id='series',Name='Series',CollectionType='tvshows',Path='/private/series'),
            dict(Id='playlists',Name='Lista de reproducción',CollectionType='playlists'),
            dict(Id='collections',Name='Colecciones',CollectionType='boxsets'),
            dict(Id='music-videos',Name='Videos musicales',CollectionType='musicvideos'),
            dict(Id='unknown',Name='Vista sin tipo'),
        ])
    client=EmbyClient('http://synthetic.invalid','synthetic-key',3)
    calls=[]
    monkeypatch.setattr(client,'_get',lambda path: calls.append(path) or Response())
    assert client.get_libraries()==[
        dict(id='movies',label='Pelis',item_types=['Movie']),
        dict(id='series',label='Series',item_types=['Episode']),
    ]
    assert calls==['Library/MediaFolders']


def test_unexpected_types_make_scan_partial_and_are_diagnosed():
    payload=dict(Items=[
        dict(Id='movie-1',Type='Movie'),
        dict(Id='playlist-1',Type='Playlist'),
        dict(Id='boxset-1',Type='BoxSet'),
    ],TotalRecordCount=3)
    result=collect_pages(lambda **kw:payload,['movies'],['Movie'],page_size=3)
    assert not result['complete']
    assert result['unexpected_types']=={'Playlist':1,'BoxSet':1}
    assert [item['Id'] for item in result['items']]==['movie-1']
    assert result['issues'][0]['code']=='UnexpectedType'


def test_service_defaults_to_safe_libraries_and_narrows_each_query(tmp_path):
    class Catalog:
        def __init__(self):self.calls=[]
        def reconciliation_libraries(self):
            return [
                dict(id='movies',label='Pelis',item_types=['Movie']),
                dict(id='series',label='Series',item_types=['Episode']),
            ]
        def reconciliation_page(self,**kwargs):
            self.calls.append(kwargs)
            return dict(Items=[],TotalRecordCount=0)
    catalog=Catalog()
    service=ReconciliationService(DeliveryStore(str(tmp_path/'history.sqlite3')),catalog,[dict(id='chat',label='Novedades')],'operational')
    summary=service.run({'chat_ids':['chat']})
    assert summary['complete']
    assert summary['scope']['library_ids']==['movies','series']
    assert [(call['library_id'],call['item_types']) for call in catalog.calls]==[
        ('movies',['Movie']),('series',['Episode'])
    ]


def test_service_rejects_empty_or_unknown_library_selection(tmp_path):
    class Catalog:
        def reconciliation_libraries(self):return [dict(id='movies',label='Pelis',item_types=['Movie'])]
    service=ReconciliationService(DeliveryStore(str(tmp_path/'history.sqlite3')),Catalog(),[dict(id='chat',label='Novedades')],'operational')
    with pytest.raises(ValueError):service.run({'chat_ids':['chat'],'library_ids':[]})
    with pytest.raises(ValueError):service.run({'chat_ids':['chat'],'library_ids':['playlists']})
