import json
import socket
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram.error import Forbidden, TimedOut, RetryAfter, BadRequest

from emby_telegram_bot.config import Settings
from emby_telegram_bot.deliveries import DeliveryStore, DecisionRequired
from emby_telegram_bot.publications import PublicationService
from emby_telegram_bot.telegram_client import TelegramClient, SendResult
from emby_telegram_bot.webhook import create_app
from test_webhook import _settings, _FakeEmbyClient, _FakeTelegramClient


ITEM = {"Id": "old-123", "Type": "Movie", "Name": "Arrival"}


class Sender:
    def __init__(self, store):
        self.store, self.calls, self.outcomes = store, [], {}

    def send(self, caption, image, chat_ids=None):
        chat = chat_ids[0]
        rows, total = self.store.history()
        # Intent is committed and observable to a different connection before I/O.
        assert any(r["chat_id"] == chat and r["status"] == "uncertain" for r in rows)
        self.calls.append(chat)
        outcome = self.outcomes.get(chat, "sent")
        if isinstance(outcome, BaseException):
            raise outcome
        return [SendResult(chat, outcome, message_id=123 if outcome == "sent" else None,
                           error_type=None if outcome == "sent" else "SimulatedRejection")]


@pytest.fixture
def service(tmp_path):
    store = DeliveryStore(str(tmp_path / "history.sqlite3"))
    sender = Sender(store)
    return PublicationService(store, sender, lambda item: None), store, sender


def test_partial_result_and_retry_only_failed_preserves_attempts(service):
    svc, store, sender = service
    sender.outcomes["b"] = "failed"
    rows = svc.publish(ITEM, "caption", ["a", "b", "a"], "operation-1")
    by_chat = {r["chat_id"]: r for r in rows}
    assert by_chat["a"]["status"] == "sent"
    assert by_chat["a"]["message_id"] == 123
    assert by_chat["b"]["status"] == "failed"
    sender.outcomes.clear()
    svc.retry(by_chat["a"]["id"], "retry-a")
    svc.retry(by_chat["b"]["id"], "retry-b")
    assert sender.calls.count("a") == 1
    assert sender.calls.count("b") == 2
    assert [a["status"] for a in store.attempts(by_chat["b"]["id"])] == ["failed", "sent"]


def test_uncertain_requires_explicit_decision_and_replayed_decision_does_not_send(service):
    svc, store, sender = service
    sender.outcomes["a"] = TimeoutError("https://fake.invalid/?api_key=SECRET")
    row = svc.publish(ITEM, "caption", ["a"], "uncertain-op")[0]
    assert row["status"] == "uncertain"
    assert "SECRET" not in json.dumps(store.history())
    with pytest.raises(DecisionRequired):
        svc.retry(row["id"], "attempt-without-decision")
    sender.outcomes["a"] = "uncertain"
    svc.retry(row["id"], "confirmed-decision", allow_uncertain=True)
    svc.retry(row["id"], "confirmed-decision", allow_uncertain=True)
    assert sender.calls == ["a", "a"]
    assert store.attempts(row["id"])[-1]["explicit_uncertain"] == 1


def test_reopening_file_preserves_sent_pending_and_unknown(service):
    svc, store, sender = service
    row = svc.publish(ITEM, "caption", ["a"], "sent-op")[0]
    pending = svc.prepare({**ITEM, "Id": "pending"}, "caption", ["b"], "pending-op", "automatic")[0]
    fresh = DeliveryStore(store.path)
    assert fresh.get(row["id"])["message_id"] == 123
    assert fresh.get(pending["id"])["status"] == "pending"
    assert fresh.item_status(ITEM["Id"], "a") == "sent"
    assert fresh.item_status("not-in-ledger", "a") == "history_unknown"
    assert fresh.item_status(ITEM["Id"], "new-channel") == "history_unknown"


