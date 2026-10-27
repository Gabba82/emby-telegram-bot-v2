"""Safe one-content/one-destination recovery, entirely offline."""
from __future__ import annotations

import json
import threading

import pytest

from emby_telegram_bot.demo import create_demo_app


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
    ('s1','demo-series','pending','retry'),
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


def test_individual_catalog_contains_movies_and_episodes_but_not_series(admin):
    client,_=admin
    body=client.get('/api/catalog?individual=1&page=1').get_json()
    kinds={item['kind'] for item in body['items']}
    assert kinds=={'movie','episode'}
    episode=next(item for item in body['items'] if item['kind']=='episode')
    assert episode['id'].startswith('e')
    assert 'T1E' in episode['title']


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
