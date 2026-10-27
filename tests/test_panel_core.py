import pytest
from emby_telegram_bot.demo import create_demo_app

@pytest.fixture
def panel(tmp_path):
    app=create_demo_app(tmp_path/'demo.sqlite3',secret_key='test-session-secret')
    app.config['TESTING']=True
    client=app.test_client()
    token=client.get('/api/session').json['csrf_token']
    login=client.post('/api/login',json={'password':'emby-demo-003'},headers={'X-CSRF-Token':token})
    return app,client,{'X-CSRF-Token':login.json['csrf_token']}

def plan(client,headers,**changes):
    data=dict(item_ids=['m4'],chat_ids=['demo-cine'],mode='recover',decisions={'m4|demo-cine':'send'})
    data.update(changes)
    return client.post('/api/prepare',json=data,headers=headers)

def test_confirm_replay_and_restart(panel,tmp_path):
    app,c,h=panel
    b=plan(c,h).json
    path='/api/batches/'+b['batch_id']+'/confirm'
    result=c.post(path,json={'confirm':True,'accept_duplicate_risk':True},headers=h)
    assert result.status_code==200 and result.json['results'][0]['status']=='sent'
    assert c.post(path,json={'confirm':True,'accept_duplicate_risk':True},headers=h).json==result.json
    store=app.extensions['delivery_store']
    assert len(store.attempts(result.json['results'][0]['delivery_id']))==1
    restarted=create_demo_app(store.path)
    assert restarted.extensions['delivery_store'].item_status('m4','demo-cine')=='sent'

def test_auth_csrf_and_owner(panel):
    app,c,h=panel
    assert app.test_client().get('/api/history').status_code==401
    assert c.post('/api/prepare',json={}).status_code==403
    b=plan(c,h).json
    second=app.test_client()
    csrf=second.get('/api/session').json['csrf_token']
    second.post('/api/login',json={'password':'emby-demo-003'},headers={'X-CSRF-Token':csrf})
    assert second.get('/api/batches/'+b['batch_id']).status_code==403

def test_recover_skips_sent_requires_unknown(panel):
    app,c,h=panel
    assert plan(c,h,item_ids=['m1'],decisions={}).json['rows'][0]['action']=='skip'
    assert not plan(c,h,decisions={}).json['can_confirm']

def test_failed_retry_and_uncertain(panel):
    app,c,h=panel
    b=plan(c,h,item_ids=['m2'],chat_ids=['demo-series'],decisions={}).json
    assert b['rows'][0]['action']=='retry'
    r=c.post('/api/batches/'+b['batch_id']+'/confirm',json={'confirm':True},headers=h)
    assert r.json['results'][0]['status']=='sent'
    b=plan(c,h,item_ids=['m3'],chat_ids=['demo-private'],decisions={}).json
    assert b['rows'][0]['action']=='decision' and not b['can_confirm']

def test_stale_retry_blocks_new_uncertainty(panel):
    app,c,h=panel
    b=plan(c,h,item_ids=['s1'],chat_ids=['demo-series'],decisions={}).json
    store=app.extensions['delivery_store']
    store.claim(b['rows'][0]['delivery_id'],'another-operation')
    r=c.post('/api/batches/'+b['batch_id']+'/confirm',json={'confirm':True},headers=h)
    assert r.status_code==409

def test_bad_ids_and_duplicate_targets(panel):
    app,c,h=panel
    assert plan(c,h,chat_ids=['demo-cine','demo-cine']).status_code==400
    assert plan(c,h,item_ids=['missing']).status_code==400
    assert plan(c,h,chat_ids=['real-chat']).status_code==400

def test_frozen_payload_and_expiry(panel):
    app,c,h=panel
    b=plan(c,h).json
    app.extensions['demo_catalog'].items[3]['Name']='Nombre cambiado después del plan'
    path='/api/batches/'+b['batch_id']+'/confirm'
    r=c.post(path,json={'confirm':True,'accept_duplicate_risk':True},headers=h)
    delivery=app.extensions['delivery_store'].get(r.json['results'][0]['delivery_id'])
    assert delivery['title']==b['rows'][0]['title']
    assert delivery['caption']==b['rows'][0]['caption']
    b=plan(c,h,item_ids=['m5'],decisions={'m5|demo-cine':'send'}).json
    with app.extensions['delivery_store'].connection() as db:
        db.execute('UPDATE panel_batches SET expires=0 WHERE id=?',(b['batch_id'],))
    assert c.post('/api/batches/'+b['batch_id']+'/confirm',json={'confirm':True,'accept_duplicate_risk':True},headers=h).status_code==409

def test_disabled_operational_adapter_and_safe_errors(panel):
    from flask import Flask
    from emby_telegram_bot.web_manager import register_manager
    from emby_telegram_bot.demo import CHATS
    app,c,h=panel
    operation=Flask('operational-test')
    register_manager(operation,app.extensions['delivery_store'],app.extensions['publications'],app.extensions['demo_catalog'],CHATS,password='test-password',mode='operational')
    client=operation.test_client()
    csrf=client.get('/api/session').json['csrf_token']
    login=client.post('/api/login',json={'password':'test-password'},headers={'X-CSRF-Token':csrf}).json
    assert login['mode']=='operational' and not login['sends_enabled']
    headers={'X-CSRF-Token':login['csrf_token']}
    assert client.post('/api/batches/anything/confirm',json={'confirm':True},headers=headers).status_code==403
    individual=client.post('/api/individual-recovery/prepare',json={
        'item_id':'m4','chat_id':'demo-cine','decision':'send'},headers=headers)
    assert individual.status_code==200
    blocked=client.post('/api/batches/'+individual.json['batch_id']+'/confirm',json={
        'confirm':True,'accept_duplicate_risk':True},headers=headers)
    assert blocked.status_code==403 and blocked.json['error']=='sends_disabled'

def test_storage_failure_prevents_publish(panel,monkeypatch):
    import sqlite3
    app,c,h=panel
    store=app.extensions['delivery_store']
    b=plan(c,h).json
    def fail(*a,**kw):raise sqlite3.OperationalError('deliberate error')
    monkeypatch.setattr(store,'connection',fail)
    r=c.post('/api/batches/'+b['batch_id']+'/confirm',json={'confirm':True,'accept_duplicate_risk':True},headers=h)
    assert r.status_code==503
    assert 'deliberate' not in r.text

def test_voluntary_resend_requires_individual_selection(panel):
    app,c,h=panel
    b=plan(c,h,item_ids=['m1'],mode='resend',decisions={}).json
    assert b['rows'][0]['action']=='skip' and not b['can_confirm']
    b=plan(c,h,item_ids=['m1'],mode='resend',decisions={'m1|demo-cine':'send'}).json
    assert b['rows'][0]['action']=='send' and b['rows'][0]['duplicate_risk']
