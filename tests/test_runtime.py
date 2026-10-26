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
