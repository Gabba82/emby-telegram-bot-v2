from __future__ import annotations

import re
from typing import Any

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


def _fmt_value(value: str) -> str:
    return value if value and value != "?" else "N/D"


def _build_file_specs(item: dict[str, Any], season_mode: bool = False) -> str:
    container = (item.get("Container") or "").upper() or "?"
    path = item.get("Path", "")
    resolution = resolution_from_filename(path)
    size_str = _size_to_gib(item.get("Size"))
    media_type = item.get("Type")

    if season_mode:
        return f"⚙️ Archivo: Temporada | {_fmt_value(resolution)} | {_fmt_value(container)}"
    if media_type == "Movie":
        release_type = release_type_from_filename(path)
        return (
            f"⚙️ Archivo: Pelicula | {_fmt_value(release_type)} | {_fmt_value(resolution)} | "
            f"{_fmt_value(container)} | {_fmt_value(size_str)}"
        )
    if media_type == "Episode":
        return (
            f"⚙️ Archivo: Episodio | {_fmt_value(resolution)} | "
            f"{_fmt_value(container)} | {_fmt_value(size_str)}"
        )
    return ""


def _format_episode_list(episode_list: list[str] | None, max_items: int = 12) -> str:
    if not episode_list:
        return ""
    if len(episode_list) <= max_items:
        return ", ".join(episode_list)
    shown = ", ".join(episode_list[:max_items])
    hidden = len(episode_list) - max_items
    return f"{shown} ... (+{hidden})"


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