def test_process_exit_after_claim_leaves_uncertain_and_no_auto_retry(service):
    svc, store, sender = service
    row = svc.prepare(ITEM, "caption", ["a"], "crash-op", "automatic")[0]
    source = str(Path(__file__).resolve().parents[1] / "src")
    program = "import sys,os; sys.path.insert(0,sys.argv[1]); from emby_telegram_bot.deliveries import DeliveryStore; s=DeliveryStore(sys.argv[2]); s.claim(int(sys.argv[3]),'crash-attempt'); os._exit(9)"
    result = subprocess.run([sys.executable, "-B", "-c", program, source, store.path, str(row["id"])],
                            check=False, capture_output=True)
    assert result.returncode == 9
    assert DeliveryStore(store.path).get(row["id"])["status"] == "uncertain"
    svc.publish(ITEM, "caption", ["a"], "crash-op", "automatic")
    assert sender.calls == []


def test_repeated_operation_and_concurrent_callbacks_are_idempotent(service):
    svc, store, sender = service
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: svc.publish(ITEM, "caption", ["a"], "same-operation"), range(4)))
    assert sender.calls == ["a"]
    assert store.history()[1] == 1
    # A new voluntary publication has a different operation identity.
    svc.publish(ITEM, "caption", ["a"], "new-voluntary-operation")
    assert sender.calls == ["a", "a"]


def test_resend_failure_does_not_erase_previous_success(service):
    svc, store, sender = service
    svc.publish(ITEM, "caption", ["a"], "first")
    sender.outcomes["a"] = "failed"
    svc.publish(ITEM, "caption", ["a"], "voluntary-resend")
    assert store.history()[0][0]["status"] == "failed"
    assert store.item_status(ITEM["Id"], "a") == "sent"


def test_database_prepare_failure_sends_nothing(service, monkeypatch):
    svc, store, sender = service
    def fail(*args, **kwargs):
        raise sqlite3.OperationalError("readonly database")
    monkeypatch.setattr(store, "prepare", fail)
    with pytest.raises(sqlite3.OperationalError):
        svc.publish(ITEM, "caption", ["a"], "no-storage")
    assert not sender.calls


def test_result_commit_failure_remains_uncertain(service, monkeypatch):
    svc, store, sender = service
    def fail(*args, **kwargs): raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(store, "finish", fail)
    with pytest.raises(sqlite3.OperationalError):
        svc.publish(ITEM, "caption", ["a"], "lost-result")
    assert store.history()[0][0]["status"] == "uncertain"
    assert sender.calls == ["a"]


@pytest.mark.parametrize("error,status", [(Forbidden("fake"), "failed"), (BadRequest("fake"), "failed"),
                                          (RetryAfter(3), "failed"), (TimedOut(), "uncertain")])
def test_real_client_reports_individual_results_without_leaking_errors(monkeypatch, error, status):
    class Bot:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def send_message(self, **kwargs):
            if kwargs["chat_id"] == "b": raise error
            return SimpleNamespace(message_id=77)
        send_photo = send_message
    monkeypatch.setattr("emby_telegram_bot.telegram_client.Bot", Bot)
    results = TelegramClient("fake", ["a", "b", "a"]).send("caption", None)
    assert [(r.chat_id, r.status) for r in results] == [("a", "sent"), ("b", status)]
    assert results[0].message_id == 77
    assert results[1].error_type == type(error).__name__


class WebSender(_FakeTelegramClient):
    failure = False
    def send(self, caption, image_bytes, chat_ids=None):
        super().send(caption, image_bytes, chat_ids)
        return [SendResult(cid, "failed" if self.failure else "sent", None if self.failure else 77,
                           "Forbidden" if self.failure else None) for cid in chat_ids]


@pytest.fixture
def web(monkeypatch, tmp_path):
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", WebSender)
    settings = replace(_settings(), history_db_path=str(tmp_path / "web.sqlite3"))
    app = create_app(settings)
    return app, app.test_client(), _FakeTelegramClient.latest


def command(client, text, chat_id=42, chat_type="private", update=1):
    return client.post("/telegramhook", json={"update_id": update,
        "message": {"chat": {"id": chat_id, "type": chat_type}, "text": text}})


