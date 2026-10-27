"""Explicit opt-in configuration for the operational web panel."""
import os
from collections.abc import Mapping
from .config import Settings
from .webhook import create_app


def _flag(env: Mapping[str, str], name: str) -> bool:
    raw = env.get(name, 'false').strip().lower()
    if raw not in {'true', 'false', '1', '0', 'yes', 'no', 'on', 'off'}:
        raise ValueError(f'{name} must be a boolean')
    return raw in {'true', '1', 'yes', 'on'}


def panel_options_from_env(env: Mapping[str, str] | None = None) -> dict | None:
    env = os.environ if env is None else env
    if not _flag(env, 'PANEL_ENABLED'):
        return None
    password = env.get('PANEL_ADMIN_PASSWORD', '')
    secret = env.get('PANEL_SECRET_KEY', '')
    placeholders = ('replace', 'change', 'changeme', 'example', 'emby-demo', '<', '>')
    for name, value, minimum in [('PANEL_ADMIN_PASSWORD', password, 16), ('PANEL_SECRET_KEY', secret, 32)]:
        if len(value) < minimum or any(word in value.lower() for word in placeholders):
            raise ValueError(f'{name} requires a private value of at least {minimum} characters; demo/placeholder values are forbidden')
    if secret == password:
        raise ValueError('PANEL_SECRET_KEY must be independent from PANEL_ADMIN_PASSWORD')
    return dict(password=password, secret_key=secret, allow_sends=_flag(env, 'PANEL_ALLOW_SENDS'))


def create_runtime_app():
    # Validate the panel before constructing clients that register Telegram commands.
    panel = panel_options_from_env()
    settings = Settings.from_env()
    return create_app(settings, panel=panel)
