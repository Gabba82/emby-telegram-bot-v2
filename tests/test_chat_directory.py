import pytest

from emby_telegram_bot.chat_directory import ChatDirectory
from emby_telegram_bot.deliveries import DeliveryStore
from emby_telegram_bot.demo import create_demo_app
from emby_telegram_bot.telegram_client import TelegramClient


class FakeTelegram:
    def __init__(self, names=None, failure=False):
        self.names = names or {}
        self.failure = failure
        self.calls = []

    def validate_chat(self, chat_id):
        self.calls.append(chat_id)
        if self.failure:
            raise TimeoutError("Telegram unavailable")
        return self.names.get(chat_id, chat_id)


def login(client):
    csrf = client.get('/api/session').json['csrf_token']
    response = client.post('/api/login', json={'password': 'emby-demo-003'}, headers={'X-CSRF-Token': csrf})
    return {'X-CSRF-Token': response.json['csrf_token']}


def test_real_names_aliases_and_ids_remain_separate(tmp_path):
    store = DeliveryStore(str(tmp_path/'history.sqlite3'))
    telegram = FakeTelegram({'-1001': 'Notificaciones Emby', '-1002': 'Emby'})
    directory = ChatDirectory(store, telegram, ['-1001', '-1002'], {'-1001': 'Novedades'})

    chats = directory.refresh_names()

    assert chats == [
        dict(id='-1001', label='Novedades', telegram_name='Notificaciones Emby', alias='Novedades', kind='channel'),
        dict(id='-1002', label='Emby', telegram_name='Emby', alias=None, kind='channel'),
    ]
    assert [chat['id'] for chat in chats] == ['-1001', '-1002']
    assert store.connection is not None
    with store.connection() as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 1


def test_cached_name_and_alias_survive_telegram_failure_and_restart(tmp_path):
    path = tmp_path/'history.sqlite3'
    first = ChatDirectory(DeliveryStore(str(path)), FakeTelegram({'-1001': 'Notificaciones Emby'}), ['-1001'])
    first.refresh_names()
    first.set_alias('-1001', 'Novedades')

    failed = FakeTelegram(failure=True)
    restarted = ChatDirectory(DeliveryStore(str(path)), failed, ['-1001'])
    restarted.refresh_names()

    assert failed.calls == ['-1001']
    assert restarted.list()[0] == dict(
        id='-1001', label='Novedades', telegram_name='Notificaciones Emby', alias='Novedades', kind='channel'
    )


def test_unresolved_chat_falls_back_to_id(tmp_path):
    directory = ChatDirectory(DeliveryStore(str(tmp_path/'history.sqlite3')), FakeTelegram(failure=True), ['-1009'])
    assert directory.refresh_names()[0] == dict(
        id='-1009', label='-1009', telegram_name=None, alias=None, kind='channel'
    )


def test_alias_validation_never_changes_known_ids(tmp_path):
    path = tmp_path/'history.sqlite3'
    directory = ChatDirectory(DeliveryStore(str(path)), FakeTelegram(), ['-1001'])
    assert directory.set_alias('-1001', '  Grupo general  ')['alias'] == 'Grupo general'
    assert directory.set_alias('-1001', '')['label'] == '-1001'
    restarted = ChatDirectory(DeliveryStore(str(path)), FakeTelegram(), ['-1001'], {'-1001': 'Alias del entorno'})
    assert restarted.list()[0]['alias'] is None
    with pytest.raises(ValueError):
        directory.set_alias('-9999', 'Intruso')
    with pytest.raises(ValueError):
        directory.set_alias('-1001', 'x'*81)
    assert [chat['id'] for chat in directory.list()] == ['-1001']


def test_telegram_client_caches_successful_get_chat(monkeypatch):
    calls = []
    def run(coroutine):
        coroutine.close()
        calls.append(True)
        return 'Notificaciones Emby'
    monkeypatch.setattr('emby_telegram_bot.telegram_client.asyncio.run', run)
    client = TelegramClient('fake', ['-1001'])

    assert client.validate_chat('-1001') == 'Notificaciones Emby'
    assert client.validate_chat('-1001') == 'Notificaciones Emby'
    assert calls == [True]


def test_telegram_client_throttles_repeated_failures(monkeypatch):
    calls = []
    def run(coroutine):
        coroutine.close()
        calls.append(True)
        raise TimeoutError('offline')
    monkeypatch.setattr('emby_telegram_bot.telegram_client.asyncio.run', run)
    client = TelegramClient('fake', ['-1001'])

    with pytest.raises(TimeoutError):
        client.validate_chat('-1001')
    with pytest.raises(RuntimeError, match='recently failed'):
        client.validate_chat('-1001')
    assert calls == [True]


def test_panel_alias_api_persists_without_changing_plan_destinations(tmp_path):
    path = tmp_path/'demo.sqlite3'
    app = create_demo_app(path, secret_key='test-session-secret')
    client = app.test_client()
    headers = login(client)
    original = client.get('/api/chats').json['chats']
    chat_id = original[0]['id']

    changed = client.post(f'/api/chats/{chat_id}/alias', json={'alias': 'Novedades'}, headers=headers)
    assert changed.status_code == 200
    assert changed.json['chat']['id'] == chat_id
    assert changed.json['chat']['label'] == 'Novedades'
    plan = client.post('/api/prepare', json={
        'item_ids': ['m4'], 'chat_ids': [chat_id], 'mode': 'recover',
        'decisions': {f'm4|{chat_id}': 'send'},
    }, headers=headers)
    assert plan.status_code == 200
    assert plan.json['rows'][0]['chat_id'] == chat_id

    history = client.get(f'/api/history?chat_id={chat_id}&page=1').json
    assert history['items'] and all(row['chat_id'] == chat_id for row in history['items'])
    run = client.post('/api/reconciliation/runs', json={'chat_ids': [chat_id]}, headers=headers).json
    detail = client.get(f"/api/reconciliation/runs/{run['run_id']}?chat_id={chat_id}&page=1").json
    assert detail['pages'] > 1
    assert all(row['chat_id'] == chat_id and row['chat_label'] == 'Novedades' for row in detail['items'])

    restarted = create_demo_app(path, secret_key='another-test-session-secret')
    second = restarted.test_client()
    second_headers = login(second)
    persisted = second.get('/api/chats', headers=second_headers).json['chats']
    assert next(chat for chat in persisted if chat['id'] == chat_id)['alias'] == 'Novedades'


def test_alias_api_requires_session_csrf_and_known_chat(tmp_path):
    app = create_demo_app(tmp_path/'demo.sqlite3', secret_key='test-session-secret')
    anonymous = app.test_client()
    csrf = anonymous.get('/api/session').json['csrf_token']
    assert anonymous.post('/api/chats/demo-cine/alias', json={'alias': 'Novedades'}, headers={'X-CSRF-Token': csrf}).status_code == 401

    client = app.test_client()
    headers = login(client)
    assert client.post('/api/chats/demo-cine/alias', json={'alias': 'x'*81}, headers=headers).status_code == 400
    assert client.post('/api/chats/no-existe/alias', json={'alias': 'Intruso'}, headers=headers).status_code == 400
    assert client.post('/api/chats/demo-cine/alias', json={'alias': 'Sin CSRF'}).status_code == 403
