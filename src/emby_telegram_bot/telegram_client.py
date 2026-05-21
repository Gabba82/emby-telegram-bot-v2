from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

from telegram import Bot, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown


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


class TelegramClient:
    def __init__(self, token: str, chat_ids: list[str]) -> None:
        self._token = token
        self._chat_ids = chat_ids

    def send(self, caption: str, image_bytes: bytes | None, chat_ids: list[str] | None = None) -> None:
        formatted_caption = safe_markdown_v2(caption)
        targets = chat_ids or self._chat_ids
        if not targets:
            logging.warning("Telegram send skipped because no target chat IDs were provided")
            return
        try:
            asyncio.run(self._send_all(formatted_caption, image_bytes, targets))
        except Exception as exc:
            logging.error("Telegram batch send failed error_type=%s error=%s", type(exc).__name__, exc)

    def validate_credentials(self) -> str:
        try:
            return asyncio.run(self._get_bot_username())
        except Exception as exc:
            logging.error("Telegram credential validation failed error_type=%s error=%s", type(exc).__name__, exc)
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
        self.send_text(f"Destino para reenviar '{item_name}':", chat_ids=[chat_id], reply_markup=keyboard)

    def send_private_search_keyboard(self, chat_id: str, is_admin: bool = False) -> None:
        buttons = [[PRIVATE_SEARCH_BUTTON_TEXT]]
        if is_admin:
            buttons.extend(
                [
                    [ADMIN_RESEND_MENU_BUTTON_TEXT, ADMIN_LATEST_BUTTON_TEXT],
                    [ADMIN_RESEND_BY_ID_BUTTON_TEXT, ADMIN_DIAGNOSTICS_BUTTON_TEXT],
                ]
            )
        keyboard = ReplyKeyboardMarkup(
            buttons,
            resize_keyboard=True,
            is_persistent=True,
        )
        text = "Menu admin activado." if is_admin else "Menu de busqueda activado."
        self.send_text(text, chat_ids=[chat_id], reply_markup=keyboard)

    def request_search_query(self, chat_id: str) -> None:
        self.send_text(
            "Escribe el titulo de la pelicula o serie que quieres buscar.",
            chat_ids=[chat_id],
            reply_markup=ForceReply(selective=True),
        )

    def answer_callback_query(self, callback_query_id: str, text: str = "", show_alert: bool = False) -> None:
        try:
            asyncio.run(self._answer_callback_query(callback_query_id, text, show_alert=show_alert))
        except Exception as exc:
            logging.error("Telegram callback answer failed error=%s", exc)

    async def _send_all(self, formatted_caption: str, image_bytes: bytes | None, targets: list[str]) -> None:
        async with Bot(token=self._token) as bot:
            for chat_id in targets:
                try:
                    if image_bytes:
                        await bot.send_photo(
                            chat_id=chat_id,
                            photo=io.BytesIO(image_bytes),
                            caption=formatted_caption,
                            parse_mode=ParseMode.MARKDOWN_V2,
                        )
                    else:
                        await bot.send_message(
                            chat_id=chat_id,
                            text=formatted_caption,
                            parse_mode=ParseMode.MARKDOWN_V2,
                        )
                except Exception as exc:
                    logging.error(
                        "Telegram send failed for chat_id=%s error_type=%s error=%s",
                        chat_id,
                        type(exc).__name__,
                        exc,
                    )

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

    async def _answer_callback_query(self, callback_query_id: str, text: str, show_alert: bool = False) -> None:
        async with Bot(token=self._token) as bot:
            await bot.answer_callback_query(
                callback_query_id=callback_query_id,
                text=text or None,
                show_alert=show_alert,
            )
