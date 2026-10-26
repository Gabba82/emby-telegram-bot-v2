"""Exercise recovery through the original confirm engine, preserving exact pairs."""
import pytest
from emby_telegram_bot.demo import create_demo_app

@pytest.fixture
def panel(tmp_path):
    app=create_demo_app(tmp_path/'demo.sqlite3',secret_key='synthetic-test-key')
    client=app.test_client()
    csrf=client.get('/api/session').json['csrf_token']
    csrf=client.post('/api/login',json={'password':'emby-demo-003'},headers={'X-CSRF-Token':csrf}).json['csrf_token']
    def post(url,data):return client.post(url,json=data,headers={'X-CSRF-Token':csrf})
    run=post('/api/reconciliation/runs',{'chat_ids':['demo-cine','demo-series']}).json
    return app,client,post,run['run_id']


def test_exact_two_pairs_confirm_idempotent(panel):
    app,client,post,rid=panel
    keys=['e1|demo-cine','e2|demo-series']
    plan=post(f'/api/reconciliation/runs/{rid}/prepare',dict(keys=keys,decisions={k:'send' for k in keys})).json
    assert [r['key'] for r in plan['rows']]==keys
    result=post(f"/api/batches/{plan['batch_id']}/confirm",dict(confirm=True,accept_duplicate_risk=True))
    assert result.status_code==200 and [r['key'] for r in result.json['results']]==keys
    with app.extensions['delivery_store'].connection() as db:
        count=db.execute('SELECT count(*) FROM attempts').fetchone()[0]
        assert db.execute("SELECT count(*) FROM operations WHERE item_id IN ('e1','e2')").fetchone()[0]==2
    assert post(f"/api/batches/{plan['batch_id']}/confirm",dict(confirm=True,accept_duplicate_risk=True)).json==result.json
    with app.extensions['delivery_store'].connection() as db:assert db.execute('SELECT count(*) FROM attempts').fetchone()[0]==count
    newer=post('/api/reconciliation/runs',{'chat_ids':['demo-cine','demo-series']}).json
    rows=client.get(f"/api/reconciliation/runs/{newer['run_id']}?query=Capítulo+1").json['items']
    assert next(r for r in rows if r['key']=='e1|demo-cine')['status']=='delivered'
    # Original run remains an immutable snapshot.
    old=client.get(f'/api/reconciliation/runs/{rid}?query=Capítulo+1').json['items']
    assert next(r for r in old if r['key']=='e1|demo-cine')['status']=='possible_omission'


def test_scope_change_blocks_prepared_confirmation(panel):
    app,client,post,rid=panel
    plan=post(f'/api/reconciliation/runs/{rid}/prepare',dict(keys=['e1|demo-cine'],decisions={'e1|demo-cine':'send'})).json
    post('/api/reconciliation/config',{'history_from':None})
    response=post(f"/api/batches/{plan['batch_id']}/confirm",dict(confirm=True,accept_duplicate_risk=True))
    assert response.status_code==409 and response.json['error']=='stale_scope'


def test_unrelated_event_does_not_mark_episode_delivered(panel):
    app,client,post,rid=panel
    catalog=app.extensions['demo_catalog'];pub=app.extensions['publications']
    item=catalog.get('e1')
    pub.publish(item,'Unrelated playback event',['demo-cine'],'other-event',source='playback',actor='test')
    scan=post('/api/reconciliation/runs',{'chat_ids':['demo-cine']}).json
    rows=client.get(f"/api/reconciliation/runs/{scan['run_id']}?query=Capítulo+1").json['items']
    assert next(r for r in rows if r['key']=='e1|demo-cine')['status']=='possible_omission'
    plan=post(f"/api/reconciliation/runs/{scan['run_id']}/prepare",dict(keys=['e1|demo-cine'],decisions={'e1|demo-cine':'send'})).json
    result=post(f"/api/batches/{plan['batch_id']}/confirm",dict(confirm=True,accept_duplicate_risk=True)).json
    assert result['results'][0]['status']=='sent'