def test_history_admin_pagination_filter_and_unknown(web):
    app, client, sender = web
    svc = app.extensions["publications"]
    for n in range(12): svc.publish({**ITEM, "Name": f"Title {n}"}, "caption", ["-1001"], f"op-{n}")
    command(client, "/historial 2")
    text = sender.sent_texts[-1][0]
    assert "pagina 2/3" in text and "Title 6" in text and "Title 11" not in text
    command(client, "/historial 1 fallido")
    assert "0 entregas" in sender.sent_texts[-1][0]
    command(client, "/historial item missing")
    assert "historial desconocido" in sender.sent_texts[-1][0]


@pytest.mark.parametrize("chat_id,chat_type", [(99, "private"), (-1001, "group"), (42, "group")])
def test_history_rejected_for_non_admin_or_group(web, chat_id, chat_type):
    app, client, sender = web
    command(client, "/historial", chat_id, chat_type)
    assert sender.sent_texts[-1][0] == "Solo administradores configurados en privado."


def test_no_admin_fallback_to_chat_ids(monkeypatch, tmp_path):
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", WebSender)
    app = create_app(replace(_settings(), admin_chat_ids=[], chat_ids=["42"], history_db_path=str(tmp_path / "other.db")))
    command(app.test_client(), "/historial")
    assert "Solo administradores" in _FakeTelegramClient.latest.sent_texts[-1][0]


def callback(client, callback_id="callback-1", message_id=20):
    return client.post("/telegramhook", json={"update_id": 400,
        "callback_query": {"id": callback_id, "from": {"id": 42}, "data": "resend:to:chat:12345",
                           "message": {"message_id": message_id, "chat": {"id": 42, "type": "private"}}}})


def test_false_success_removed_and_replayed_callback_deduplicated(web):
    app, client, sender = web
    sender.failure = True
    assert callback(client).status_code == 200
    assert "fallido" in sender.sent_texts[-1][0]
    assert "Reenviado a" not in sender.sent_texts[-1][0]
    callback(client, "new-click-same-button")
    assert len(sender.sent_media) == 1
    sender.failure = False
    delivery = app.extensions["delivery_store"].history()[0][0]
    command(client, f"/reintentar {delivery['id']}", update=700)
    command(client, f"/reintentar {delivery['id']}", update=700)
    assert len(sender.sent_media) == 2
    assert "enviado" in sender.sent_texts[-1][0]
    # Opening a new selection and choosing a destination means a voluntary copy.
    callback(client, "new-operation", message_id=21)
    assert len(sender.sent_media) == 3


def test_web_storage_failure_is_503_and_never_sends(web, monkeypatch):
    app, client, sender = web
    def fail(*args, **kwargs): raise sqlite3.OperationalError("readonly")
    monkeypatch.setattr(app.extensions["delivery_store"], "prepare", fail)
    assert callback(client).status_code == 503
    assert sender.sent_media == []


def test_automatic_movies_record_and_do_not_repeat_after_app_recreation(web, monkeypatch):
    app, client, sender = web
    payload = {"Event": "library.new", "Item": ITEM}
    client.post("/embyhook", json=payload)
    assert app.extensions["delivery_store"].history()[0][0]["status"] == "sent"
    # Same persisted path, fresh process-like app and debounce dictionaries.
    other = create_app(replace(_settings(), history_db_path=app.extensions["delivery_store"].path))
    other.test_client().post("/embyhook", json=payload)
    assert _FakeTelegramClient.latest.sent_media == []


def test_episode_group_keeps_each_id_and_shared_message(service):
    svc, store, sender = service
    items = [{"Id": f"ep{n}", "Type": "Episode", "SeriesId": "series1", "IndexNumber": n,
              "ParentIndexNumber": 1} for n in [1, 2]]
    key = lambda item: f"ep:{item['Id']}"
    for item in items: svc.prepare(item, "single episode", ["a"], key(item), "automatic")
    svc.publish_episode_group(items, ["a"], key, lambda group: str([i["Id"] for i in group]))
    assert sender.calls == ["a"]
    rows, total = store.history()
    assert total == 2 and {r["item_id"] for r in rows} == {"ep1", "ep2"}
    assert all(r["message_id"] == 123 for r in rows)
    assert all("ep1" in store.attempts(r["id"])[0]["caption"] and
               "ep2" in store.attempts(r["id"])[0]["caption"] for r in rows)


