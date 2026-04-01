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
        return self._get(f"Items/{item_id}", params={"Fields": "MediaStreams,Path"}).json()

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

