import os
from dataclasses import dataclass
from zoneinfo import ZoneInfo


def _parse_chat_ids(raw: str) -> list[str]:
    values = [cid.strip() for cid in raw.split(",")]
    return [cid for cid in values if cid]


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    chat_ids: list[str]
    emby_api_url: str
    emby_api_key: str
    request_timeout_seconds: int
    episode_buffer_seconds: int
    playback_with_image: bool
    playback_style: str
    app_timezone: str

    @classmethod
    def from_env(cls) -> "Settings":
        telegram_token = os.getenv("TELEGRAM_TOKEN", "").strip()
        emby_api_key = os.getenv("EMBY_API_KEY", "").strip()
        chat_ids = _parse_chat_ids(os.getenv("CHAT_IDS", ""))
        emby_api_url = os.getenv("EMBY_API_URL", "http://emby:8096/emby").rstrip("/")
        playback_with_image_raw = os.getenv("PLAYBACK_WITH_IMAGE", "false").strip().lower()
        playback_style = os.getenv("PLAYBACK_STYLE", "compact").strip().lower()
        app_timezone = os.getenv("APP_TIMEZONE", "Europe/Madrid").strip()

        timeout_raw = os.getenv("REQUEST_TIMEOUT_SECONDS", "15").strip()
        buffer_raw = os.getenv("EPISODE_BUFFER_SECONDS", "60").strip()

        if not telegram_token:
            raise ValueError("Missing TELEGRAM_TOKEN environment variable")
        if not emby_api_key:
            raise ValueError("Missing EMBY_API_KEY environment variable")
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
        if playback_style not in {"compact", "detailed"}:
            raise ValueError("PLAYBACK_STYLE must be one of: compact, detailed")
        try:
            ZoneInfo(app_timezone)
        except Exception as exc:
            raise ValueError("APP_TIMEZONE must be a valid IANA timezone, e.g. Europe/Madrid") from exc

        playback_with_image = playback_with_image_raw in {"1", "true", "yes", "on"}

        return cls(
            telegram_token=telegram_token,
            chat_ids=chat_ids,
            emby_api_url=emby_api_url,
            emby_api_key=emby_api_key,
            request_timeout_seconds=request_timeout_seconds,
            episode_buffer_seconds=episode_buffer_seconds,
            playback_with_image=playback_with_image,
            playback_style=playback_style,
            app_timezone=app_timezone,
        )
