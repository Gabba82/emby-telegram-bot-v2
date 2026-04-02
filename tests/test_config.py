import pytest

from emby_telegram_bot.config import Settings


def _set_required_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TELEGRAM_TOKEN", "test-token")
    monkeypatch.setenv("CHAT_IDS", "-1001,-1002")
    monkeypatch.setenv("EMBY_API_KEY", "test-key")


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    settings = Settings.from_env()
    assert settings.chat_ids == ["-1001", "-1002"]
    assert settings.library_chat_ids == []
    assert settings.playback_chat_ids == []
    assert settings.playback_debounce_seconds == 10
    assert settings.enable_library_notifications is True
    assert settings.enable_playback_notifications is True


def test_settings_optional_targets_and_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("LIBRARY_CHAT_IDS", "-2001")
    monkeypatch.setenv("PLAYBACK_CHAT_IDS", "-3001,-3002")
    monkeypatch.setenv("PLAYBACK_DEBOUNCE_SECONDS", "5")
    monkeypatch.setenv("ENABLE_LIBRARY_NOTIFICATIONS", "false")
    monkeypatch.setenv("ENABLE_PLAYBACK_NOTIFICATIONS", "0")

    settings = Settings.from_env()
    assert settings.library_chat_ids == ["-2001"]
    assert settings.playback_chat_ids == ["-3001", "-3002"]
    assert settings.playback_debounce_seconds == 5
    assert settings.enable_library_notifications is False
    assert settings.enable_playback_notifications is False


def test_settings_rejects_negative_debounce(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_env(monkeypatch)
    monkeypatch.setenv("PLAYBACK_DEBOUNCE_SECONDS", "-1")
    with pytest.raises(ValueError):
        Settings.from_env()

