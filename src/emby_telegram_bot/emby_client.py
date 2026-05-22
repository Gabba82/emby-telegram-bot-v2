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

    def validate_credentials(self) -> str:
        payload = self._get("System/Info").json()
        server_name = payload.get("ServerName") or payload.get("LocalAddress") or "Emby"
        version = payload.get("Version")
        return f"{server_name} {version}".strip()

    def get_item_info(self, item_id: str) -> dict[str, Any]:
        return self._get(
            f"Items/{item_id}",
            params={
                "Fields": (
                    "MediaStreams,MediaSources,Path,Container,Size,ProductionYear,"
                    "Overview,CommunityRating,ProviderIds,DateCreated,SeriesInfo,ParentId"
                )
            },
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
                "Fields": (
                    "MediaStreams,MediaSources,Path,Container,Size,ProductionYear,"
                    "Overview,CommunityRating,ProviderIds,DateCreated,SeriesInfo,ParentId"
                ),
            },
        ).json()
        items = payload.get("Items", [])
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]
        return {}

    def search_items(
        self,
        query: str,
        limit: int = 10,
        include_item_types: str = "Movie,Series",
    ) -> list[dict[str, Any]]:
        query = query.strip()
        if not query:
            return []

        item_types = include_item_types.strip() or "Movie,Series"
        payload = self._get(
            "Items",
            params={
                "SearchTerm": query,
                "IncludeItemTypes": item_types,
                "Recursive": "true",
                "Limit": limit,
                "Fields": "ProductionYear,Overview",
            },
        ).json()
        items = payload.get("Items", [])
        if not isinstance(items, list):
            return []
        return [item for item in items if isinstance(item, dict)]

    def get_latest_added_item(self) -> dict[str, Any]:
        items = self.get_recently_added_items(limit=1)
        if items:
            item_id = items[0].get("Id")
            if item_id:
                detailed = self.get_item_by_id(str(item_id))
                if detailed:
                    return detailed
            return items[0]
        return {}

    def get_recently_added_items(self, limit: int = 10) -> list[dict[str, Any]]:
        fetch_limit = max(limit * 5, 50)
        payload = self._get(
            "Items",
            params={
                "IncludeItemTypes": "Movie,Series,Episode",
                "Recursive": "true",
                "SortBy": "DateCreated",
                "SortOrder": "Descending",
                "Limit": fetch_limit,
                "Fields": (
                    "MediaStreams,MediaSources,Path,Container,Size,ProductionYear,"
                    "Overview,CommunityRating,ProviderIds,DateCreated,SeriesInfo,ParentId"
                ),
            },
        ).json()
        items = payload.get("Items", [])
        if not isinstance(items, list):
            return []

        collapsed_items: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            display_item = item
            item_type = item.get("Type")
            item_id = str(item.get("Id") or "")
            unique_key = f"{item_type}:{item_id}"

            if item_type == "Episode":
                series_id = str(item.get("SeriesId") or "")
                if series_id:
                    unique_key = f"Series:{series_id}"
                    if unique_key in seen_keys:
                        continue
                    try:
                        series_item = self.get_item_by_id(series_id)
                        if series_item:
                            display_item = series_item
                    except Exception as exc:
                        logging.warning("Cannot fetch series for recent episode series_id=%s error=%s", series_id, exc)
                        display_item = {
                            "Id": series_id,
                            "Type": "Series",
                            "Name": item.get("SeriesName") or item.get("Name") or "Serie",
                            "ProductionYear": item.get("ProductionYear"),
                        }

            if not item_id and item_type != "Episode":
                continue
            if unique_key in seen_keys:
                continue
            seen_keys.add(unique_key)
            collapsed_items.append(display_item)
            if len(collapsed_items) >= limit:
                break

        return collapsed_items

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
