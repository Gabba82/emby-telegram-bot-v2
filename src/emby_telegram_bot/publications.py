"""Publication use cases shared by automatic notifications and Telegram commands."""
from __future__ import annotations

import json
from collections.abc import Callable

from .deliveries import DeliveryStore
from .telegram_client import SendResult


class PublicationService:
    def __init__(self, store: DeliveryStore, telegram, image_loader: Callable) -> None:
        self.store, self.telegram, self.image_loader = store, telegram, image_loader

    def prepare(self, item, caption, targets, request_key, source, actor=""):
        return self.store.prepare(item, caption, targets, request_key, source, actor)

    def _send(self, rows: list[dict], caption: str, item: dict, action_key: str,
              *, retry=False, allow_uncertain=False, caption_for_rows=None) -> None:
        # One call per destination. Save each accepted result before starting the next.
        by_chat: dict[str, list[dict]] = {}
        for row in rows:
            by_chat.setdefault(row["chat_id"], []).append(row)
        for chat_id, group in by_chat.items():
            claimed = []
            for row in group:
                attempt = self.store.claim(row["id"], f"{action_key}:{row['id']}",
                                           retry=retry, allow_uncertain=allow_uncertain)
                if attempt is not None:
                    claimed.append((attempt, row))
            if not claimed:
                continue
            if caption_for_rows is not None:
                caption = caption_for_rows([row for _, row in claimed])
            for attempt, row in claimed:
                self.store.set_attempt_caption(attempt, caption)
            try:
                image = self.image_loader(item)
            except Exception:
                image = None  # Optional artwork must not prevent a text delivery.
            try:
                results = self.telegram.send(caption, image, chat_ids=[chat_id])
                result = next((r for r in (results or []) if r.chat_id == chat_id),
                              SendResult(chat_id, "uncertain", error_type="MissingSendResult"))
            except Exception as exc:
                result = SendResult(chat_id, "uncertain", error_type=type(exc).__name__)
            for attempt, row in claimed:
                self.store.finish(attempt, result.status, result.message_id, result.error_type)

    def publish(self, item, caption, targets, request_key, source="manual", actor=""):
        rows = self.prepare(item, caption, targets, request_key, source, actor)
        if rows:
            self._send(rows, rows[0]["caption"], json.loads(rows[0]["item_json"]), f"initial:{request_key}")
        return [self.store.get(row["id"]) for row in rows]

    def retry(self, delivery_id: int, action_key: str, *, allow_uncertain=False):
        row = self.store.get(delivery_id)
        self._send([row], row["caption"], json.loads(row["item_json"]), action_key,
                   retry=True, allow_uncertain=allow_uncertain)
        return self.store.get(delivery_id)

    def publish_episode_group(self, items, targets, key_for_item, caption_builder):
        # Each EpisodeId has its own ledger row even when several share one message.
        prepared = [(item, self.prepare(item, caption_builder([item]), targets,
                                       key_for_item(item), "automatic")) for item in items]
        for chat_id in dict.fromkeys(targets):
            pending_items, rows = [], []
            for item, deliveries in prepared:
                eligible = [r for r in deliveries if r["chat_id"] == chat_id and r["status"] == "pending"]
                if eligible:
                    pending_items.append(item)
                    rows.extend(eligible)
            if rows:
                # Serialized by the app's group lock; still atomically claimed in SQLite.
                self._send(rows, caption_builder(pending_items), pending_items[-1], "episode-group",
                           caption_for_rows=lambda claimed: caption_builder([json.loads(r["item_json"]) for r in claimed]))
