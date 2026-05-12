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
    build_search_item_caption,
    build_search_results_message,
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
    allowed_telegram_chats = set(settings.chat_ids + settings.library_chat_ids + settings.playback_chat_ids)
    recent_playback: dict[tuple[str, str], float] = {}
    playback_lock = threading.Lock()

    def _should_send_playback_event(payload: dict[str, Any], activity_item: dict[str, Any]) -> bool:
        event_code = infer_activity_event_code(payload)
        if event_code == "playback.pause" and not settings.playback_notify_pause:
            logging.info("Playback pause notification skipped by config")
            return False
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

    def _is_authorized_chat(chat_id: str) -> bool:
        return chat_id in allowed_telegram_chats

    def _send_search_results(chat_id: str, query: str, with_images: bool = False) -> None:
        clean_query = query.strip()
        if len(clean_query) < 2:
            telegram.send_text("Escribe al menos 2 caracteres para buscar.", chat_ids=[chat_id])
            return
        try:
            items = emby.search_items(clean_query)
        except Exception as exc:
            logging.error("Emby search failed query=%s error=%s", clean_query, exc)
            telegram.send_text("No he podido consultar Emby ahora mismo. Revisa logs y conexion.", chat_ids=[chat_id])
            return
        if with_images and items:
            if len(items) == 1:
                _send_search_item(chat_id, items[0])
                return
            telegram.send_search_selection_menu(chat_id, clean_query, items)
            return
        telegram.send_text(build_search_results_message(clean_query, items), chat_ids=[chat_id])

    def _send_search_item(chat_id: str, item: dict[str, Any], fetch_details: bool = True) -> None:
        item_id = item.get("Id")
        if item_id and fetch_details:
            try:
                detailed_item = emby.get_item_by_id(str(item_id))
                if detailed_item:
                    item = detailed_item
            except Exception as exc:
                logging.warning("Cannot fetch selected item id=%s error=%s", item_id, exc)
        series_seasons = []
        if item.get("Type") == "Series" and item.get("Id"):
            try:
                series_seasons = emby.get_series_seasons(str(item["Id"]))
                for season in series_seasons:
                    season_id = season.get("Id")
                    if season_id:
                        season["Episodes"] = emby.get_season_episodes(str(item["Id"]), str(season_id))
            except Exception as exc:
                logging.warning("Cannot fetch series availability id=%s error=%s", item.get("Id"), exc)
        image = emby.get_item_image(item)
        telegram.send(build_search_item_caption(item, series_seasons=series_seasons), image, chat_ids=[chat_id])

    def _handle_telegram_message(message: dict[str, Any]) -> None:
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        chat_id = str(chat.get("id") or "")
        user = message.get("from") if isinstance(message.get("from"), dict) else {}
        private_chat_id = str(user.get("id") or "")
        is_private_chat = chat.get("type") == "private"
        reply_to_message = message.get("reply_to_message") if isinstance(message.get("reply_to_message"), dict) else {}
        reply_text = str(reply_to_message.get("text") or "")
        is_search_reply = is_private_chat and reply_text.startswith("Escribe el titulo de la pelicula o serie")

        text = str(message.get("text") or "").strip()
        if not text:
            return

        command, _, arg = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        is_private_menu_command = is_private_chat and command in {"/start", "/menu"}

        if not chat_id or (not _is_authorized_chat(chat_id) and not is_search_reply and not is_private_menu_command):
            logging.warning("Telegram update ignored from unauthorized chat_id=%s", chat_id or "unknown")
            return

        if text == "🔎 Buscar pelicula o serie":
            telegram.request_search_query(chat_id)
            return
        if command in {"/start", "/menu"}:
            if is_private_chat:
                telegram.send_private_search_keyboard(chat_id)
                return
            telegram.send_search_menu(chat_id)
            return
        if command == "/buscar":
            target_chat_id = chat_id if is_private_chat else private_chat_id
            if not target_chat_id:
                return
            if not arg.strip():
                telegram.request_search_query(target_chat_id)
                return
            _send_search_results(target_chat_id, arg, with_images=True)
            return

        if is_search_reply:
            _send_search_results(chat_id, text, with_images=chat.get("type") == "private")
            return

        if is_private_chat:
            _send_search_results(chat_id, text, with_images=True)

    def _handle_telegram_callback(callback_query: dict[str, Any]) -> None:
        callback_id = str(callback_query.get("id") or "")
        message = callback_query.get("message") if isinstance(callback_query.get("message"), dict) else {}
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        chat_id = str(chat.get("id") or "")
        user = callback_query.get("from") if isinstance(callback_query.get("from"), dict) else {}
        private_chat_id = str(user.get("id") or "")
        callback_data = str(callback_query.get("data") or "")

        is_private_selection = chat.get("type") == "private" and callback_data.startswith("search:item:")
        if not chat_id or (not _is_authorized_chat(chat_id) and not is_private_selection):
            if callback_id:
                telegram.answer_callback_query(callback_id)
            logging.warning("Telegram callback ignored from unauthorized chat_id=%s", chat_id or "unknown")
            return

        if callback_data.startswith("search:item:"):
            item_id = callback_data.removeprefix("search:item:")
            if callback_id:
                telegram.answer_callback_query(callback_id, "Preparando ficha...")
            try:
                item = emby.get_item_by_id(item_id)
            except Exception as exc:
                logging.error("Cannot fetch selected search item id=%s error=%s", item_id, exc)
                telegram.send_text("No he podido cargar ese resultado ahora mismo.", chat_ids=[chat_id])
                return
            if not item:
                logging.error("Selected search item id=%s returned no details", item_id)
                telegram.send_text("No he podido cargar ese resultado ahora mismo.", chat_ids=[chat_id])
                return
            _send_search_item(chat_id, item, fetch_details=False)
            return

        if callback_data == "search:start":
            if chat.get("type") == "private":
                if callback_id:
                    telegram.answer_callback_query(callback_id)
                telegram.request_search_query(chat_id)
                return
            if private_chat_id:
                telegram.request_search_query(private_chat_id)
                if callback_id:
                    telegram.answer_callback_query(
                        callback_id,
                        "Te he escrito por privado. Si no llega, abre el bot y pulsa Iniciar.",
                        show_alert=True,
                    )
                return
        if callback_id:
            telegram.answer_callback_query(callback_id)

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

    @app.post("/telegramhook")
    def telegramhook() -> tuple[str, int]:
        if settings.telegram_webhook_secret:
            received_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if received_secret != settings.telegram_webhook_secret:
                logging.warning("Telegram webhook rejected because secret token did not match")
                return "", 403

        payload = request.get_json(silent=True) or {}
        message = payload.get("message") if isinstance(payload.get("message"), dict) else None
        callback_query = (
            payload.get("callback_query") if isinstance(payload.get("callback_query"), dict) else None
        )

        if message:
            _handle_telegram_message(message)
        elif callback_query:
            _handle_telegram_callback(callback_query)
        else:
            logging.info("Ignored unsupported Telegram update")

        return "", 200

    return app
