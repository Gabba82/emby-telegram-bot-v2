"""Presentation-only Telegram chat names and aliases backed by the history SQLite file."""
from __future__ import annotations

from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ChatDirectory:
    def __init__(self, store, telegram, chat_ids, aliases=None, kinds=None):
        self.store = store
        self.telegram = telegram
        self.chat_ids = list(dict.fromkeys(str(value) for value in chat_ids if value))
        self.kinds = {str(key): str(value) for key, value in (kinds or {}).items()}
        with self.store.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS panel_chat_directory (
                chat_id TEXT PRIMARY KEY,
                telegram_name TEXT,
                alias TEXT,
                updated_at TEXT NOT NULL
            )""")
            for chat_id in self.chat_ids:
                db.execute("INSERT OR IGNORE INTO panel_chat_directory VALUES (?,?,?,?)",
                           (chat_id, None, None, _now()))
            for chat_id, alias in (aliases or {}).items():
                chat_id = str(chat_id)
                alias = self._clean_alias(alias)
                if chat_id in self.chat_ids and alias:
                    db.execute("UPDATE panel_chat_directory SET alias=COALESCE(alias,?),updated_at=? WHERE chat_id=?",
                               (alias, _now(), chat_id))

    @staticmethod
    def _clean_alias(value):
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("Alias inválido")
        alias = value.strip()
        if len(alias) > 80 or any(ord(char) < 32 for char in alias):
            raise ValueError("Alias inválido")
        return alias or None

    def refresh_names(self):
        for chat_id in self.chat_ids:
            try:
                name = str(self.telegram.validate_chat(chat_id)).strip()
            except Exception:
                continue
            if not name or name == chat_id:
                continue
            with self.store.connection() as db:
                db.execute("UPDATE panel_chat_directory SET telegram_name=?,updated_at=? WHERE chat_id=?",
                           (name[:120], _now(), chat_id))
        return self.list()

    def list(self):
        with self.store.connection() as db:
            rows = {row['chat_id']: dict(row) for row in db.execute(
                "SELECT chat_id,telegram_name,alias,updated_at FROM panel_chat_directory")}
        chats = []
        for chat_id in self.chat_ids:
            row = rows.get(chat_id, {})
            telegram_name = row.get('telegram_name') or None
            alias = row.get('alias') or None
            chats.append(dict(
                id=chat_id,
                label=alias or telegram_name or chat_id,
                telegram_name=telegram_name,
                alias=alias,
                kind=self.kinds.get(chat_id, 'channel'),
            ))
        return chats

    def set_alias(self, chat_id, alias):
        chat_id = str(chat_id)
        if chat_id not in self.chat_ids:
            raise ValueError("Chat desconocido")
        alias = self._clean_alias(alias)
        with self.store.connection() as db:
            db.execute("UPDATE panel_chat_directory SET alias=?,updated_at=? WHERE chat_id=?",
                       (alias if alias is not None else '', _now(), chat_id))
        return next(chat for chat in self.list() if chat['id'] == chat_id)
