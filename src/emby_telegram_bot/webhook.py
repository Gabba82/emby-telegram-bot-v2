from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

from flask import Flask, Request, Response, request

from .config import Settings
from .emby_client import EmbyClient
from .episode_aggregator import EpisodeAggregator
from .formatting import (
    build_activity_caption,
    build_caption,
    infer_activity_event_code,
    is_activity_payload,
)
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
    playback_targets = settings.playback_chat_ids or settings.chat_ids
    library_targets = settings.library_chat_ids or settings.chat_ids
    recent_playback: dict[tuple[str, str], float] = {}
    playback_lock = threading.Lock()

    def _should_send_playback_event(payload: dict[str, Any], activity_item: dict[str, Any]) -> bool:
        event_code = infer_activity_event_code(payload)
        # Always keep terminal events visible.
        if event_code in {"playback.stop", "session.end"}:
            return True
        if not event_code.startswith("playback."):
            return True
        if settings.playback_debounce_seconds == 0:
            return True

        user_data = payload.get("User") if isinstance(payload.get("User"), dict) else {}
        user_key = str(
            payload.get("UserId")
            or payload.get("UserName")
            or user_data.get("Id")
            or user_data.get("Name")
            or "unknown_user"
        )

        item_data = activity_item if isinstance(activity_item, dict) and activity_item else {}
        payload_item = payload.get("Item") if isinstance(payload.get("Item"), dict) else {}
        item_key = str(
            item_data.get("Id")
            or payload_item.get("Id")
            or payload.get("ItemId")
            or item_data.get("Name")
            or payload_item.get("Name")
            or "unknown_item"
        )

        key = (user_key, item_key)
        now = time.time()
        with playback_lock:
            previous = recent_playback.get(key, 0.0)
            if now - previous < settings.playback_debounce_seconds:
                logging.info(
                    "Playback event debounced for user=%s item=%s event=%s (window=%ss)",
                    user_key,
                    item_key,
                    event_code,
                    settings.playback_debounce_seconds,
                )
                return False
            recent_playback[key] = now
        return True

    def flush_episode_group(sample_item: dict[str, Any], episode_list: list[str]) -> None:
        caption = build_caption(sample_item, season_mode=True, episode_list=episode_list)
        image = emby.get_item_image(sample_item)
        telegram.send(caption, image, chat_ids=library_targets)

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

        if settings.enable_playback_notifications and is_activity_payload(payload):
            activity_item = payload.get("Item") if isinstance(payload.get("Item"), dict) else {}
            activity_item_id = activity_item.get("Id") or payload.get("ItemId")
            if activity_item_id and (
                not activity_item or not activity_item.get("Type") or not activity_item.get("Name")
            ):
                try:
                    activity_item = emby.get_item_info(str(activity_item_id))
                except Exception as exc:
                    logging.warning("Cannot fetch activity item id=%s error=%s", activity_item_id, exc)

            if not _should_send_playback_event(payload, activity_item):
                return "", 200

            activity_caption = build_activity_caption(
                payload,
                item_override=activity_item,
                style=settings.playback_style,
                timezone_name=settings.app_timezone,
            )
            if activity_caption:
                activity_image = (
                    emby.get_item_image(activity_item)
                    if activity_item and settings.playback_with_image
                    else None
                )
                telegram.send(activity_caption, activity_image, chat_ids=playback_targets)
                return "", 200

        item = payload.get("Item") or {}
        item_id = item.get("Id") or payload.get("ItemId")

        if not item and item_id:
            try:
                item = emby.get_item_info(str(item_id))
            except Exception as exc:
                logging.error("Cannot fetch item id=%s error=%s", item_id, exc)
                return "", 200

        if item:
            if not settings.enable_library_notifications:
                logging.info("Library notifications disabled; skipping media notification")
                return "", 200

            if item.get("Type") == "Episode":
                aggregator.add_episode(item)
                return "", 200

            caption = build_caption(item)
            image = emby.get_item_image(item)
            telegram.send(caption, image, chat_ids=library_targets)
            return "", 200

        logging.info("Ignored non-media event: %s", payload.get("Event") or "unknown")
        return "", 200

    return app
