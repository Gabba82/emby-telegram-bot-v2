from __future__ import annotations

import asyncio
import html
import io
import logging
import time
from dataclasses import dataclass
from typing import Any

from telegram import Bot, BotCommand, BotCommandScopeChat, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from telegram.error import BadRequest, Forbidden, InvalidToken, RetryAfter, ChatMigrated

from .formatting import EXPANDABLE_SECTION_END, EXPANDABLE_SECTION_START


PRIVATE_SEARCH_BUTTON_TEXT = "\U0001f50e Buscar pelicula o serie"
ADMIN_RESEND_MENU_BUTTON_TEXT = "Reenviar reciente"
ADMIN_LATEST_BUTTON_TEXT = "Reenviar ultimo"
ADMIN_RESEND_BY_ID_BUTTON_TEXT = "Reenviar por ID"
ADMIN_DIAGNOSTICS_BUTTON_TEXT = "Diagnostico"
ADMIN_PRIVATE_BUTTON_TEXTS = {
    ADMIN_RESEND_MENU_BUTTON_TEXT,
    ADMIN_LATEST_BUTTON_TEXT,
    ADMIN_RESEND_BY_ID_BUTTON_TEXT,
    ADMIN_DIAGNOSTICS_BUTTON_TEXT,
}


def safe_markdown_v2(text: str) -> str:
    return escape_markdown(text, version=2)


def _format_html_caption(text: str) -> str:
    output = []
    remaining = text
    while EXPANDABLE_SECTION_START in remaining:
        before, _, rest = remaining.partition(EXPANDABLE_SECTION_START)
        expandable, separator, remaining = rest.partition(EXPANDABLE_SECTION_END)
        output.append(html.escape(before, quote=False))
        if separator:
            output.append(f"<blockquote expandable>{html.escape(expandable, quote=False)}</blockquote>")
        else:
            output.append(html.escape(expandable, quote=False))
            remaining = ""
    output.append(html.escape(remaining, quote=False))
    return "".join(output)


def format_caption_for_telegram(caption: str) -> tuple[str, str]:
    if EXPANDABLE_SECTION_START in caption:
        return _format_html_caption(caption), ParseMode.HTML
    return safe_markdown_v2(caption), ParseMode.MARKDOWN_V2


@dataclass(frozen=True)
class SendResult:
    chat_id: str
    status: str
    message_id: int | None = None
    error_type: str | None = None


def error_result(chat_id: str, exc: Exception) -> SendResult:
    # A server rejection is known not delivered; ambiguous failures stay uncertain.
    status = "failed" if isinstance(exc, (BadRequest, Forbidden, InvalidToken, RetryAfter, ChatMigrated)) else "uncertain"
    return SendResult(chat_id, status, error_type=type(exc).__name__)


