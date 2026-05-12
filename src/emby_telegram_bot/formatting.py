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


def build_search_results_message(query: str, items: list[dict[str, Any]]) -> str:
    clean_query = query.strip()
    if not items:
        return f"🔎 Busqueda: {clean_query}\n\nNo he encontrado peliculas ni series con ese texto."

    lines = [f"🔎 Busqueda: {clean_query}", ""]
    for index, item in enumerate(items, start=1):
        item_type = item.get("Type")
        icon = "🎬" if item_type == "Movie" else "📺" if item_type == "Series" else "🆕"
        label = "Pelicula" if item_type == "Movie" else "Serie" if item_type == "Series" else "Contenido"
        name = item.get("Name") or "Sin titulo"
        year = item.get("ProductionYear")
        suffix = f" ({year})" if year else ""
        lines.append(f"{index}. {icon} {label}: {name}{suffix}")
    return "\n".join(lines)


def _audio_label(stream: dict[str, Any]) -> str:
    language = _first_str(stream.get("Language"), stream.get("DisplayLanguage"), stream.get("Title"))
    codec = _first_str(stream.get("Codec")).upper()
    channels = stream.get("Channels")
    channel_label = f"{channels}ch" if channels else ""
    return _join_known([language, codec, channel_label])


def _format_audio_streams(media_source: dict[str, Any], max_items: int = 3) -> str:
    streams = media_source.get("MediaStreams")
    if not isinstance(streams, list):
        return ""
    audio = [
        _audio_label(stream)
        for stream in streams
        if isinstance(stream, dict) and (stream.get("Type") or "").lower() == "audio"
    ]
    audio = [item for item in audio if item]
    if not audio:
        return ""
    shown = audio[:max_items]
    if len(audio) > max_items:
        shown.append(f"+{len(audio) - max_items}")
    return ", ".join(shown)


def _format_movie_versions(item: dict[str, Any], max_versions: int = 4) -> list[str]:
    media_sources = item.get("MediaSources")
    if not isinstance(media_sources, list) or not media_sources:
        return []

    valid_sources = [s for s in media_sources if isinstance(s, dict)]
    if not valid_sources:
        return []

    lines = ["Datos de la version:" if len(valid_sources) == 1 else "Versiones disponibles:"]
    for index, source in enumerate(valid_sources[:max_versions], start=1):
        path = _first_str(source.get("Path"), source.get("Name"), item.get("Path"), item.get("Name"))
        resolution = resolution_from_filename(path)
        if not _is_known(resolution):
            resolution = _resolution_from_media_streams(item, source)
        container = _first_str(source.get("Container"), item.get("Container")).upper() or "?"
        size = _size_to_gib(source.get("Size") or item.get("Size"))
        audio = _format_audio_streams(source)
        details = _join_known([resolution, container, size])
        line = f"{index}. {details}" if details else f"{index}. Version"
        if audio:
            line += f" | Audio: {audio}"
        lines.append(line)
    if len(valid_sources) > max_versions:
        lines.append(f"... +{len(valid_sources) - max_versions} versiones mas")
    return lines


def _format_series_availability(seasons: list[dict[str, Any]], max_seasons: int = 8) -> list[str]:
    if not seasons:
        return []
    lines = ["Temporadas disponibles:"]
    for season in seasons[:max_seasons]:
        season_number = season.get("IndexNumber")
        try:
            season_number = int(season_number)
        except Exception:
            season_number = 0
        episodes = season.get("Episodes")
        episode_numbers = []
        if isinstance(episodes, list):
            for episode in episodes:
                if not isinstance(episode, dict):
                    continue
                try:
                    episode_number = int(episode.get("IndexNumber") or 0)
                except Exception:
                    episode_number = 0
                if episode_number:
                    episode_numbers.append(episode_number)
        episode_numbers = sorted(set(episode_numbers))
        if episode_numbers:
            episode_tags = [f"E{episode:02}" for episode in episode_numbers]
            episodes_text = _format_episode_list(episode_tags, max_items=10)
            lines.append(f"T{season_number:02}: {episodes_text}")
            continue
        child_count = season.get("ChildCount")
        suffix = f"{child_count} episodios" if child_count else "episodios disponibles"
        lines.append(f"T{season_number:02}: {suffix}")
    if len(seasons) > max_seasons:
        lines.append(f"... +{len(seasons) - max_seasons} temporadas mas")
    return lines


def _trim_caption(caption: str, max_length: int = 1000) -> str:
    if len(caption) <= max_length:
        return caption
    return caption[: max_length - 3].rstrip() + "..."


def build_search_item_caption(
    item: dict[str, Any],
    series_seasons: list[dict[str, Any]] | None = None,
) -> str:
    item_type = item.get("Type")
    icon = "🎬" if item_type == "Movie" else "📺" if item_type == "Series" else "🆕"
    label = "Pelicula" if item_type == "Movie" else "Serie" if item_type == "Series" else "Contenido"
    name = item.get("Name") or "Sin titulo"
    year = item.get("ProductionYear")
    caption = f"{icon} {label}: {name}"
    if year:
        caption += f" ({year})"
    overview = _first_str(item.get("Overview"))
    if overview:
        caption += f"\n\n{overview[:450]}"
        if len(overview) > 450:
            caption += "..."
    extra_lines = []
    if item_type == "Movie":
        extra_lines = _format_movie_versions(item)
    elif item_type == "Series" and series_seasons:
        extra_lines = _format_series_availability(series_seasons)
    if extra_lines:
        caption += f"\n\n{SECTION_DIVIDER}\n" + "\n".join(extra_lines)
    return _trim_caption(caption)
