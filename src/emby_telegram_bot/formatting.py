from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

SECTION_DIVIDER = "━━━━━━━━━━━━"


def resolution_from_filename(path: str | None) -> str:
    if not path:
        return "?"
    match = re.search(r"(2160p|1080p|720p|480p)", path, re.IGNORECASE)
    return match.group(1) if match else "?"


def release_type_from_filename(path: str | None) -> str:
    if not path:
        return "?"
    patterns = ("BDRemux", "Remux", "WEB-DL", "WEBRip", "BluRay", "DVDRip", "HDRip", "CAM", "HDTV")
    for pattern in patterns:
        if re.search(pattern, path, re.IGNORECASE):
            return pattern
    return "?"


def _size_to_gib(size: int | None) -> str:
    if not size:
        return "?"
    return f"{round(size / (1024 ** 3), 2)} GiB"


def _is_known(value: str) -> bool:
    return bool(value and value != "?")


def _extract_primary_media_source(item: dict[str, Any]) -> dict[str, Any]:
    media_sources = item.get("MediaSources")
    if isinstance(media_sources, list) and media_sources and isinstance(media_sources[0], dict):
        return media_sources[0]
    return {}


def _resolution_from_media_streams(item: dict[str, Any], media_source: dict[str, Any]) -> str:
    stream_candidates = []
    item_streams = item.get("MediaStreams")
    media_streams = media_source.get("MediaStreams")
    if isinstance(item_streams, list):
        stream_candidates.extend([s for s in item_streams if isinstance(s, dict)])
    if isinstance(media_streams, list):
        stream_candidates.extend([s for s in media_streams if isinstance(s, dict)])

    for stream in stream_candidates:
        if (stream.get("Type") or "").lower() != "video":
            continue
        try:
            height = int(stream.get("Height") or 0)
        except Exception:
            height = 0
        if height >= 2000:
            return "2160p"
        if height >= 1000:
            return "1080p"
        if height >= 700:
            return "720p"
        if height >= 450:
            return "480p"
    return "?"


def _join_known(parts: list[str]) -> str:
    return " | ".join([part for part in parts if _is_known(part)])


def _build_file_specs(item: dict[str, Any], season_mode: bool = False) -> str:
    media_source = _extract_primary_media_source(item)
    container = (
        (item.get("Container") or media_source.get("Container") or "").strip().upper()
        or "?"
    )
    path = _first_str(item.get("Path"), media_source.get("Path"), media_source.get("Name"), item.get("Name"))
    resolution = resolution_from_filename(path)
    if not _is_known(resolution):
        resolution = _resolution_from_media_streams(item, media_source)
    size_str = _size_to_gib(item.get("Size") or media_source.get("Size"))
    media_type = item.get("Type")

    if season_mode:
        details = _join_known([resolution, container])
        return f"⚙️ Archivo: Temporada | {details}" if details else "⚙️ Archivo: Temporada"
    if media_type == "Movie":
        release_type = release_type_from_filename(path)
        details = _join_known([release_type, resolution, container, size_str])
        return f"⚙️ Archivo: Pelicula | {details}" if details else "⚙️ Archivo: Pelicula"
    if media_type == "Episode":
        details = _join_known([resolution, container, size_str])
        return f"⚙️ Archivo: Episodio | {details}" if details else "⚙️ Archivo: Episodio"
    return ""


def _format_episode_list(episode_list: list[str] | None, max_items: int = 12) -> str:
    if not episode_list:
        return ""
    if len(episode_list) <= max_items:
        return ", ".join(episode_list)
    shown = ", ".join(episode_list[:max_items])
    hidden = len(episode_list) - max_items
    return f"{shown} ... (+{hidden})"


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _event_label(event_code: str) -> str:
    mapping = {
        "playback.start": "▶️ Reproduccion iniciada",
        "playback.pause": "⏸️ Reproduccion pausada",
        "playback.unpause": "▶️ Reproduccion reanudada",
        "playback.stop": "⏹️ Reproduccion finalizada",
        "session.start": "🟢 Sesion iniciada",
        "session.end": "🔴 Sesion finalizada",
    }
    return mapping.get(event_code, "")


def _event_time_hhmm(payload: dict[str, Any], timezone_name: str = "Europe/Madrid") -> str:
    raw = _first_str(payload.get("Date"), payload.get("Timestamp"), payload.get("EventDate"))
    if not raw:
        return ""
    try:
        tz = ZoneInfo(timezone_name)
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt.astimezone(tz).strftime("%H:%M")
    except Exception:
        return ""


def _extract_client(payload: dict[str, Any]) -> str:
    session = payload.get("Session") if isinstance(payload.get("Session"), dict) else {}
    playback_info = payload.get("PlaybackInfo") if isinstance(payload.get("PlaybackInfo"), dict) else {}
    return _first_str(
        payload.get("Client"),
        payload.get("ClientName"),
        payload.get("DeviceName"),
        session.get("DeviceName"),
        session.get("Client"),
        session.get("ClientName"),
        playback_info.get("Client"),
        playback_info.get("DeviceName"),
    )


