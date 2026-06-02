from __future__ import annotations

import json
import logging
import os
import threading
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any

from flask import Flask, Request, Response, request

from .config import Settings
from .diagnostics import (
    build_chat_reachability_checks,
    build_config_checks,
    build_runtime_checks,
    format_diagnostic_report,
)
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
from .telegram_client import (
    ADMIN_DIAGNOSTICS_BUTTON_TEXT,
    ADMIN_LATEST_BUTTON_TEXT,
    ADMIN_PRIVATE_BUTTON_TEXTS,
    ADMIN_RESEND_BY_ID_BUTTON_TEXT,
    ADMIN_RESEND_MENU_BUTTON_TEXT,
    PRIVATE_SEARCH_BUTTON_TEXT,
    TelegramClient,
)


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
    telegram.configure_bot_commands(settings.admin_chat_ids)
    playback_targets = settings.playback_chat_ids or settings.chat_ids
    library_targets = settings.library_chat_ids or settings.chat_ids
    admin_targets = settings.admin_chat_ids or settings.chat_ids
    allowed_telegram_chats = set(
        settings.chat_ids + settings.admin_chat_ids + settings.library_chat_ids + settings.playback_chat_ids
    )
    recent_playback: dict[tuple[str, str], float] = {}
    recent_library: dict[str, float] = {}
    playback_lock = threading.Lock()
    library_lock = threading.Lock()
    search_mode_item_types = {
        "all": "Movie,Series",
        "movies": "Movie",
        "series": "Series",
    }
    startup_checks = [
        *build_config_checks(settings, library_targets, playback_targets, admin_targets),
        *build_runtime_checks(emby, telegram),
        *build_chat_reachability_checks(telegram, list(allowed_telegram_chats)),
    ]
    for check in startup_checks:
        log_message = "Startup check %s %s: %s"
        if check.status == "ERROR":
            logging.error(log_message, check.status, check.label, check.detail)
        elif check.status == "WARNING":
            logging.warning(log_message, check.status, check.label, check.detail)
        else:
            logging.info(log_message, check.status, check.label, check.detail)

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

    def _should_send_library_event(item: dict[str, Any], item_id: str | None) -> bool:
        if settings.library_debounce_seconds == 0:
            return True
        item_key = str(item_id or item.get("Id") or item.get("Name") or "unknown_item")
        item_type = str(item.get("Type") or "unknown_type")
        key = f"{item_type}:{item_key}"
        now = time.time()
        with library_lock:
            previous = recent_library.get(key, 0.0)
            if now - previous < settings.library_debounce_seconds:
                logging.info(
                    "Library event debounced for item=%s type=%s (window=%ss)",
                    item_key,
                    item_type,
                    settings.library_debounce_seconds,
                )
                return False
            recent_library[key] = now
        return True

    def flush_episode_group(sample_item: dict[str, Any], episode_list: list[str]) -> None:
        caption = build_caption(sample_item, season_mode=True, episode_list=episode_list)
        image = emby.get_item_image(sample_item)
        telegram.send(caption, image, chat_ids=library_targets)

    def _is_authorized_chat(chat_id: str) -> bool:
        return chat_id in allowed_telegram_chats

    def _is_admin_private_chat(chat_id: str, is_private_chat: bool) -> bool:
        return is_private_chat and chat_id in set(admin_targets)

    def _search_mode_from_prompt(prompt: str) -> str:
        if "peliculas" in prompt:
            return "movies"
        if "series" in prompt and "peliculas" not in prompt:
            return "series"
        return "all"

    def _format_target_label(target_key: str, default_label: str, chat_ids: list[str]) -> str:
        if target_key in settings.chat_labels:
            return settings.chat_labels[target_key]
        labeled_chat_ids = [settings.chat_labels.get(chat_id, chat_id) for chat_id in chat_ids]
        if labeled_chat_ids and labeled_chat_ids != chat_ids:
            return ", ".join(labeled_chat_ids)
        return default_label

    def _resend_target_options(current_chat_id: str) -> list[tuple[str, str, list[str]]]:
        options: list[tuple[str, str, list[str]]] = [
            ("private", f"Mi privado ({current_chat_id})", [current_chat_id]),
            ("chat", f"CHAT_IDS ({', '.join(settings.chat_ids)})", settings.chat_ids),
        ]
        if settings.library_chat_ids:
            options.append(("library", f"LIBRARY_CHAT_IDS ({', '.join(settings.library_chat_ids)})", settings.library_chat_ids))
        if settings.playback_chat_ids:
            options.append(("playback", f"PLAYBACK_CHAT_IDS ({', '.join(settings.playback_chat_ids)})", settings.playback_chat_ids))
        if settings.admin_chat_ids:
            options.append(("admin", f"ADMIN_CHAT_IDS ({', '.join(settings.admin_chat_ids)})", settings.admin_chat_ids))

        unique_options = []
        seen_targets = set()
        for key, label, chat_ids in options:
            clean_chat_ids = [cid for cid in chat_ids if cid]
            targets_key = tuple(clean_chat_ids)
            if not clean_chat_ids or targets_key in seen_targets:
                continue
            seen_targets.add(targets_key)
            unique_options.append((key, _format_target_label(key, label, clean_chat_ids), clean_chat_ids))
        return unique_options

    def _resolve_resend_targets(target_key: str, current_chat_id: str) -> list[str]:
        for key, _, chat_ids in _resend_target_options(current_chat_id):
            if key == target_key:
                return chat_ids
        return []

    def _send_item_notification(chat_id: str, item: dict[str, Any], target_chat_ids: list[str] | None = None) -> None:
        if not item:
            telegram.send_text("No he encontrado ese contenido en Emby.", chat_ids=[chat_id])
            return
        targets = target_chat_ids or [chat_id]
        item_id = item.get("Id")
        logging.info(
            "Manual resend requested for item_id=%s type=%s name=%s target_chat_ids=%s",
            item_id or "unknown",
            item.get("Type") or "unknown",
            item.get("Name") or "unknown",
            ",".join(targets),
        )
        image = emby.get_item_image(item)
        telegram.send(_build_resend_caption(item), image, chat_ids=targets)

    def _series_seasons_with_episodes(series_id: str) -> list[dict[str, Any]]:
        seasons = emby.get_series_seasons(series_id)
        for season in seasons:
            season_id = season.get("Id")
            if season_id:
                season["Episodes"] = emby.get_season_episodes(series_id, str(season_id))
        return seasons

    def _build_resend_caption(item: dict[str, Any]) -> str:
        if item.get("Type") != "Series" or not item.get("Id"):
            return build_caption(item)
        try:
            series_seasons = _series_seasons_with_episodes(str(item["Id"]))
        except Exception as exc:
            logging.warning("Cannot fetch series details for resend id=%s error=%s", item.get("Id"), exc)
            series_seasons = []
        return build_search_item_caption(item, series_seasons=series_seasons)

    def _open_resend_item_menu(chat_id: str) -> None:
        try:
            items = emby.get_recently_added_items(limit=10)
        except Exception as exc:
            logging.error("Recent items lookup failed error_type=%s error=%s", type(exc).__name__, exc)
            telegram.send_text("No he podido consultar contenido reciente en Emby.", chat_ids=[chat_id])
            return
        telegram.send_resend_item_menu(chat_id, items)

    def _open_resend_target_menu(chat_id: str, item_id: str) -> None:
        clean_item_id = item_id.strip()
        if not clean_item_id:
            telegram.send_text("Uso: /reenvia ID_DE_EMBY", chat_ids=[chat_id])
            return
        try:
            item = emby.get_item_by_id(clean_item_id)
        except Exception as exc:
            logging.error(
                "Manual resend item lookup failed item_id=%s error_type=%s error=%s",
                clean_item_id,
                type(exc).__name__,
                exc,
            )
            telegram.send_text("No he podido consultar ese ID en Emby.", chat_ids=[chat_id])
            return
        if not item:
            telegram.send_text("No he encontrado ese contenido en Emby.", chat_ids=[chat_id])
            return
        item_name = str(item.get("Name") or item.get("SeriesName") or clean_item_id)
        telegram.send_resend_target_menu(chat_id, clean_item_id, item_name, _resend_target_options(chat_id))

    def _send_latest_added(chat_id: str) -> None:
        try:
            item = emby.get_latest_added_item()
        except Exception as exc:
            logging.error("Latest added lookup failed error_type=%s error=%s", type(exc).__name__, exc)
            telegram.send_text("No he podido consultar el ultimo contenido anadido en Emby.", chat_ids=[chat_id])
            return
        if not item:
            telegram.send_text("Emby no ha devuelto ningun contenido reciente.", chat_ids=[chat_id])
            return
        item_id = str(item.get("Id") or "")
        if not item_id:
            telegram.send_text("El ultimo contenido no trae ID de Emby.", chat_ids=[chat_id])
            return
        item_name = str(item.get("Name") or item.get("SeriesName") or item_id)
        telegram.send_resend_target_menu(chat_id, item_id, item_name, _resend_target_options(chat_id))

    def _send_item_by_id(chat_id: str, item_id: str) -> None:
        clean_item_id = item_id.strip()
        if not clean_item_id:
            telegram.send_text("Uso: /reenvia ID_DE_EMBY", chat_ids=[chat_id])
            return
        _open_resend_target_menu(chat_id, clean_item_id)

    def _send_diagnostics(chat_id: str, is_private_chat: bool) -> None:
        checks = [
            *build_config_checks(settings, library_targets, playback_targets, admin_targets),
            *build_runtime_checks(emby, telegram),
            *build_chat_reachability_checks(telegram, list(allowed_telegram_chats)),
        ]
        lines = [
            format_diagnostic_report(checks),
            "",
            f"Chat actual: {chat_id}",
            f"Chat privado admin: {'si' if _is_admin_private_chat(chat_id, is_private_chat) else 'no'}",
            f"Notificaciones biblioteca: {'activas' if settings.enable_library_notifications else 'desactivadas'}",
            f"Notificaciones playback: {'activas' if settings.enable_playback_notifications else 'desactivadas'}",
        ]
        telegram.send_text("\n".join(lines), chat_ids=[chat_id])

    def _send_help(chat_id: str, is_private_chat: bool) -> None:
        lines = [
            "Ayuda del bot:",
            "- /buscar titulo: busca una pelicula o serie.",
            "- /menu: muestra como abrir el menu de comandos.",
        ]
        if _is_admin_private_chat(chat_id, is_private_chat):
            lines.extend(
                [
                    "",
                    "Admin:",
                    "- /reenviar: elegir entre contenido reciente y reenviarlo.",
                    "- /reenviaultimo: reenviar el ultimo contenido anadido.",
                    "- /reenvia ID_DE_EMBY: reenviar una ficha concreta.",
                    "- /diagnostico: validar Emby, Telegram y destinos.",
                    "- /version: ver version desplegada.",
                    "- /reload_menu: recargar comandos del menu de Telegram.",
                ]
            )
        telegram.send_text("\n".join(lines), chat_ids=[chat_id])

    def _send_version(chat_id: str) -> None:
        try:
            package_version = version("emby-telegram-bot-v2")
        except PackageNotFoundError:
            package_version = "desconocida"
        build_version = os.getenv("APP_VERSION", "").strip() or "no configurado"
        telegram.send_text(
            "\n".join(
                [
                    "Version del bot:",
                    f"- Paquete: {package_version}",
                    f"- Build: {build_version}",
                ]
            ),
            chat_ids=[chat_id],
        )

    def _reload_bot_commands(chat_id: str) -> None:
        telegram.configure_bot_commands(settings.admin_chat_ids)
        telegram.send_text("Menu de comandos recargado.", chat_ids=[chat_id])

    def _send_search_results(
        chat_id: str,
        query: str,
        with_images: bool = False,
        mode: str = "all",
    ) -> None:
        clean_query = query.strip()
        if len(clean_query) < 2:
            telegram.send_text("Escribe al menos 2 caracteres para buscar.", chat_ids=[chat_id])
            return
        try:
            items = emby.search_items(clean_query, include_item_types=search_mode_item_types.get(mode, "Movie,Series"))
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
                series_seasons = _series_seasons_with_episodes(str(item["Id"]))
            except Exception as exc:
                logging.warning("Cannot fetch series availability id=%s error=%s", item.get("Id"), exc)
        image = emby.get_item_image(item)
        telegram.send(build_search_item_caption(item, series_seasons=series_seasons), image, chat_ids=[chat_id])
        if item.get("Id") and _is_admin_private_chat(chat_id, True):
            telegram.send_search_admin_actions(chat_id, str(item["Id"]))
        telegram.send_search_again_action(chat_id)

    def _handle_telegram_message(message: dict[str, Any]) -> None:
        chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
        chat_id = str(chat.get("id") or "")
        user = message.get("from") if isinstance(message.get("from"), dict) else {}
        private_chat_id = str(user.get("id") or "")
        is_private_chat = chat.get("type") == "private"
        reply_to_message = message.get("reply_to_message") if isinstance(message.get("reply_to_message"), dict) else {}
        reply_text = str(reply_to_message.get("text") or "")
        is_search_reply = is_private_chat and reply_text.startswith("Escribe el titulo de")

        text = str(message.get("text") or "").strip()
        if not text:
            return

        command, _, arg = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        is_private_menu_command = is_private_chat and command in {"/start", "/menu", "/help", "/version"}
        is_private_search_command = is_private_chat and command == "/buscar"
        is_private_search_button = is_private_chat and text == PRIVATE_SEARCH_BUTTON_TEXT
        is_private_admin_button = is_private_chat and text in ADMIN_PRIVATE_BUTTON_TEXTS

        if not chat_id or (
            not _is_authorized_chat(chat_id)
            and not is_search_reply
            and not is_private_menu_command
            and not is_private_search_command
            and not is_private_search_button
            and not is_private_admin_button
        ):
            logging.warning("Telegram update ignored from unauthorized chat_id=%s", chat_id or "unknown")
            return

        if is_private_search_button:
            telegram.send_search_filter_menu(chat_id)
            return
        if is_private_admin_button:
            if not _is_admin_private_chat(chat_id, is_private_chat):
                logging.warning("Admin keyboard button rejected for non-admin/private chat_id=%s", chat_id)
                telegram.send_text("Este boton solo esta disponible en privado para administradores.", chat_ids=[chat_id])
                return
            if text == ADMIN_RESEND_MENU_BUTTON_TEXT:
                _open_resend_item_menu(chat_id)
                return
            if text == ADMIN_LATEST_BUTTON_TEXT:
                _send_latest_added(chat_id)
                return
            if text == ADMIN_RESEND_BY_ID_BUTTON_TEXT:
                telegram.send_text("Envia /reenvia ID_DE_EMBY para elegir destino.", chat_ids=[chat_id])
                return
            if text == ADMIN_DIAGNOSTICS_BUTTON_TEXT:
                _send_diagnostics(chat_id, is_private_chat)
                return
        if command in {"/start", "/menu"}:
            if is_private_chat:
                telegram.send_private_menu_help(chat_id, is_admin=_is_admin_private_chat(chat_id, is_private_chat))
                return
            telegram.send_search_menu(chat_id)
            return
        if command == "/help":
            _send_help(chat_id, is_private_chat)
            return
        if command == "/version":
            if not _is_admin_private_chat(chat_id, is_private_chat):
                logging.warning("Version command rejected for non-admin/private chat_id=%s", chat_id)
                telegram.send_text("Este comando solo esta disponible en privado para administradores.", chat_ids=[chat_id])
                return
            _send_version(chat_id)
            return
        if command == "/reload_menu":
            if not _is_admin_private_chat(chat_id, is_private_chat):
                logging.warning("Reload menu command rejected for non-admin/private chat_id=%s", chat_id)
                telegram.send_text("Este comando solo esta disponible en privado para administradores.", chat_ids=[chat_id])
                return
            _reload_bot_commands(chat_id)
            return
        if command == "/buscar":
            target_chat_id = chat_id if is_private_chat else private_chat_id
            if not target_chat_id:
                return
            if not arg.strip():
                telegram.send_search_filter_menu(target_chat_id)
                return
            _send_search_results(target_chat_id, arg, with_images=True)
            return
        if command in {"/reenviar", "/reenvia_menu"}:
            if not _is_admin_private_chat(chat_id, is_private_chat):
                logging.warning("Manual resend menu rejected for non-admin/private chat_id=%s", chat_id)
                telegram.send_text("Este comando solo esta disponible en privado para administradores.", chat_ids=[chat_id])
                return
            _open_resend_item_menu(chat_id)
            return
        if command in {"/reenviaultimo", "/lastadded"}:
            if not _is_admin_private_chat(chat_id, is_private_chat):
                logging.warning("Manual latest resend rejected for non-admin/private chat_id=%s", chat_id)
                telegram.send_text("Este comando solo esta disponible en privado para administradores.", chat_ids=[chat_id])
                return
            _send_latest_added(chat_id)
            return
        if command == "/reenvia":
            if not _is_admin_private_chat(chat_id, is_private_chat):
                logging.warning("Manual item resend rejected for non-admin/private chat_id=%s", chat_id)
                telegram.send_text("Este comando solo esta disponible en privado para administradores.", chat_ids=[chat_id])
                return
            _send_item_by_id(chat_id, arg)
            return
        if command in {"/diagnostico", "/diagnostico_playback", "/estado"}:
            if not _is_authorized_chat(chat_id):
                logging.warning("Diagnostics rejected for unauthorized chat_id=%s", chat_id)
                return
            _send_diagnostics(chat_id, is_private_chat)
            return

        if is_search_reply:
            _send_search_results(
                chat_id,
                text,
                with_images=chat.get("type") == "private",
                mode=_search_mode_from_prompt(reply_text),
            )
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

        is_search_selection = chat.get("type") == "private" and callback_data.startswith("search:item:")
        is_search_flow = chat.get("type") == "private" and (
            callback_data.startswith("search:mode:") or callback_data == "search:again"
        )
        is_resend_selection = chat.get("type") == "private" and callback_data.startswith("resend:")
        is_private_selection = is_search_selection or is_search_flow or is_resend_selection
        if not chat_id or (not _is_authorized_chat(chat_id) and not is_private_selection):
            if callback_id:
                telegram.answer_callback_query(callback_id)
            logging.warning("Telegram callback ignored from unauthorized chat_id=%s", chat_id or "unknown")
            return

        if is_resend_selection and not _is_admin_private_chat(chat_id, chat.get("type") == "private"):
            if callback_id:
                telegram.answer_callback_query(callback_id, "No autorizado", show_alert=True)
            logging.warning("Resend callback rejected for non-admin/private chat_id=%s", chat_id)
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

        if callback_data.startswith("search:mode:"):
            mode = callback_data.removeprefix("search:mode:")
            if mode not in search_mode_item_types:
                mode = "all"
            if callback_id:
                telegram.answer_callback_query(callback_id)
            telegram.request_search_query(chat_id, mode=mode)
            return

        if callback_data == "search:again":
            if callback_id:
                telegram.answer_callback_query(callback_id)
            telegram.send_search_filter_menu(chat_id)
            return

        if callback_data.startswith("resend:item:"):
            item_id = callback_data.removeprefix("resend:item:")
            if callback_id:
                telegram.answer_callback_query(callback_id, "Elige destino...")
            _open_resend_target_menu(chat_id, item_id)
            return

        if callback_data.startswith("resend:to:"):
            remainder = callback_data.removeprefix("resend:to:")
            target_key, _, item_id = remainder.partition(":")
            if not target_key or not item_id:
                if callback_id:
                    telegram.answer_callback_query(callback_id, "Seleccion no valida", show_alert=True)
                return
            target_chat_ids = _resolve_resend_targets(target_key, chat_id)
            if not target_chat_ids:
                if callback_id:
                    telegram.answer_callback_query(callback_id, "Destino no configurado", show_alert=True)
                return
            if callback_id:
                telegram.answer_callback_query(callback_id, "Reenviando...")
            try:
                item = emby.get_item_by_id(item_id)
            except Exception as exc:
                logging.error(
                    "Manual resend callback lookup failed item_id=%s error_type=%s error=%s",
                    item_id,
                    type(exc).__name__,
                    exc,
                )
                telegram.send_text("No he podido consultar ese contenido en Emby.", chat_ids=[chat_id])
                return
            if not item:
                telegram.send_text("No he encontrado ese contenido en Emby.", chat_ids=[chat_id])
                return
            _send_item_notification(chat_id, item, target_chat_ids=target_chat_ids)
            telegram.send_text(f"Reenviado a: {', '.join(target_chat_ids)}", chat_ids=[chat_id])
            return

        if callback_data == "search:start":
            if chat.get("type") == "private":
                if callback_id:
                    telegram.answer_callback_query(callback_id)
                telegram.send_search_filter_menu(chat_id)
                return
            if private_chat_id:
                telegram.send_search_filter_menu(private_chat_id)
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
        event_code = infer_activity_event_code(payload)
        payload_item = payload.get("Item") if isinstance(payload.get("Item"), dict) else {}
        logging.info(
            "Emby webhook received raw_event=%s normalized_event=%s item_id=%s item_type=%s",
            payload.get("Event") or "missing",
            event_code or "unknown",
            payload.get("ItemId") or payload_item.get("Id") or "unknown",
            payload_item.get("Type") or "unknown",
        )

        if settings.enable_playback_notifications and is_activity_payload(payload):
            logging.info("Processing Emby activity event normalized_event=%s", event_code or "unknown")
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
                logging.info("Playback notification sent to %s", ",".join(playback_targets))
                return "", 200
            logging.info("Activity event produced no caption normalized_event=%s", event_code or "unknown")
        elif is_activity_payload(payload):
            logging.info("Playback notifications disabled; skipping activity event")

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

            if not _should_send_library_event(item, item_id):
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