@pytest.mark.network_guard
def test_external_connections_are_blocked():
    with pytest.raises(AssertionError, match="disabled"):
        socket.create_connection(("127.0.0.1", 9))
    with socket.socket() as sock:
        with pytest.raises(AssertionError, match="disabled"):
            sock.connect(("127.0.0.1", 9))


def test_configurable_path(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "fake")
    monkeypatch.setenv("CHAT_IDS", "a")
    monkeypatch.setenv("EMBY_API_KEY", "fake")
    monkeypatch.setenv("HISTORY_DB_PATH", str(tmp_path / "configured.db"))
    assert Settings.from_env().history_db_path == str(tmp_path / "configured.db")


def test_sdk_shutdown_error_keeps_confirmed_results(monkeypatch):
    class Bot:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): raise TimedOut()
        async def send_message(self, **kwargs): return SimpleNamespace(message_id=88)
    monkeypatch.setattr("emby_telegram_bot.telegram_client.Bot", Bot)
    assert TelegramClient("fake", ["a", "b"]).send("caption", None) == [
        SendResult("a", "sent", 88), SendResult("b", "sent", 88)]


def test_no_sdk_response_is_not_reported_as_success(monkeypatch):
    class Bot:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def send_message(self, **kwargs): return None
    monkeypatch.setattr("emby_telegram_bot.telegram_client.Bot", Bot)
    assert TelegramClient("fake", ["a"]).send("caption", None)[0].status == "uncertain"


def test_episode_webhook_persists_before_timer_and_retry_survives_restart(web, monkeypatch):
    app, client, sender = web
    scheduled = []
    class Timer:
        def __init__(self, delay, fn, args): scheduled.append((fn, args))
        def start(self): pass
    monkeypatch.setattr("emby_telegram_bot.episode_aggregator.threading.Timer", Timer)
    # Keep the actual episode returned by the fake Emby detail request.
    episode = {"Id": "episode-old", "Type": "Episode", "Name": "Pilot", "SeriesName": "Example",
               "SeriesId": "series-1", "ParentIndexNumber": 1, "IndexNumber": 1,
               "MediaStreams": [{"Type": "Audio"}]}
    monkeypatch.setattr(_FakeEmbyClient.latest, "get_item_by_id", lambda item_id: episode)
    assert client.post("/embyhook", json={"Item": episode}).status_code == 200
    store = app.extensions["delivery_store"]
    row = store.history()[0][0]
    assert row["status"] == "pending" and not sender.sent_media
    # A fresh service recovers pending work without needing the old timer.
    other_sender = Sender(DeliveryStore(store.path))
    svc = PublicationService(other_sender.store, other_sender, lambda item: None)
    assert svc.retry(row["id"], "explicit-pending-recovery")["status"] == "sent"
    fn, args = scheduled[0]
    fn(*args)
    assert not sender.sent_media  # Old timer cannot repeat a recovered episode.


def test_storage_failure_does_not_poison_in_memory_debounce(web, monkeypatch):
    app, client, sender = web
    store = app.extensions["delivery_store"]
    original = store.prepare
    def fail(*args, **kwargs): raise sqlite3.OperationalError("readonly")
    monkeypatch.setattr(store, "prepare", fail)
    assert client.post("/embyhook", json={"Item": ITEM}).status_code == 503
    monkeypatch.setattr(store, "prepare", original)
    assert client.post("/embyhook", json={"Item": ITEM}).status_code == 200
    assert len(sender.sent_media) == 1


def test_late_failure_cannot_erase_confirmed_overlapping_retry(service):
    svc, store, sender = service
    row = svc.prepare(ITEM, "caption", ["a"], "overlap", "manual")[0]
    old = store.claim(row["id"], "first-in-flight")
    retry = store.claim(row["id"], "explicit-overlap", retry=True, allow_uncertain=True)
    store.finish(retry, "sent", message_id=222)
    store.finish(old, "failed", error_type="Forbidden")
    assert store.get(row["id"])["status"] == "sent"
    assert store.get(row["id"])["message_id"] == 222
    assert store.claim(row["id"], "must-not-send", retry=True) is None