class TelegramClient:
    def __init__(self, token: str, chat_ids: list[str]) -> None:
        self._token = token
        self._chat_ids = chat_ids
        self._chat_labels: dict[str, str] = {}
        self._chat_label_failures: dict[str, tuple[float, Exception]] = {}

    def send(self, caption: str, image_bytes: bytes | None, chat_ids: list[str] | None = None) -> list[SendResult]:
        targets = list(dict.fromkeys(chat_ids if chat_ids is not None else self._chat_ids))
        if not targets:
            return []
        try:
            formatted_caption, parse_mode = format_caption_for_telegram(caption)
            return asyncio.run(self._send_all(formatted_caption, parse_mode, image_bytes, targets))
        except Exception as exc:
            logging.error("Telegram batch send failed error_type=%s", type(exc).__name__)
            return [error_result(chat_id, exc) for chat_id in targets]

    def validate_credentials(self) -> str:
        try:
            return asyncio.run(self._get_bot_username())
        except Exception as exc:
            logging.error("Telegram credential validation failed error_type=%s error=%s", type(exc).__name__, exc)
            raise

    def validate_chat(self, chat_id: str) -> str:
        if chat_id in self._chat_labels:
            return self._chat_labels[chat_id]
        failed = self._chat_label_failures.get(chat_id)
        if failed and time.monotonic() - failed[0] < 60:
            raise RuntimeError("Telegram chat lookup recently failed") from failed[1]
        try:
            label = asyncio.run(self._get_chat_label(chat_id))
            self._chat_labels[chat_id] = label
            self._chat_label_failures.pop(chat_id, None)
            return label
        except Exception as exc:
            self._chat_label_failures[chat_id] = (time.monotonic(), exc)
            logging.error(
                "Telegram chat validation failed chat_id=%s error_type=%s error=%s",
                chat_id,
                type(exc).__name__,
                exc,
            )
            raise

    def send_text(
        self,
        text: str,
        chat_ids: list[str] | None = None,
        reply_markup: Any | None = None,
    ) -> None:
        formatted_text = safe_markdown_v2(text)
        targets = chat_ids or self._chat_ids
        if not targets:
            logging.warning("Telegram text send skipped because no target chat IDs were provided")
            return
        try:
            asyncio.run(self._send_text_all(formatted_text, targets, reply_markup=reply_markup))
        except Exception as exc:
            logging.error("Telegram text batch send failed error_type=%s error=%s", type(exc).__name__, exc)

    def send_search_menu(self, chat_id: str) -> None:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔎 Buscar por privado", callback_data="search:start")]]
        )
        self.send_text("Que quieres hacer?", chat_ids=[chat_id], reply_markup=keyboard)

    def send_search_filter_menu(self, chat_id: str) -> None:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("Todo", callback_data="search:mode:all"),
                    InlineKeyboardButton("Peliculas", callback_data="search:mode:movies"),
                    InlineKeyboardButton("Series", callback_data="search:mode:series"),
                ]
            ]
        )
        self.send_text("Que quieres buscar?", chat_ids=[chat_id], reply_markup=keyboard)

    def send_search_selection_menu(self, chat_id: str, query: str, items: list[dict[str, Any]]) -> None:
        buttons = []
        for index, item in enumerate(items[:10], start=1):
            item_id = str(item.get("Id") or "")
            if not item_id:
                continue
            item_type = item.get("Type")
            label_type = "Peli" if item_type == "Movie" else "Serie" if item_type == "Series" else "Item"
            name = str(item.get("Name") or "Sin titulo")
            year = item.get("ProductionYear")
            suffix = f" ({year})" if year else ""
            label = f"{index}. {label_type}: {name}{suffix}"
            buttons.append([InlineKeyboardButton(label[:64], callback_data=f"search:item:{item_id}")])

        if not buttons:
            self.send_text("No he podido preparar la lista de resultados.", chat_ids=[chat_id])
            return

        keyboard = InlineKeyboardMarkup(buttons)
        self.send_text(
            f"He encontrado varios resultados para '{query}'. Elige uno:",
            chat_ids=[chat_id],
            reply_markup=keyboard,
        )

    def send_resend_item_menu(self, chat_id: str, items: list[dict[str, Any]]) -> None:
        buttons = []
        for index, item in enumerate(items[:10], start=1):
            item_id = str(item.get("Id") or "")
            if not item_id:
                continue
            item_type = item.get("Type")
            label_type = "Peli" if item_type == "Movie" else "Serie" if item_type == "Series" else "Episodio"
            name = str(item.get("Name") or item.get("SeriesName") or "Sin titulo")
            year = item.get("ProductionYear")
            suffix = f" ({year})" if year else ""
            label = f"{index}. {label_type}: {name}{suffix}"
            buttons.append([InlineKeyboardButton(label[:64], callback_data=f"resend:item:{item_id}")])

        if not buttons:
            self.send_text("No he encontrado contenido reciente para reenviar.", chat_ids=[chat_id])
            return

        keyboard = InlineKeyboardMarkup(buttons)
        self.send_text("Elige que contenido quieres reenviar:", chat_ids=[chat_id], reply_markup=keyboard)

    def send_resend_target_menu(
        self,
        chat_id: str,
        item_id: str,
        item_name: str,
        targets: list[tuple[str, str, list[str]]],
    ) -> None:
        buttons = []
        for target_key, label, chat_ids in targets:
            if not chat_ids:
                continue
            buttons.append([InlineKeyboardButton(label[:64], callback_data=f"resend:to:{target_key}:{item_id}")])

        if not buttons:
            self.send_text("No hay destinos configurados para reenviar.", chat_ids=[chat_id])
            return

        keyboard = InlineKeyboardMarkup(buttons)
        self.send_text(
            f"Destino para publicar de nuevo '{item_name}':\nPuede duplicar una publicacion anterior. "
            "Para recuperar una entrega usa /reintentar NUMERO (ver /historial).",
            chat_ids=[chat_id], reply_markup=keyboard,
        )

    def send_search_admin_actions(self, chat_id: str, item_id: str) -> None:
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("Reenviar al canal", callback_data=f"resend:to:chat:{item_id}")],
                [InlineKeyboardButton("Elegir destino", callback_data=f"resend:item:{item_id}")],
            ]
        )
        self.send_text("Acciones admin para esta ficha:", chat_ids=[chat_id], reply_markup=keyboard)

    def send_search_again_action(self, chat_id: str) -> None:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Buscar otra vez", callback_data="search:again")]]
        )
        self.send_text("Quieres hacer otra busqueda?", chat_ids=[chat_id], reply_markup=keyboard)

    def send_private_menu_help(self, chat_id: str, is_admin: bool = False) -> None:
        text = "Menu admin activado." if is_admin else "Menu de busqueda activado."
        self.send_text(f"{text} Abre el menu de comandos junto al campo de escritura.", chat_ids=[chat_id])

    def request_search_query(self, chat_id: str, mode: str = "all") -> None:
        mode_label = {
            "movies": "peliculas",
            "series": "series",
        }.get(mode, "peliculas o series")
        self.send_text(
            f"Escribe el titulo de {mode_label} que quieres buscar.",
            chat_ids=[chat_id],
            reply_markup=ForceReply(selective=True),
        )

    def configure_bot_commands(self, admin_chat_ids: list[str]) -> None:
        try:
            asyncio.run(self._configure_bot_commands(admin_chat_ids))
        except Exception as exc:
            logging.error("Telegram command menu configuration failed error_type=%s error=%s", type(exc).__name__, exc)

    def answer_callback_query(self, callback_query_id: str, text: str = "", show_alert: bool = False) -> None:
        try:
            asyncio.run(self._answer_callback_query(callback_query_id, text, show_alert=show_alert))
        except Exception as exc:
            logging.error("Telegram callback answer failed error=%s", exc)

    async def _send_all(self, formatted_caption: str, parse_mode: str,
                        image_bytes: bytes | None, targets: list[str]) -> list[SendResult]:
        results = []
        try:
            async with Bot(token=self._token) as bot:
                for chat_id in targets:
                    try:
                        if image_bytes:
                            message = await bot.send_photo(chat_id=chat_id, photo=io.BytesIO(image_bytes),
                                                           caption=formatted_caption, parse_mode=parse_mode)
                        else:
                            message = await bot.send_message(chat_id=chat_id, text=formatted_caption,
                                                             parse_mode=parse_mode)
                        if getattr(message, "message_id", None) is None:
                            results.append(SendResult(chat_id, "uncertain", error_type="MissingMessageId"))
                        else:
                            results.append(SendResult(chat_id, "sent", message_id=message.message_id))
                    except Exception as exc:
                        results.append(error_result(chat_id, exc))
                        logging.error("Telegram send failed chat_id=%s error_type=%s", chat_id, type(exc).__name__)
        except Exception as exc:
            # Preserve earlier accepted messages even if SDK setup/shutdown fails.
            completed = {r.chat_id for r in results}
            results.extend(error_result(cid, exc) for cid in targets if cid not in completed)
            logging.error("Telegram transport failed error_type=%s", type(exc).__name__)
        return results

    async def _send_text_all(
        self,
        formatted_text: str,
        targets: list[str],
        reply_markup: Any | None = None,
    ) -> None:
        async with Bot(token=self._token) as bot:
            for chat_id in targets:
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text=formatted_text,
                        parse_mode=ParseMode.MARKDOWN_V2,
                        reply_markup=reply_markup,
                    )
                except Exception as exc:
                    logging.error(
                        "Telegram text send failed for chat_id=%s error_type=%s error=%s",
                        chat_id,
                        type(exc).__name__,
                        exc,
                    )

    async def _get_bot_username(self) -> str:
        async with Bot(token=self._token) as bot:
            me = await bot.get_me()
            return f"@{me.username}" if me.username else str(me.id)

    async def _get_chat_label(self, chat_id: str) -> str:
        async with Bot(token=self._token) as bot:
            chat = await bot.get_chat(chat_id=chat_id)
            title = getattr(chat, "title", None) or getattr(chat, "username", None) or getattr(chat, "first_name", None)
            return str(title or chat.id)

    async def _configure_bot_commands(self, admin_chat_ids: list[str]) -> None:
        user_commands = [
            BotCommand("buscar", "Buscar pelicula o serie"),
            BotCommand("help", "Ver ayuda"),
            BotCommand("menu", "Mostrar opciones del bot"),
        ]
        admin_commands = [
            *user_commands,
            BotCommand("reenviar", "Reenviar contenido reciente"),
            BotCommand("reenviaultimo", "Reenviar ultimo contenido"),
            BotCommand("reenvia", "Reenviar por ID de Emby"),
            BotCommand("historial", "Historial persistente de entregas"),
            BotCommand("reintentar", "Reintentar una entrega por su numero"),
            BotCommand("diagnostico", "Validar configuracion"),
            BotCommand("version", "Ver version desplegada"),
            BotCommand("reload_menu", "Recargar menu de comandos"),
        ]
        async with Bot(token=self._token) as bot:
            await bot.set_my_commands(user_commands)
            for chat_id in admin_chat_ids:
                if chat_id:
                    await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=chat_id))

    async def _answer_callback_query(self, callback_query_id: str, text: str, show_alert: bool = False) -> None:
        async with Bot(token=self._token) as bot:
            await bot.answer_callback_query(
                callback_query_id=callback_query_id,
                text=text or None,
                show_alert=show_alert,
            )
