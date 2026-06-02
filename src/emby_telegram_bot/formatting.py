from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

SECTION_DIVIDER = "━━━━━━━━━━━━"
EXPANDABLE_SECTION_START = "[[EMBY_BOT_EXPANDABLE_START]]"
EXPANDABLE_SECTION_END = "[[EMBY_BOT_EXPANDABLE_END]]"

LANGUAGE_LABELS = {
    "ca": "Catalan",
    "cat": "Catalan",
    "en": "Ingles",
    "eng": "Ingles",
    "es": "Español",
    "spa": "Español",
    "esl": "Español Latino",
    "fr": "Frances",
    "fre": "Frances",
    "fra": "Frances",
    "de": "Aleman",
    "ger": "Aleman",
    "deu": "Aleman",
    "it": "Italiano",
    "ita": "Italiano",
    "ja": "Japones",
    "jpn": "Japones",
    "pt": "Portugues",
    "por": "Portugues",
}


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
    return f"{round(size / (1024 ** 3), 2)} GB"


def _is_known(value: str) -> bool:
    return bool(value and value != "?")


def _extract_primary_media_source(item: dict[str, Any]) -> dict[str, Any]:
    media_sources = item.get("MediaSources")
    if isinstance(media_sources, list) and media_sources and isinstance(media_sources[0], dict):
        return media_sources[0]
    return {}


