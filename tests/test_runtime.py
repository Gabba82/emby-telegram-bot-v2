"""Only the new release entrypoint; no Telegram clients or network."""
import pytest
from emby_telegram_bot import runtime


def credentials(**changes):
    return dict(PANEL_ENABLED='true', PANEL_ADMIN_PASSWORD='synthetic-panel-password-1234',
                PANEL_SECRET_KEY='synthetic-independent-session-key-123456789', **changes)


def test_panel_disabled_by_default():
    assert runtime.panel_options_from_env({}) is None


@pytest.mark.parametrize('env', [
    {'PANEL_ENABLED':'maybe'}, {'PANEL_ENABLED':'true'},
    dict(credentials(),PANEL_ADMIN_PASSWORD='emby-demo-003'),
    dict(credentials(),PANEL_SECRET_KEY='replace_me_with_a_very_long_secret_value'),
    dict(credentials(),PANEL_ALLOW_SENDS='maybe'),
    dict(credentials(),PANEL_SECRET_KEY='synthetic-panel-password-1234'),
])
def test_invalid_options_fail_closed(env):
    with pytest.raises(ValueError):runtime.panel_options_from_env(env)


def test_panel_sends_require_explicit_opt_in():
    assert runtime.panel_options_from_env(credentials())['allow_sends'] is False
    assert runtime.panel_options_from_env(credentials(PANEL_ALLOW_SENDS='true'))['allow_sends'] is True


def test_factory_passes_validated_options(monkeypatch):
    env=credentials()
    for key,value in env.items():monkeypatch.setenv(key,value)
    sentinel=object()
    monkeypatch.setattr(runtime.Settings,'from_env',lambda:sentinel)
    calls=[]
    monkeypatch.setattr(runtime,'create_app',lambda settings,**kw:calls.append((settings,kw)) or 'app')
    assert runtime.create_runtime_app()=='app'
    assert calls[0][0] is sentinel
    assert calls[0][1]['panel']['password']==env['PANEL_ADMIN_PASSWORD']


def test_bad_panel_rejected_before_bot_initialization(monkeypatch):
    monkeypatch.setenv('PANEL_ENABLED','true')
    monkeypatch.delenv('PANEL_ADMIN_PASSWORD',raising=False)
    monkeypatch.setattr(runtime.Settings,'from_env',lambda:pytest.fail('must validate panel first'))
    with pytest.raises(ValueError):runtime.create_runtime_app()


@pytest.mark.parametrize('panel_enabled', [False, True])
def test_operational_boot_webhooks_and_restart_with_simulated_clients(monkeypatch, tmp_path, panel_enabled):
    from dataclasses import replace
    from test_webhook import _FakeEmbyClient, _FakeTelegramClient, _settings
    from emby_telegram_bot.telegram_client import SendResult

    class RecordingTelegram(_FakeTelegramClient):
        def send(self, caption, image_bytes, chat_ids=None):
            super().send(caption, image_bytes, chat_ids)
            return [SendResult(chat, 'sent', 7001, None) for chat in chat_ids]

    settings = replace(_settings(secret='synthetic-webhook-secret'),
                       history_db_path=str(tmp_path / 'operational.sqlite3'))
    monkeypatch.setattr(runtime.Settings, 'from_env', lambda: settings)
    monkeypatch.setattr('emby_telegram_bot.webhook.EmbyClient', _FakeEmbyClient)
    monkeypatch.setattr('emby_telegram_bot.webhook.TelegramClient', RecordingTelegram)
    for key in ('PANEL_ENABLED', 'PANEL_ADMIN_PASSWORD', 'PANEL_SECRET_KEY', 'PANEL_ALLOW_SENDS'):
        monkeypatch.delenv(key, raising=False)
    if panel_enabled:
        for key, value in credentials().items():
            monkeypatch.setenv(key, value)
    app = runtime.create_runtime_app()
    client = app.test_client()
    assert client.get('/health').status_code == 200
    assert client.get('/manager/').status_code == (200 if panel_enabled else 404)
    if panel_enabled:
        session = client.get('/api/session').json
        assert session['sends_enabled'] is False
        login = client.post('/api/login', json={'password': credentials()['PANEL_ADMIN_PASSWORD']},
                            headers={'X-CSRF-Token': session['csrf_token']}).json
        blocked = client.post('/api/batches/not-a-real-batch/confirm', json={'confirm': True},
                              headers={'X-CSRF-Token': login['csrf_token']})
        assert blocked.status_code == 403 and blocked.json['error'] == 'sends_disabled'
    payload = {'Event': 'library.new', 'Item': {'Id': 'movie-1', 'Type': 'Movie', 'Name': 'Synthetic film'}}
    assert client.post('/embyhook', json=payload).status_code == 200
    assert app.extensions['delivery_store'].item_status('movie-1', '-1001') == 'sent'
    before = len(RecordingTelegram.latest.sent_texts)
    message = {'message': {'chat': {'id': 42, 'type': 'private'}, 'text': '/help'}}
    assert client.post('/telegramhook', json=message).status_code == 403
    assert len(RecordingTelegram.latest.sent_texts) == before
    assert client.post('/telegramhook', json=message,
                       headers={'X-Telegram-Bot-Api-Secret-Token': settings.telegram_webhook_secret}).status_code == 200
    restarted = runtime.create_runtime_app()
    assert restarted.extensions['delivery_store'].item_status('movie-1', '-1001') == 'sent'
