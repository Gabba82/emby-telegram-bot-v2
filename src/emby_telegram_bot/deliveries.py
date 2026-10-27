"""Small durable ledger. No network calls, credentials, or automatic retries.

An attempt becomes uncertain *before* external I/O. A killed process therefore
cannot leave a potentially accepted message looking safe to retry automatically.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS_LABELS = {
    "sent": "enviado", "failed": "fallido", "pending": "pendiente",
    "uncertain": "incierto", "history_unknown": "historial desconocido",
}


class DecisionRequired(ValueError):
    """The caller must explicitly acknowledge possible duplicate delivery."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DeliveryStore:
    def __init__(self, path: str) -> None:
        if not path.strip() or path == ":memory:":
            raise ValueError("HISTORY_DB_PATH must name a persistent SQLite file")
        self.path = str(Path(path).expanduser().resolve())
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            if db.execute("PRAGMA user_version").fetchone()[0] not in (0, 1):
                raise ValueError("Unsupported history schema version; use a compatible release")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS operations (
                    id INTEGER PRIMARY KEY,
                    request_key TEXT NOT NULL UNIQUE,
                    item_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    item_json TEXT NOT NULL,
                    caption TEXT NOT NULL,
                    source TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS deliveries (
                    id INTEGER PRIMARY KEY,
                    operation_id INTEGER NOT NULL REFERENCES operations(id),
                    chat_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','uncertain','sent','failed')),
                    message_id INTEGER,
                    error_type TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(operation_id, chat_id)
                );
                CREATE TABLE IF NOT EXISTS attempts (
                    id INTEGER PRIMARY KEY,
                    delivery_id INTEGER NOT NULL REFERENCES deliveries(id),
                    request_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    message_id INTEGER,
                    error_type TEXT,
                    explicit_uncertain INTEGER NOT NULL,
                    caption TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS deliveries_status ON deliveries(status, id DESC);
                CREATE INDEX IF NOT EXISTS operations_item ON operations(item_id);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def prepare(self, item: dict[str, Any], caption: str, targets: list[str],
                request_key: str, source: str, actor: str = "") -> list[dict]:
        # Whitelist metadata. Never persist the full webhook or server URLs/keys.
        fields = ("Id", "Name", "Type", "SeriesId", "SeriesName", "ParentId",
                  "ParentIndexNumber", "IndexNumber")
        safe_item = {key: item[key] for key in fields if key in item}
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            inserted = db.execute("""INSERT OR IGNORE INTO operations
                (request_key,item_id,title,item_json,caption,source,actor,created_at)
                VALUES (?,?,?,?,?,?,?,?)""", (
                    request_key, str(item.get("Id") or ""), str(item.get("Name") or "Contenido"),
                    json.dumps(safe_item, ensure_ascii=False), caption, source, actor, now(),
                )).rowcount
            operation_id = db.execute("SELECT id FROM operations WHERE request_key=?", (request_key,)).fetchone()[0]
            if inserted:
                for chat_id in dict.fromkeys(str(c) for c in targets if c):
                    db.execute("""INSERT INTO deliveries
                        (operation_id,chat_id,status,updated_at) VALUES (?,?,'pending',?)""",
                        (operation_id, chat_id, now()))
            return list(reversed(self._rows(db, "d.operation_id=?", (operation_id,))))

    @staticmethod
    def _rows(db, where: str = "1", params: tuple = (), tail: str = "") -> list[dict]:
        return [dict(row) for row in db.execute(f"""SELECT d.*, o.item_id, o.title,
            o.item_json, o.caption, o.source, o.actor, o.created_at,
            (SELECT count(*) FROM attempts a WHERE a.delivery_id=d.id) AS attempt_count
            FROM deliveries d JOIN operations o ON o.id=d.operation_id
            WHERE {where} ORDER BY d.id DESC {tail}""", params)]

    def get(self, delivery_id: int) -> dict:
        with self.connection() as db:
            rows = self._rows(db, "d.id=?", (delivery_id,))
            if not rows:
                raise ValueError("Entrega no encontrada")
            return rows[0]

    def claim(self, delivery_id: int, request_key: str, *, retry: bool = False,
              allow_uncertain: bool = False) -> int | None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM deliveries WHERE id=?", (delivery_id,)).fetchone()
            if row is None:
                raise ValueError("Entrega no encontrada")
            if db.execute("SELECT 1 FROM attempts WHERE request_key=?", (request_key,)).fetchone():
                return None  # Same action replayed: never another external call.
            status = row[0]
            if status == "sent":
                return None
            if status == "uncertain" and not (retry and allow_uncertain):
                if retry:
                    raise DecisionRequired("Resultado incierto: puede duplicar. Usa confirmar-incierto expresamente.")
                return None
            if status == "failed" and not retry:
                return None
            cursor = db.execute("""INSERT INTO attempts
                (delivery_id,request_key,status,explicit_uncertain,created_at)
                VALUES (?,?,'uncertain',?,?)""",
                (delivery_id, request_key, int(allow_uncertain), now()))
            db.execute("UPDATE deliveries SET status='uncertain', error_type=NULL, updated_at=? WHERE id=?",
                       (now(), delivery_id))
            return cursor.lastrowid

    def finish(self, attempt_id: int, status: str, message_id: int | None = None,
               error_type: str | None = None) -> None:
        if status not in {"sent", "failed", "uncertain"}:
            raise ValueError("Invalid delivery result")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            attempt = db.execute("SELECT * FROM attempts WHERE id=?", (attempt_id,)).fetchone()
            if attempt is None or attempt["finished_at"]:
                raise ValueError("Attempt missing or already completed")
            # Error codes only, never raw exception strings with token-bearing URLs.
            error_type = (error_type or "")[:80] or None
            db.execute("""UPDATE attempts SET status=?,message_id=?,error_type=?,finished_at=?
                WHERE id=?""", (status, message_id, error_type, now(), attempt_id))
            # An explicitly authorized uncertain retry can overlap an old response.
            # A late failure must never erase an acceptance already recorded.
            sent = db.execute("""SELECT message_id FROM attempts WHERE delivery_id=?
                AND status='sent' ORDER BY id DESC LIMIT 1""", (attempt["delivery_id"],)).fetchone()
            if sent is not None:
                status, message_id, error_type = "sent", sent[0], None
            db.execute("""UPDATE deliveries SET status=?,message_id=?,error_type=?,updated_at=?
                WHERE id=?""", (status, message_id, error_type, now(), attempt["delivery_id"]))

    def set_attempt_caption(self, attempt_id: int, caption: str) -> None:
        """Freeze the actual payload before I/O, including grouped episode captions."""
        with self.connection() as db:
            changed = db.execute("UPDATE attempts SET caption=? WHERE id=? AND finished_at IS NULL",
                                 (caption, attempt_id)).rowcount
            if changed != 1:
                raise ValueError("Attempt missing or already completed")

    def history(self, page: int = 1, status: str | None = None, page_size: int = 5) -> tuple[list[dict], int]:
        if page < 1 or page_size < 1 or page_size > 20:
            raise ValueError("Pagina no valida")
        if status is not None and status not in {"sent", "failed", "pending", "uncertain"}:
            raise ValueError("Estado no valido")
        where, params = ("d.status=?", (status,)) if status else ("1", ())
        with self.connection() as db:
            total = db.execute(f"SELECT count(*) FROM deliveries d WHERE {where}", params).fetchone()[0]
            rows = self._rows(db, where, params + (page_size, (page - 1) * page_size), "LIMIT ? OFFSET ?")
            return rows, total

    def item_status(self, item_id: str, chat_id: str) -> str:
        with self.connection() as db:
            rows = self._rows(db, "o.item_id=? AND d.chat_id=?", (item_id, chat_id))
        # A later voluntary resend failure does not erase a confirmed publication.
        if any(row["status"] == "sent" for row in rows):
            return "sent"
        return rows[0]["status"] if rows else "history_unknown"

    def attempts(self, delivery_id: int) -> list[dict]:
        with self.connection() as db:
            return [dict(row) for row in db.execute("SELECT * FROM attempts WHERE delivery_id=? ORDER BY id", (delivery_id,))]
