"""Safe one-content/one-destination recovery, entirely offline."""
from __future__ import annotations

import json
import threading

import pytest

from emby_telegram_bot.demo import create_demo_app
from emby_telegram_bot.telegram_client import SendResult


PASSWORD = "emby-demo-003"


def login(client):
    token=client.get('/api/session').get_json()['csrf_token']
    response=client.post('/api/login',json={'password':PASSWORD},headers={'X-CSRF-Token':token})
    assert response.status_code==200
    return response.get_json()['csrf_token']


def post(client,path,body,token):
    return client.post(path,json=body,headers={'X-CSRF-Token':token})


def prepare(client,token,item_id,chat_id,decision=None):
    body={'item_id':item_id,'chat_id':chat_id}
    if decision is not None:body['decision']=decision
    return post(client,'/api/individual-recovery/prepare',body,token)


@pytest.fixture
def app(tmp_path):
    return create_demo_app(str(tmp_path/'history.sqlite3'),secret_key='individual-secret')


@pytest.fixture
def admin(app):
    client=app.test_client()
    return client,login(client)


def test_sent_is_visible_and_cannot_be_resent(admin,app):
    client,token=admin
    before=len(app.extensions['delivery_store'].attempts(1))
    response=prepare(client,token,'m1','demo-cine')
    assert response.status_code==200
    plan=response.get_json()
    assert plan['flow']=='individual'
    assert plan['current']['state']=='sent'
    assert plan['current']['message_id'] is not None
    assert plan['rows'][0]['action']=='skip'
    assert plan['can_confirm'] is False
    confirm=post(client,f"/api/batches/{plan['batch_id']}/confirm",{'confirm':True},token)
    assert confirm.status_code==409
    assert len(app.extensions['delivery_store'].attempts(1))==before


@pytest.mark.parametrize(('item_id','chat_id','state','action'),[
    ('e3','demo-cine','pending','retry'),
    ('m2','demo-series','failed','retry'),
    ('m3','demo-private','uncertain','decision'),
    ('m4','demo-cine','history_unknown','decision'),
])
def test_current_state_and_action_are_explained(admin,item_id,chat_id,state,action):
    client,token=admin
    plan=prepare(client,token,item_id,chat_id).get_json()
    assert plan['current']['state']==state
    assert plan['rows'][0]['state']==state
    assert plan['rows'][0]['action']==action
    assert isinstance(plan['current']['result'],str) and plan['current']['result']
    if state in ('uncertain','history_unknown'):
        assert plan['can_confirm'] is False
        assert plan['summary']['decision']==1


@pytest.mark.parametrize(('item_id','chat_id'),[
    ('m3','demo-private'),
    ('m4','demo-cine'),
])
def test_uncertain_or_unknown_requires_explicit_duplicate_decision(admin,item_id,chat_id):
    client,token=admin
    blocked=prepare(client,token,item_id,chat_id).get_json()
    assert blocked['can_confirm'] is False
    plan=prepare(client,token,item_id,chat_id,'send').get_json()
    assert plan['can_confirm'] is True
    assert plan['rows'][0]['explicit'] is True
    without_risk=post(client,f"/api/batches/{plan['batch_id']}/confirm",{'confirm':True},token)
    assert without_risk.status_code==409
    response=post(client,f"/api/batches/{plan['batch_id']}/confirm",
                  {'confirm':True,'accept_duplicate_risk':True},token)
    assert response.status_code==200
    assert len(response.get_json()['results'])==1


def test_confirmation_replay_returns_saved_result_without_another_attempt(admin,app):
    client,token=admin
    plan=prepare(client,token,'m2','demo-series').get_json()
    original_caption=app.extensions['delivery_store'].get(plan['rows'][0]['delivery_id'])['caption']
    path=f"/api/batches/{plan['batch_id']}/confirm"
    first=post(client,path,{'confirm':True},token)
    assert first.status_code==200
    delivery_id=first.get_json()['results'][0]['delivery_id']
    attempt_count=len(app.extensions['delivery_store'].attempts(delivery_id))
    second=post(client,path,{'confirm':True},token)
    assert second.status_code==200
    assert second.get_json()==first.get_json()
    assert len(app.extensions['delivery_store'].attempts(delivery_id))==attempt_count
    assert app.extensions['delivery_store'].attempts(delivery_id)[-1]['caption']==original_caption


