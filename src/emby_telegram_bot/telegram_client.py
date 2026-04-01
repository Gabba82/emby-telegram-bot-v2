from __future__ import annotations

import asyncio
import io
import logging

from telegram import Bot
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown


def safe_markdown_v2(text: str) -> str:
    return escape_markdown(text, version=2)


class TelegramClient:
    def __init__(self, token: str, chat_ids: list[str]) -> None:
        self._token = token
        self._chat_ids = chat_ids

    def send(self, caption: str, image_bytes: bytes | None) -> None:
        formatted_caption = safe_markdown_v2(caption)
        try:
            asyncio.run(self._send_all(formatted_caption, image_bytes))
        except Exception as exc:
            logging.error("Telegram batch send failed error=%s", exc)

    async def _send_all(self, formatted_caption: str, image_bytes: bytes | None) -> None:
        async with Bot(token=self._token) as bot:
            for chat_id in self._chat_ids:
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
                    logging.error("Telegram send failed for chat_id=%s error=%s", chat_id, exc)
