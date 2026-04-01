from __future__ import annotations

import re
from typing import Any


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


def build_specs(item: dict[str, Any], season_mode: bool = False) -> str:
    container = (item.get("Container") or "").upper() or "?"
    path = item.get("Path", "")
    resolution = resolution_from_filename(path)
    size_str = _size_to_gib(item.get("Size"))

    if season_mode:
        return f"\n\nTipo: Temporada | {resolution} | {container}"
    if item.get("Type") == "Movie":
        release_type = release_type_from_filename(path)
        return f"\n\nTipo: Pelicula | {release_type} | {resolution} | {container} | {size_str}"
    if item.get("Type") == "Episode":
        return f"\n\nTipo: Episodio | {resolution} | {container} | {size_str}"
    return ""


def build_caption(item: dict[str, Any], season_mode: bool = False, episode_list: list[str] | None = None) -> str:
    item_type = item.get("Type")
    name = item.get("Name") or "Nuevo contenido"
    year = item.get("ProductionYear")
    rating = item.get("CommunityRating")

    if season_mode:
        series_name = item.get("SeriesName") or "Serie"
        season_number = item.get("ParentIndexNumber") or item.get("IndexNumber") or 0
        title = f"Serie: {series_name} (Temporada {season_number})"
        caption = title
        if episode_list:
            caption += f"\nCapitulos anadidos: {', '.join(episode_list)}"
    elif item_type == "Movie":
        title = f"Pelicula: {name} ({year})" if year else f"Pelicula: {name}"
        caption = title
    elif item_type == "Episode":
        series_name = item.get("SeriesName") or "Serie"
        season = item.get("ParentIndexNumber") or 0
        episode = item.get("IndexNumber") or 0
        caption = f"Serie: {series_name} S{season:02}E{episode:02} - {name}"
    else:
        caption = name

    if rating:
        caption += f"\nRating: {rating}/10"

    caption += build_specs(item, season_mode=season_mode)
    return caption