def test_enabled_confirmation_uses_existing_engine_with_artwork_text_and_idempotency(admin,app,monkeypatch):
    client,token=admin
    publications=app.extensions['publications']
    image=b'fake-jpeg-bytes'
    calls=[]
    monkeypatch.setattr(publications,'image_loader',lambda item:image)

    def fake_send(caption,sent_image,chat_ids):
        calls.append((caption,sent_image,list(chat_ids)))
        return [SendResult(chat_ids[0],'sent',4242)]

    monkeypatch.setattr(publications.telegram,'send',fake_send)
    plan=prepare(client,token,'m4','demo-cine','send').get_json()
    path=f"/api/batches/{plan['batch_id']}/confirm"
    first=post(client,path,{'confirm':True,'accept_duplicate_risk':True},token)
    assert first.status_code==200
    assert calls==[(plan['rows'][0]['caption'],image,['demo-cine'])]
    assert first.get_json()['results'][0]['message_id']==4242
    replay=post(client,path,{'confirm':True,'accept_duplicate_risk':True},token)
    assert replay.status_code==200
    assert calls==[(plan['rows'][0]['caption'],image,['demo-cine'])]


def test_expired_operation_cannot_be_confirmed(admin,app):
    client,token=admin
    plan=prepare(client,token,'m2','demo-series').get_json()
    with app.extensions['delivery_store'].connection() as db:
        db.execute('UPDATE panel_batches SET expires=0 WHERE id=?',(plan['batch_id'],))
    response=post(client,f"/api/batches/{plan['batch_id']}/confirm",{'confirm':True},token)
    assert response.status_code==409
    assert response.get_json()['error']=='batch_unavailable'


def test_endpoint_enforces_auth_csrf_destination_and_one_by_one(admin,app):
    client,token=admin
    anonymous=app.test_client()
    anon_token=anonymous.get('/api/session').get_json()['csrf_token']
    assert post(anonymous,'/api/individual-recovery/prepare',{'item_id':'m4','chat_id':'demo-cine'},anon_token).status_code==401
    assert client.post('/api/individual-recovery/prepare',json={'item_id':'m4','chat_id':'demo-cine'}).status_code==403
    assert prepare(client,token,'m4','not-configured').status_code==400
    response=post(client,'/api/individual-recovery/prepare',
                  {'item_id':'m4','chat_id':'demo-cine','item_ids':['m4','m5']},token)
    assert response.status_code==400


@pytest.mark.parametrize('unsupported_type',['Series','Playlist','BoxSet','Audio'])
def test_direct_api_rejects_unsupported_types_without_persisting_plan_or_delivery(admin,app,monkeypatch,unsupported_type):
    client,token=admin
    store=app.extensions['delivery_store']
    catalog=app.extensions['demo_catalog']
    original=catalog.get
    item_id='s1' if unsupported_type=='Series' else 'unsupported-'+unsupported_type.lower()
    if unsupported_type!='Series':
        monkeypatch.setattr(catalog,'get',lambda value: {
            'Id':value,'Name':'No admitido','Type':unsupported_type
        } if value==item_id else original(value))
    with store.connection() as db:
        before=(db.execute('SELECT count(*) FROM panel_batches').fetchone()[0],
                db.execute('SELECT count(*) FROM operations').fetchone()[0],
                db.execute('SELECT count(*) FROM deliveries').fetchone()[0],
                db.execute('SELECT count(*) FROM attempts').fetchone()[0])
    response=prepare(client,token,item_id,'demo-cine')
    assert response.status_code==400
    assert response.get_json()['error']=='invalid_request'
    with store.connection() as db:
        after=(db.execute('SELECT count(*) FROM panel_batches').fetchone()[0],
               db.execute('SELECT count(*) FROM operations').fetchone()[0],
               db.execute('SELECT count(*) FROM deliveries').fetchone()[0],
               db.execute('SELECT count(*) FROM attempts').fetchone()[0])
    assert after==before


def test_individual_catalog_contains_movies_and_episodes_but_not_series(admin):
    client,_=admin
    body=client.get('/api/catalog?individual=1&page=1').get_json()
    kinds={item['kind'] for item in body['items']}
    assert kinds=={'movie','episode'}
    episode=next(item for item in body['items'] if item['kind']=='episode')
    assert episode['id'].startswith('e')
    assert 'T1E' in episode['title']
    assert all(item['image_url']==f"/api/artwork/{item['id']}" for item in body['items'])


