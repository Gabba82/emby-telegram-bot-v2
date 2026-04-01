import os
from dataclasses import dataclass


def _parse_chat_ids(raw: str) -> list[str]:
    values = [cid.strip() for cid in raw.split(",")]
    return [cid for cid in values if cid]


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    chat_ids: list[str]
    emby_api_url: str
    emby_api_key: str
    webhook_secret: str
    request_timeout_seconds: int
    episode_buffer_seconds: int

    @classmethod
    def from_env(cls) -> "Settings":
        telegram_token = os.getenv("TELEGRAM_TOKEN", "").strip()
        emby_api_key = os.getenv("EMBY_API_KEY", "").strip()
        webhook_secret = os.getenv("WEBHOOK_SECRET", "").strip()
        chat_ids = _parse_chat_ids(os.getenv("CHAT_IDS", ""))
        emby_api_url = os.getenv("EMBY_API_URL", "http://emby:8096/emby").rstrip("/")

        timeout_raw = os.getenv("REQUEST_TIMEOUT_SECONDS", "15").strip()
        buffer_raw = os.getenv("EPISODE_BUFFER_SECONDS", "60").strip()

        if not telegram_token:
            raise ValueError("Missing TELEGRAM_TOKEN environment variable")
        if not emby_api_key:
            raise ValueError("Missing EMBY_API_KEY environment variable")
        if not webhook_secret:
            raise ValueError("Missing WEBHOOK_SECRET environment variable")
        if not chat_ids:
            raise ValueError("Missing CHAT_IDS environment variable")

        try:
            request_timeout_seconds = int(timeout_raw)
            episode_buffer_seconds = int(buffer_raw)
        except ValueError as exc:
            raise ValueError("REQUEST_TIMEOUT_SECONDS and EPISODE_BUFFER_SECONDS must be integers") from exc

        if request_timeout_seconds <= 0:
            raise ValueError("REQUEST_TIMEOUT_SECONDS must be greater than 0")
        if episode_buffer_seconds <= 0:
            raise ValueError("EPISODE_BUFFER_SECONDS must be greater than 0")

        return cls(
            telegram_token=telegram_token,
            chat_ids=chat_ids,
            emby_api_url=emby_api_url,
            emby_api_key=emby_api_key,
            webhook_secret=webhook_secret,
            request_timeout_seconds=request_timeout_seconds,
            episode_buffer_seconds=episode_buffer_seconds,
        )

