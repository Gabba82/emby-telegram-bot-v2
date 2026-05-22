from __future__ import annotations

import asyncio
import io
import logging
from typing import Any

from telegram import Bot, BotCommand, BotCommandScopeChat, ForceReply, InlineKeyboardButton, InlineKeyboardMarkup
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
        self.send_text(f"Destino para reenviar '{item_name}':", chat_ids=[chat_id], reply_markup=keyboard)

    def send_search_admin_actions(self, chat_id: str, item_id: str) -> None:
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("Reenviar esta ficha", callback_data=f"resend:item:{item_id}")]]
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
            BotCommand("diagnostico", "Validar configuracion"),
            BotCommand("estado", "Ver estado del bot"),
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