def test_simultaneous_confirmation_allows_one_executor(admin,app,monkeypatch):
    client,token=admin
    plan=prepare(client,token,'m2','demo-series').get_json()
    path=f"/api/batches/{plan['batch_id']}/confirm"
    entered=threading.Event();release=threading.Event()
    original=app.extensions['publications'].retry

    def delayed(*args,**kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args,**kwargs)

    monkeypatch.setattr(app.extensions['publications'],'retry',delayed)
    with client.session_transaction() as session:
        session_data=dict(session)
    worker=app.test_client()
    with worker.session_transaction() as session:
        session.update(session_data)
    output=[]
    thread=threading.Thread(target=lambda:output.append(post(worker,path,{'confirm':True},token)))
    thread.start()
    assert entered.wait(5)
    competing=post(client,path,{'confirm':True},token)
    release.set();thread.join(5)
    assert competing.status_code==409
    assert competing.get_json()['error']=='in_progress'
    assert len(output)==1 and output[0].status_code==200


def test_unknown_plan_becomes_stale_if_delivery_appears_before_confirmation(admin,app):
    client,token=admin
    plan=prepare(client,token,'m4','demo-cine','send').get_json()
    catalog=app.extensions['demo_catalog'];publications=app.extensions['publications']
    item=catalog.get('m4')
    created=publications.prepare(item,catalog.caption(item),['demo-cine'],'concurrent-intent','automatic')
    assert created[0]['status']=='pending'
    attempts_before=len(app.extensions['delivery_store'].attempts(created[0]['id']))
    response=post(client,f"/api/batches/{plan['batch_id']}/confirm",
                  {'confirm':True,'accept_duplicate_risk':True},token)
    assert response.status_code==409
    assert response.get_json()['error']=='stale_plan'
    assert len(app.extensions['delivery_store'].attempts(created[0]['id']))==attempts_before==0
    saved=client.get(f"/api/batches/{plan['batch_id']}").get_json()
    assert saved['status']=='interrupted' and saved['error']=='stale_plan'


def test_plan_is_skipped_if_delivery_was_confirmed_before_confirmation(admin,app):
    client,token=admin
    plan=prepare(client,token,'m4','demo-cine','send').get_json()
    catalog=app.extensions['demo_catalog'];publications=app.extensions['publications']
    item=catalog.get('m4')
    sent=publications.publish(item,catalog.caption(item),['demo-cine'],'concurrent-sent','automatic')[0]
    assert sent['status']=='sent'
    response=post(client,f"/api/batches/{plan['batch_id']}/confirm",
                  {'confirm':True,'accept_duplicate_risk':True},token)
    assert response.status_code==200
    assert response.get_json()['results'][0]['status']=='skipped'
    assert len(app.extensions['delivery_store'].attempts(sent['id']))==1


def test_restart_marks_executing_operation_interrupted_and_preserves_trace(tmp_path):
    db_path=tmp_path/'history.sqlite3'
    app=create_demo_app(str(db_path),secret_key='restart-secret')
    client=app.test_client();token=login(client)
    plan=prepare(client,token,'m4','demo-cine','send').get_json()
    partial={'batch_id':plan['batch_id'],'status':'interrupted','results':[
        {'key':'m4|demo-cine','item_id':'m4','chat_id':'demo-cine','status':'uncertain'}],
        'summary':{}}
    with app.extensions['delivery_store'].connection() as db:
        db.execute("UPDATE panel_batches SET status='executing',results=? WHERE id=?",
                   (json.dumps(partial),plan['batch_id']))
    cookie=client.get_cookie('session').value

    restarted=create_demo_app(str(db_path),secret_key='restart-secret')
    resumed=restarted.test_client();resumed.set_cookie('session',cookie)
    result=resumed.get(f"/api/batches/{plan['batch_id']}")
    assert result.status_code==200
    body=result.get_json()
    assert body['status']=='interrupted'
    assert body['results'][0]['status']=='uncertain'
    assert body['summary']['uncertain']==1
    retry=post(resumed,f"/api/batches/{plan['batch_id']}/confirm",{'confirm':True},token)
    assert retry.status_code==409
    assert retry.get_json()['error']=='batch_unavailable'
