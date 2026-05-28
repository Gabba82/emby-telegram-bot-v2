from emby_telegram_bot.config import Settings
from emby_telegram_bot.diagnostics import build_config_checks, format_diagnostic_report


def _settings() -> Settings:
    return Settings(
        telegram_token="token",
        chat_ids=["-1001", "-1001"],
        admin_chat_ids=[],
        library_chat_ids=[],
        playback_chat_ids=["-3001"],
        emby_api_url="http://emby:8096/emby",
        emby_api_key="key",
        request_timeout_seconds=15,
        episode_buffer_seconds=60,
        library_debounce_seconds=120,
        playback_debounce_seconds=10,
        enable_library_notifications=True,
        enable_playback_notifications=True,
        playback_notify_pause=False,
        playback_with_image=False,
        playback_style="compact",
        app_timezone="Europe/Madrid",
        telegram_webhook_secret="",
        chat_labels={},
    )


def test_config_checks_warn_about_secret_and_duplicate_targets() -> None:
    settings = _settings()

    checks = build_config_checks(
        settings,
        library_targets=settings.chat_ids,
        playback_targets=settings.playback_chat_ids,
        admin_targets=settings.chat_ids,
    )

    assert any(check.status == "WARNING" and check.label == "Webhook Telegram" for check in checks)
    assert any(check.status == "WARNING" and check.label == "CHAT_IDS" for check in checks)
    assert any(check.status == "OK" and check.label == "Timezone" for check in checks)


def test_format_diagnostic_report_includes_status_prefixes() -> None:
    report = format_diagnostic_report(
        build_config_checks(
            _settings(),
            library_targets=["-1001"],
            playback_targets=[],
            admin_targets=[],
        )
    )

    assert "[OK] Timezone" in report
    assert "[WARNING] Webhook Telegram" in report
    assert "[ERROR] Destinos playback" in report