def _media_streams(item: dict[str, Any], media_source: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    streams = []
    if media_source:
        source_streams = media_source.get("MediaStreams")
        if isinstance(source_streams, list):
            streams.extend([stream for stream in source_streams if isinstance(stream, dict)])
    item_streams = item.get("MediaStreams")
    if isinstance(item_streams, list):
        streams.extend([stream for stream in item_streams if isinstance(stream, dict)])
    return streams


def _streams_by_type(
    item: dict[str, Any],
    media_source: dict[str, Any] | None,
    stream_type: str,
) -> list[dict[str, Any]]:
    return [
        stream
        for stream in _media_streams(item, media_source)
        if (stream.get("Type") or "").lower() == stream_type.lower()
    ]


def _resolution_from_media_streams(item: dict[str, Any], media_source: dict[str, Any]) -> str:
    for stream in _streams_by_type(item, media_source, "video"):
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


def _display_resolution(resolution: str) -> str:
    return "4K" if resolution == "2160p" else resolution


def _join_known(parts: list[str]) -> str:
    return " · ".join([part for part in parts if _is_known(part)])


def _build_file_specs(item: dict[str, Any], season_mode: bool = False) -> str:
    media_source = _extract_primary_media_source(item)
    media_type = item.get("Type")
    summary = _format_media_source_summary(item, media_source, include_release_type=media_type == "Movie")
    detail_lines = _format_media_detail_lines(item, media_source)
    if season_mode:
        heading = "📦 Archivo: Episodios añadidos"
    elif media_type == "Movie":
        heading = "📦 Archivo: Pelicula"
    elif media_type == "Episode":
        heading = "📦 Archivo: Episodio"
    else:
        return ""
    lines = [heading]
    if summary:
        lines.append(summary)
    lines.extend(detail_lines)
    return "\n".join(lines)


def _format_episode_list(episode_list: list[str] | None, max_items: int = 12) -> str:
    if not episode_list:
        return ""
    if len(episode_list) <= max_items:
        return ", ".join(episode_list)
    shown = ", ".join(episode_list[:max_items])
    hidden = len(episode_list) - max_items
    return f"{shown} ... (+{hidden})"


def _format_episode_tags(episode_list: list[str] | None) -> str:
    if not episode_list:
        return ""
    episode_numbers = []
    for tag in episode_list:
        match = re.search(r"E(\d+)$", tag, re.IGNORECASE)
        if not match:
            continue
        episode_numbers.append(int(match.group(1)))
    if episode_numbers:
        return _format_number_ranges(episode_numbers, prefix="E")
    return _format_episode_list(episode_list)


def _format_number_ranges(numbers: list[int], prefix: str = "") -> str:
    clean_numbers = sorted(set(number for number in numbers if number > 0))
    if not clean_numbers:
        return ""

    ranges = []
    start = previous = clean_numbers[0]
    for number in clean_numbers[1:]:
        if number == previous + 1:
            previous = number
            continue
        ranges.append((start, previous))
        start = previous = number
    ranges.append((start, previous))

    parts = []
    for start, end in ranges:
        start_label = f"{prefix}{start:02}"
        end_label = f"{prefix}{end:02}"
        parts.append(start_label if start == end else f"{start_label}-{end_label}")
    return ", ".join(parts)


def _first_str(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _codec_label(value: Any) -> str:
    return _first_str(value).upper()


def _language_label(stream: dict[str, Any]) -> str:
    raw_language = _first_str(stream.get("Language"), stream.get("DisplayLanguage"))
    label = LANGUAGE_LABELS.get(raw_language.lower(), raw_language)
    return _first_str(label, stream.get("Title"))


def _channel_label(channels: Any) -> str:
    try:
        channel_count = int(channels or 0)
    except Exception:
        channel_count = 0
    mapping = {
        1: "1.0",
        2: "2.0",
        6: "5.1",
        8: "7.1",
    }
    if channel_count in mapping:
        return mapping[channel_count]
    return f"{channel_count}ch" if channel_count else ""


def _video_label(stream: dict[str, Any]) -> str:
    codec = _codec_label(stream.get("Codec"))
    hdr = _first_str(
        stream.get("VideoRange"),
        stream.get("VideoRangeType"),
        stream.get("VideoDoViTitle"),
        stream.get("Profile"),
    )
    if hdr and hdr.lower() in {"main", "high", "baseline"}:
        hdr = ""
    return _join_known([codec, hdr])


def _audio_label(stream: dict[str, Any]) -> str:
    language = _language_label(stream)
    codec = _codec_label(stream.get("Codec"))
    channels = _channel_label(stream.get("Channels"))
    return _join_known([language, codec, channels])


def _subtitle_label(stream: dict[str, Any]) -> str:
    language = _language_label(stream)
    flags = []
    if stream.get("IsForced"):
        flags.append("forzados")
    if stream.get("IsExternal"):
        flags.append("externos")
    suffix = f" ({', '.join(flags)})" if flags else ""
    return f"{language or 'Subtitulos'}{suffix}"


def _format_stream_labels(labels: list[str], max_items: int = 4) -> str:
    clean_labels = [label for label in labels if label]
    if not clean_labels:
        return ""
    shown = clean_labels[:max_items]
    if len(clean_labels) > max_items:
        shown.append(f"+{len(clean_labels) - max_items}")
    return ", ".join(shown)


def _format_media_source_summary(
    item: dict[str, Any],
    media_source: dict[str, Any],
    include_release_type: bool = False,
) -> str:
    path = _first_str(item.get("Path"), media_source.get("Path"), media_source.get("Name"), item.get("Name"))
    resolution = resolution_from_filename(path)
    if not _is_known(resolution):
        resolution = _resolution_from_media_streams(item, media_source)
    release_type = release_type_from_filename(path) if include_release_type else ""
    container = _first_str(media_source.get("Container"), item.get("Container")).upper()
    size = _size_to_gib(media_source.get("Size") or item.get("Size"))
    return _join_known([_display_resolution(resolution), release_type, container, size])


def _format_media_detail_lines(item: dict[str, Any], media_source: dict[str, Any]) -> list[str]:
    video = _format_stream_labels([_video_label(stream) for stream in _streams_by_type(item, media_source, "video")], 1)
    audio = _format_stream_labels([_audio_label(stream) for stream in _streams_by_type(item, media_source, "audio")])
    subtitles = _format_stream_labels(
        [_subtitle_label(stream) for stream in _streams_by_type(item, media_source, "subtitle")]
    )
    lines = []
    if video:
        lines.append(f"Video: {video}")
    if audio:
        lines.append(f"Audio: {audio}")
    if subtitles:
        lines.append(f"Subs: {subtitles}")
    return lines


def _provider_ids(item: dict[str, Any]) -> dict[str, Any]:
    provider_ids = item.get("ProviderIds")
    return provider_ids if isinstance(provider_ids, dict) else {}


def _imdb_url(item: dict[str, Any]) -> str:
    provider_ids = _provider_ids(item)
    imdb_id = _first_str(
        provider_ids.get("Imdb"),
        provider_ids.get("IMDb"),
        provider_ids.get("IMDB"),
        provider_ids.get("imdb"),
    )
    if not imdb_id:
        return ""
    if not imdb_id.startswith("tt"):
        imdb_id = f"tt{imdb_id}"
    return f"https://www.imdb.com/title/{imdb_id}/"


def _format_external_links(item: dict[str, Any]) -> list[str]:
    imdb = _imdb_url(item)
    return [f"IMDb: {imdb}"] if imdb else []


def _format_rating(value: Any) -> str:
    if value in {None, ""}:
        return ""
    return f"{float(value):.1f}" if isinstance(value, (int, float)) else str(value)


def _expandable_section(text: str) -> str:
    return f"{EXPANDABLE_SECTION_START}{text}{EXPANDABLE_SECTION_END}"


def _short_overview(overview: str, max_length: int = 450) -> str:
    if len(overview) <= max_length:
        return overview
    return overview[:max_length] + "..."


def _common_episode_stream_lines(seasons: list[dict[str, Any]]) -> list[str]:
    audio_sets = []
    subtitle_sets = []
    for season in seasons:
        episodes = season.get("Episodes")
        if not isinstance(episodes, list):
            continue
        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            media_source = _extract_primary_media_source(episode)
            audio = {
                _audio_label(stream)
                for stream in _streams_by_type(episode, media_source, "audio")
                if _audio_label(stream)
            }
            subtitles = {
                _subtitle_label(stream)
                for stream in _streams_by_type(episode, media_source, "subtitle")
                if _subtitle_label(stream)
            }
            if audio:
                audio_sets.append(audio)
            if subtitles:
                subtitle_sets.append(subtitles)

    lines = []
    if audio_sets:
        common_audio = sorted(set.intersection(*audio_sets))
        audio = _format_stream_labels(common_audio, max_items=6)
        if audio:
            lines.append(f"Audio comun: {audio}")
    if subtitle_sets:
        common_subtitles = sorted(set.intersection(*subtitle_sets))
        subtitles = _format_stream_labels(common_subtitles, max_items=6)
        if subtitles:
            lines.append(f"Subs comunes: {subtitles}")
    return lines


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
        normalized_event = re.sub(r"[^a-z0-9]+", "", raw_event)
        mapping = {
            "playbackstart": "playback.start",
            "playbackstarted": "playback.start",
            "playbackstop": "playback.stop",
            "playbackstopped": "playback.stop",
            "playbackpause": "playback.pause",
            "playbackpaused": "playback.pause",
            "playbackunpause": "playback.unpause",
            "playbackunpaused": "playback.unpause",
            "playbackresume": "playback.unpause",
            "playbackresumed": "playback.unpause",
            "sessionstart": "session.start",
            "sessionstarted": "session.start",
            "sessionend": "session.end",
            "sessionended": "session.end",
            "sessionstop": "session.end",
            "sessionstopped": "session.end",
            "systemnotificationtest": "system.notificationtest",
        }
        if normalized_event in mapping:
            return mapping[normalized_event]
        if raw_event.startswith(("playback.", "session.", "system.")):
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
        title = f"📺 Serie actualizada: {series_name} T{season_number:02}"
        caption = title
        formatted_episodes = _format_episode_tags(episode_list)
        if formatted_episodes:
            caption += f"\n🧩 Episodios añadidos: {formatted_episodes}"
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
        rating_str = _format_rating(rating)
        caption += f"\n⭐ Valoración: {rating_str}/10"

    overview = _first_str(item.get("Overview"))
    if overview and item_type in {"Movie", "Series"} and not season_mode:
        caption += f"\n\nSinopsis:\n{_expandable_section(_short_overview(overview))}"

    specs = _build_file_specs(item, season_mode=season_mode)
    if specs:
        caption += f"\n{SECTION_DIVIDER}\n{specs}"
    external_links = _format_external_links(item)
    if external_links:
        caption += f"\n{SECTION_DIVIDER}\n" + "\n".join(external_links)
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


def _format_movie_versions(item: dict[str, Any], max_versions: int = 4) -> list[str]:
    media_sources = item.get("MediaSources")
    if not isinstance(media_sources, list) or not media_sources:
        return []

    valid_sources = [s for s in media_sources if isinstance(s, dict)]
    if not valid_sources:
        return []

    lines = ["Datos de la version:" if len(valid_sources) == 1 else "Versiones disponibles:"]
    for index, source in enumerate(valid_sources[:max_versions], start=1):
        details = _format_media_source_summary(item, source, include_release_type=True)
        line = f"{index}. {details}" if details else f"{index}. Version"
        lines.append(line)
        lines.extend([f"   {detail}" for detail in _format_media_detail_lines(item, source)])
    if len(valid_sources) > max_versions:
        lines.append(f"... +{len(valid_sources) - max_versions} versiones mas")
    return lines


def _format_series_availability(seasons: list[dict[str, Any]], max_seasons: int = 8) -> list[str]:
    if not seasons:
        return []
    total_episodes = 0
    lines = []
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
            total_episodes += len(episode_numbers)
            episodes_text = _format_number_ranges(episode_numbers, prefix="E")
            lines.append(f"T{season_number:02}: {episodes_text}")
            continue
        child_count = season.get("ChildCount")
        try:
            total_episodes += int(child_count or 0)
        except Exception:
            pass
        suffix = f"{child_count} episodios" if child_count else "episodios disponibles"
        lines.append(f"T{season_number:02}: {suffix}")
    if len(seasons) > max_seasons:
        lines.append(f"... +{len(seasons) - max_seasons} temporadas mas")
    summary = f"{len(seasons)} temporadas"
    if total_episodes:
        summary += f" · {total_episodes} episodios disponibles"
    common_streams = _common_episode_stream_lines(seasons)
    if common_streams:
        lines.extend(["", *common_streams])
    return [summary, "Temporadas disponibles:", *lines]


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
    rating = _format_rating(item.get("CommunityRating"))
    if rating:
        caption += f"\n⭐ Valoración: {rating}/10"
    overview = _first_str(item.get("Overview"))
    if overview:
        caption += f"\n\nSinopsis:\n{_expandable_section(_short_overview(overview))}"
    extra_lines = []
    if item_type == "Movie":
        extra_lines = _format_movie_versions(item)
    elif item_type == "Series" and series_seasons:
        extra_lines = _format_series_availability(series_seasons)
    if extra_lines:
        caption += f"\n\n{SECTION_DIVIDER}\n" + "\n".join(extra_lines)
    external_links = _format_external_links(item)
    if external_links:
        caption += f"\n\n{SECTION_DIVIDER}\n" + "\n".join(external_links)
    return _trim_caption(caption)
