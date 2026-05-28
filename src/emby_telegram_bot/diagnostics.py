from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from zoneinfo import ZoneInfo

from .config import Settings


@dataclass(frozen=True)
class DiagnosticCheck:
    status: str
    label: str
    detail: str


class EmbyValidator(Protocol):
    def validate_credentials(self) -> str: ...


class TelegramValidator(Protocol):
    def validate_credentials(self) -> str: ...


def _status_prefix(status: str) -> str:
    return {
        "OK": "[OK]",
        "WARNING": "[WARNING]",
        "ERROR": "[ERROR]",
    }.get(status, "[INFO]")


def format_diagnostic_report(checks: list[DiagnosticCheck]) -> str:
    lines = ["Diagnostico del bot:"]
    for check in checks:
        lines.append(f"- {_status_prefix(check.status)} {check.label}: {check.detail}")
    return "\n".join(lines)


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    duplicated: set[str] = set()
    for value in values:
        if value in seen:
            duplicated.add(value)
        seen.add(value)
    return sorted(duplicated)


def build_config_checks(
    settings: Settings,
    library_targets: list[str],
    playback_targets: list[str],
    admin_targets: list[str],
) -> list[DiagnosticCheck]:
    checks: list[DiagnosticCheck] = []

    checks.append(DiagnosticCheck("OK", "Timezone", settings.app_timezone))
    try:
        ZoneInfo(settings.app_timezone)
    except Exception:
        checks[-1] = DiagnosticCheck("ERROR", "Timezone", "APP_TIMEZONE no es una timezone IANA valida")

    if settings.telegram_webhook_secret:
        checks.append(DiagnosticCheck("OK", "Webhook Telegram", "secret configurado"))
    else:
        checks.append(
            DiagnosticCheck(
                "WARNING",
                "Webhook Telegram",
                "sin TELEGRAM_WEBHOOK_SECRET; aceptable en pruebas, no recomendado en produccion",
            )
        )

    target_groups = {
        "CHAT_IDS": settings.chat_ids,
        "ADMIN_CHAT_IDS": settings.admin_chat_ids,
        "LIBRARY_CHAT_IDS": settings.library_chat_ids,
        "PLAYBACK_CHAT_IDS": settings.playback_chat_ids,
    }
    for name, values in target_groups.items():
        if values:
            duplicated = _duplicates(values)
            if duplicated:
                checks.append(DiagnosticCheck("WARNING", name, f"IDs duplicados: {', '.join(duplicated)}"))
            else:
                checks.append(DiagnosticCheck("OK", name, f"{len(values)} destino(s) configurado(s)"))
        elif name == "CHAT_IDS":
            checks.append(DiagnosticCheck("ERROR", name, "sin destinos"))
        else:
            checks.append(DiagnosticCheck("OK", name, "sin valores; usa fallback si aplica"))

    if not library_targets:
        checks.append(DiagnosticCheck("ERROR", "Destinos biblioteca", "sin destinos efectivos"))
    else:
        checks.append(DiagnosticCheck("OK", "Destinos biblioteca", ", ".join(library_targets)))

    if not playback_targets:
        checks.append(DiagnosticCheck("ERROR", "Destinos playback", "sin destinos efectivos"))
    else:
        checks.append(DiagnosticCheck("OK", "Destinos playback", ", ".join(playback_targets)))

    if not admin_targets:
        checks.append(DiagnosticCheck("WARNING", "Destinos admin", "sin admin dedicado; se usara CHAT_IDS"))
    else:
        checks.append(DiagnosticCheck("OK", "Destinos admin", ", ".join(admin_targets)))

    return checks


def build_runtime_checks(emby: EmbyValidator, telegram: TelegramValidator) -> list[DiagnosticCheck]:
    checks: list[DiagnosticCheck] = []
    try:
        checks.append(DiagnosticCheck("OK", "Emby API", emby.validate_credentials()))
    except Exception as exc:
        checks.append(DiagnosticCheck("ERROR", "Emby API", type(exc).__name__))

    try:
        checks.append(DiagnosticCheck("OK", "Telegram API", telegram.validate_credentials()))
    except Exception as exc:
        checks.append(DiagnosticCheck("ERROR", "Telegram API", type(exc).__name__))

    return checks


def build_chat_reachability_checks(telegram: object, chat_ids: list[str]) -> list[DiagnosticCheck]:
    validate_chat = getattr(telegram, "validate_chat", None)
    if not callable(validate_chat):
        return [DiagnosticCheck("WARNING", "Chats Telegram", "validacion no disponible en este cliente")]

    checks: list[DiagnosticCheck] = []
    for chat_id in sorted(set(chat_ids)):
        try:
            checks.append(DiagnosticCheck("OK", f"Chat {chat_id}", str(validate_chat(chat_id))))
        except Exception as exc:
            checks.append(DiagnosticCheck("ERROR", f"Chat {chat_id}", type(exc).__name__))
    return checks