def infer_activity_event_code(payload: dict[str, Any]) -> str:
    raw_event = str(payload.get("Event") or "").strip().lower()
    if raw_event:
        return raw_event

    text = " ".join(
        [
            str(payload.get("Title") or ""),
            str(payload.get("Description") or ""),
            str(payload.get("NotificationType") or ""),
        ]
    ).lower()

    if "unpause" in text or "resume" in text or "resum" in text or "rean" in text:
        return "playback.unpause"
    if "pause" in text or "paus" in text:
        return "playback.pause"
    if "stop" in text or "end" in text or "finaliz" in text:
        return "playback.stop"
    if "playback" in text or "play" in text or "reproduc" in text:
        return "playback.start"
    if "session" in text and ("start" in text or "init" in text):
        return "session.start"
    if "session" in text and ("end" in text or "stop" in text):
        return "session.end"
    return ""


def is_activity_payload(payload: dict[str, Any]) -> bool:
    event_code = infer_activity_event_code(payload)
    if event_code.startswith("playback.") or event_code.startswith("session."):
        return True

    item = payload.get("Item")
    has_user = any(
        [
            bool(payload.get("UserName")),
            bool(payload.get("UserId")),
            isinstance(payload.get("User"), dict),
        ]
    )
    has_client = any(
        [
            bool(payload.get("Client")),
            bool(payload.get("ClientName")),
            bool(payload.get("DeviceName")),
            isinstance(payload.get("Session"), dict),
        ]
    )
    # Heuristic: playback-like payloads often include user/client + item
    return bool(item) and (has_user or has_client)


def build_activity_caption(
    payload: dict[str, Any],
    item_override: dict[str, Any] | None = None,
    style: str = "compact",
    timezone_name: str = "Europe/Madrid",
) -> str:
    event_code = infer_activity_event_code(payload)
    if not event_code or event_code == "system.notificationtest":
        return ""

    label = _event_label(event_code) or _first_str(payload.get("Title"), f"Evento Emby: {event_code}")

    user_data = payload.get("User") if isinstance(payload.get("User"), dict) else {}
    user = _first_str(payload.get("UserName"), user_data.get("Name"))

    item = item_override if isinstance(item_override, dict) else {}
    if not item:
        item = payload.get("Item") if isinstance(payload.get("Item"), dict) else {}

    item_name = _first_str(item.get("Name"), payload.get("ItemName"), payload.get("Name"))
    item_type = _first_str(item.get("Type"), payload.get("ItemType"))
    if item_type == "Episode":
        series_name = _first_str(item.get("SeriesName"), payload.get("SeriesName"), "Serie")
        season = int(item.get("ParentIndexNumber") or payload.get("ParentIndexNumber") or 0)
        episode = int(item.get("IndexNumber") or payload.get("IndexNumber") or 0)
        episode_name = item_name or "Episodio"
        item_name = f"{series_name} S{season:02}E{episode:02} - {episode_name}"

    client = _extract_client(payload)

    lines = [f"📡 {label}"]
    if user:
        lines.append(f"👤 Usuario: {user}")
    if item_name:
        lines.append(f"🎬 Contenido: {item_name}")
    if client:
        lines.append(f"📺 Cliente: {client}")
    event_time = _event_time_hhmm(payload, timezone_name=timezone_name)
    if event_time:
        lines.append(f"🕒 Hora: {event_time}")

    if style == "detailed":
        quality = resolution_from_filename(_first_str(item.get("Path")))
        if quality and quality != "?":
            lines.append(f"🧾 Calidad: {quality}")
        year = item.get("ProductionYear")
        if year:
            lines.append(f"📅 Año: {year}")

    if len(lines) == 1:
        description = _first_str(payload.get("Description"))
        if description:
            lines.append(f"ℹ️ {description}")

    return "\n".join(lines)


def build_caption(item: dict[str, Any], season_mode: bool = False, episode_list: list[str] | None = None) -> str:
    item_type = item.get("Type")
    name = item.get("Name") or "Nuevo contenido"
    year = item.get("ProductionYear")
    rating = item.get("CommunityRating")

    if season_mode:
        series_name = item.get("SeriesName") or "Serie"
        season_number = item.get("ParentIndexNumber") or item.get("IndexNumber") or 0
        title = f"📦 Temporada completa: {series_name} (T{season_number:02})"
        caption = title
        formatted_episodes = _format_episode_list(episode_list)
        if formatted_episodes:
            caption += f"\n🧩 Episodios: {formatted_episodes}"
    elif item_type == "Movie":
        title = f"🎬 Película: {name} ({year})" if year else f"🎬 Película: {name}"
        caption = title
    elif item_type == "Episode":
        series_name = item.get("SeriesName") or "Serie"
        season = item.get("ParentIndexNumber") or 0
        episode = item.get("IndexNumber") or 0
        caption = f"📺 Serie: {series_name} S{season:02}E{episode:02}\n🎞️ Título: {name}"
    else:
        caption = f"🆕 Nuevo contenido: {name}"

    if rating:
        rating_str = f"{float(rating):.1f}" if isinstance(rating, (int, float)) else str(rating)
        caption += f"\n⭐ Valoración: {rating_str}/10"

    specs = _build_file_specs(item, season_mode=season_mode)
    if specs:
        caption += f"\n{SECTION_DIVIDER}\n{specs}"
    return caption
