from __future__ import annotations

import logging
from typing import Any

import requests


class EmbyClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: int) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds

    def _get(self, path: str, params: dict[str, Any] | None = None, stream: bool = False) -> requests.Response:
        query = dict(params or {})
        query["api_key"] = self._api_key
        url = f"{self._base_url}/{path.lstrip('/')}"
        response = requests.get(url, params=query, timeout=self._timeout, stream=stream)
        response.raise_for_status()
        return response

    def get_item_info(self, item_id: str) -> dict[str, Any]:
        return self._get(
            f"Items/{item_id}",
            params={"Fields": "MediaStreams,MediaSources,Path,Container,Size,ProductionYear,Overview"},
        ).json()

    def get_item_by_id(self, item_id: str) -> dict[str, Any]:
        item_id = item_id.strip()
        if not item_id:
            return {}
        try:
            return self.get_item_info(item_id)
        except Exception:
            logging.debug("Direct item lookup failed for item=%s; trying Items?Ids fallback", item_id)

        payload = self._get(
            "Items",
            params={
                "Ids": item_id,
                "Recursive": "true",
                "Fields": "MediaStreams,MediaSources,Path,Container,Size,ProductionYear,Overview",
            },
        ).json()
        items = payload.get("Items", [])
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
        return {}

    def search_items(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []

        payload = self._get(
            "Items",
            params={
                "SearchTerm": query,
                "IncludeItemTypes": "Movie,Series",
                "Recursive": "true",
                "Limit": limit,
                "Fields": "ProductionYear,Overview",
            },
        ).json()
        items = payload.get("Items", [])
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def get_series_seasons(self, series_id: str) -> list[dict[str, Any]]:
        try:
            payload = self._get(
                f"Shows/{series_id}/Seasons",
                params={"Fields": "ChildCount,IndexNumber"},
            ).json()
        except Exception:
            logging.debug("Shows seasons lookup failed for series=%s; trying Items fallback", series_id)
            payload = self._get(
                "Items",
                params={
                    "ParentId": series_id,
                    "IncludeItemTypes": "Season",
                    "Recursive": "false",
                    "Fields": "ChildCount,IndexNumber",
                },
            ).json()
        items = payload.get("Items", [])
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def get_season_episodes(self, series_id: str, season_id: str) -> list[dict[str, Any]]:
        try:
            payload = self._get(
                f"Shows/{series_id}/Episodes",
                params={"SeasonId": season_id, "Fields": "IndexNumber,ParentIndexNumber"},
            ).json()
        except Exception:
            logging.debug("Shows episodes lookup failed for season=%s; trying Items fallback", season_id)
            payload = self._get(
                "Items",
                params={
                    "ParentId": season_id,
                    "IncludeItemTypes": "Episode",
                    "Recursive": "true",
                    "Fields": "IndexNumber,ParentIndexNumber",
                },
            ).json()
        items = payload.get("Items", [])
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def fetch_image(self, item_id: str | None) -> bytes | None:
        if not item_id:
            return None
        for image_type in ("Primary", "Thumb", "Backdrop"):
            try:
                response = self._get(
                    f"Items/{item_id}/Images/{image_type}",
                    params={"maxWidth": 800, "quality": 90},
                    stream=True,
                )
                content = response.content
                if content:
                    return content
            except Exception:
                logging.debug("No image found for item=%s image_type=%s", item_id, image_type)
        return None

    def get_item_image(self, item: dict[str, Any]) -> bytes | None:
        if item.get("Type") == "Episode":
            parent_id = item.get("SeriesId") or item.get("ParentId")
            parent_image = self.fetch_image(parent_id)
            if parent_image:
                return parent_image
        return self.fetch_image(item.get("Id"))
