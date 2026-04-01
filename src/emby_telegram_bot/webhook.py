from __future__ import annotations

import json
import logging
from typing import Any

from flask import Flask, Request, Response, request

from .config import Settings
from .emby_client import EmbyClient
from .episode_aggregator import EpisodeAggregator
from .formatting import build_activity_caption, build_caption
from .telegram_client import TelegramClient


def _extract_payload(req: Request) -> dict[str, Any]:
    if req.is_json:
        return req.get_json(silent=True) or {}

    payload: dict[str, Any] = {}
    for file in req.files.values():
        if file.mimetype.startswith("application/json"):
            try:
                payload = json.load(file.stream)
            except Exception as exc:
                logging.error("Error parsing multipart JSON: %s", exc)
            break
    return payload


def create_app(settings: Settings) -> Flask:
    app = Flask(__name__)
    emby = EmbyClient(
        base_url=settings.emby_api_url,
        api_key=settings.emby_api_key,
        timeout_seconds=settings.request_timeout_seconds,
    )
    telegram = TelegramClient(token=settings.telegram_token, chat_ids=settings.chat_ids)

    def flush_episode_group(sample_item: dict[str, Any], episode_list: list[str]) -> None:
        caption = build_caption(sample_item, season_mode=True, episode_list=episode_list)
        image = emby.get_item_image(sample_item)
        telegram.send(caption, image)

    aggregator = EpisodeAggregator(
        flush_delay_seconds=settings.episode_buffer_seconds,
        flush_callback=flush_episode_group,
    )

    @app.get("/health")
    def health() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.post("/embyhook")
    def embyhook() -> Response | tuple[str, int]:
        payload = _extract_payload(request)
        logging.info("Webhook event received")

        item = payload.get("Item") or {}
        item_id = item.get("Id") or payload.get("ItemId")

        if not item and item_id:
            try:
                item = emby.get_item_info(str(item_id))
            except Exception as exc:
                logging.error("Cannot fetch item id=%s error=%s", item_id, exc)
                return "", 200

        if item:
            if item.get("Type") == "Episode":
                aggregator.add_episode(item)
                return "", 200

            caption = build_caption(item)
            image = emby.get_item_image(item)
            telegram.send(caption, image)
            return "", 200

        activity_caption = build_activity_caption(payload)
        if activity_caption:
            telegram.send(activity_caption, None)
            return "", 200

        logging.info("Ignored non-media event: %s", payload.get("Event") or "unknown")
        return "", 200

    return app
