"""Validación QA aislada — EMBY-002 (Hermes).

Reglas duras:
  * Cero red: fixture autouse que bloquea socket.connect/create_connection/getaddrinfo.
  * Cero credenciales reales: tokens ficticios.
  * SQLite temporal en tmp_path; nada fuera del directorio de pruebas.
  * Se prueban las APIs reales (deliveries.DeliveryStore, publications.PublicationService,
    telegram_client.SendResult, webhook.create_app), sin dobles de la capa de persistencia.

Ejecutar:
    .venv-hermes-qa/bin/python -m pytest tests/test_hermes_validation.py -v
"""
from __future__ import annotations

import json
import os
import socket
import sqlite3

import pytest

from emby_telegram_bot.config import Settings
from emby_telegram_bot.deliveries import DecisionRequired, DeliveryStore
from emby_telegram_bot.publications import PublicationService
from emby_telegram_bot.telegram_client import SendResult
from emby_telegram_bot.webhook import create_app


# --------------------------------------------------------------------------- #
# Aislamiento de red (S10)
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def denied(*args, **kwargs):
        raise RuntimeError("EMBY-002 QA: conexión de red bloqueada por el harness")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def test_s10_bloqueo_de_red_efectivo():
    with pytest.raises(RuntimeError, match="red bloqueada"):
        socket.create_connection(("127.0.0.1", 9), timeout=0.1)
    sock = socket.socket()
    try:
        with pytest.raises(RuntimeError, match="red bloqueada"):
            sock.connect(("127.0.0.1", 9))
    finally:
        sock.close()


# --------------------------------------------------------------------------- #
# Dobles de infraestructura (solo Telegram/Emby; el store es el real)
# --------------------------------------------------------------------------- #
ITEM = {
    "Id": "movie-1",
    "Type": "Movie",
    "Name": "Arrival",
    "ProductionYear": 2016,
    # MediaStreams evita los reintentos con sleep(10) de _refresh_library_item.
    "MediaSources": [
        {"MediaStreams": [{"Type": "Audio", "Language": "spa", "Codec": "eac3", "Channels": 6}]}
    ],
}


class FakeTelegram:
    """Devuelve SendResult por chat. `outcomes[chat_id]` = 'sent'|'failed'|'uncertain'|Exception."""

    latest = None

    def __init__(self, token: str = "fake-token", chat_ids: list[str] | None = None):
        self.token = token
        self.chat_ids = list(chat_ids or [])
        self.calls: list[str] = []
        self.texts: list[tuple[str, list[str] | None]] = []
        self.outcomes: dict[str, object] = {}
        self.on_send = None
        FakeTelegram.latest = self

    # --- entrega ---------------------------------------------------------- #
    def send(self, caption: str, image_bytes=None, chat_ids=None):
        results = []
        for chat_id in chat_ids or []:
            chat_id = str(chat_id)
            self.calls.append(chat_id)
            if self.on_send is not None:
                self.on_send(chat_id)
            outcome = self.outcomes.get(chat_id, "sent")
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, SendResult):
                results.append(outcome)
                continue
            message_id = 9000 + len(self.calls) if outcome == "sent" else None
            results.append(SendResult(chat_id, str(outcome), message_id=message_id))
        return results

    def send_text(self, text: str, chat_ids=None, reply_markup=None):
        self.texts.append((text, chat_ids))

    # --- superficie usada por create_app / arranque ----------------------- #
    def configure_bot_commands(self, admin_chat_ids):
        return None

    def validate_credentials(self):
        return "@fakebot"

    def validate_chat(self, chat_id):
        return f"chat-{chat_id}"

    def answer_callback_query(self, *args, **kwargs):
        return None

    def send_search_menu(self, chat_id):
        return None

    def send_search_filter_menu(self, chat_id):
        return None

    def send_search_selection_menu(self, chat_id, query, items):
        return None

    def send_resend_item_menu(self, chat_id, items):
        return None

    def send_resend_target_menu(self, chat_id, item_id, item_name, targets):
        return None

    def send_search_admin_actions(self, chat_id, item_id):
        return None

    def send_search_again_action(self, chat_id):
        return None

    def send_private_menu_help(self, chat_id, is_admin=False):
        return None

    def request_search_query(self, chat_id, mode="all"):
        return None


class FakeEmby:
    latest = None

    def __init__(self, *args, **kwargs):
        self.item_requests: list[str] = []
        FakeEmby.latest = self

    def validate_credentials(self):
        return "Emby Test 1.0"

    def get_item_image(self, item):
        return None

    def get_item_info(self, item_id):
        self.item_requests.append(str(item_id))
        return dict(ITEM, Id=str(item_id))

    def get_item_by_id(self, item_id):
        return self.get_item_info(item_id)

    def get_recently_added_items(self, limit=10):
        return [ITEM]

    def get_latest_added_item(self):
        return ITEM

    def search_items(self, query, limit=10, include_item_types="Movie,Series"):
        return [ITEM]

    def get_series_seasons(self, series_id):
        return []

    def get_season_episodes(self, series_id, season_id):
        return []


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def store(tmp_path) -> DeliveryStore:
    return DeliveryStore(str(tmp_path / "history.sqlite3"))


@pytest.fixture
def telegram() -> FakeTelegram:
    return FakeTelegram()


@pytest.fixture
def service(store, telegram) -> PublicationService:
    return PublicationService(store, telegram, lambda item: None)


def _settings(tmp_path, **overrides) -> Settings:
    values = dict(
        telegram_token="fake-token",
        chat_ids=["-1001"],
        admin_chat_ids=["42"],
        library_chat_ids=[],
        playback_chat_ids=[],
        emby_api_url="http://emby.invalid:8096/emby",
        emby_api_key="fake-key",
        request_timeout_seconds=5,
        episode_buffer_seconds=60,
        library_debounce_seconds=0,
        playback_debounce_seconds=0,
        enable_library_notifications=True,
        enable_playback_notifications=True,
        playback_notify_pause=False,
        playback_with_image=False,
        playback_style="compact",
        app_timezone="Europe/Madrid",
        telegram_webhook_secret="",
        chat_labels={},
        history_db_path=str(tmp_path / "history.sqlite3"),
    )
    values.update(overrides)
    return Settings(**values)


def _webhook_app(monkeypatch, tmp_path, store, **overrides):
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", FakeEmby)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", FakeTelegram)
    return create_app(_settings(tmp_path, **overrides), store=store)


def _post_message(app, chat_id: int, text: str, chat_type: str = "private", update_id: int | None = None):
    payload = {
        "message": {
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": chat_id},
            "message_id": 1,
            "text": text,
        }
    }
    if update_id is not None:
        payload["update_id"] = update_id
    return app.test_client().post("/telegramhook", json=payload)


# --------------------------------------------------------------------------- #
# S1 — Persistencia tras recreación de proceso/store
# --------------------------------------------------------------------------- #
def test_s01_persistencia_tras_recrear_store(tmp_path, service, telegram):
    rows = service.publish(ITEM, "Arrival (2016)", ["a", "b"], "library:test:movie-1", "automatic")
    assert [r["status"] for r in rows] == ["sent", "sent"]
    sent_before = list(telegram.calls)

    # Simula reinicio de proceso: nueva instancia sobre el mismo fichero.
    reopened = DeliveryStore(str(tmp_path / "history.sqlite3"))
    history, total = reopened.history(1)
    assert total == 2
    assert {r["chat_id"] for r in history} == {"a", "b"}
    assert all(r["status"] == "sent" and r["message_id"] for r in history)
    # Reabrir no reenvía nada.
    assert telegram.calls == sent_before
    assert reopened.item_status("movie-1", "a") == "sent"


# --------------------------------------------------------------------------- #
# S2 — Intención registrada antes de llamar a Telegram
# --------------------------------------------------------------------------- #
def test_s02_intencion_antes_de_telegram(store, telegram):
    service = PublicationService(store, telegram, lambda item: None)
    snapshots = []

    def inspect(chat_id):
        rows, _ = store.history(1)
        row = rows[0]
        snapshots.append((row["status"], row["attempt_count"], store.attempts(row["id"])))

    telegram.on_send = inspect
    service.publish(ITEM, "Arrival (2016)", ["a"], "library:test:movie-1", "automatic")

    assert len(snapshots) == 1
    status_at_send, attempts_at_send, attempt_rows = snapshots[0]
    # claim() marca 'uncertain' ANTES del I/O: el intento existe y no está cerrado.
    assert status_at_send == "uncertain"
    assert attempts_at_send == 1
    assert attempt_rows[0]["finished_at"] is None
    assert store.history(1)[0][0]["status"] == "sent"


# --------------------------------------------------------------------------- #
# S3 — Resultado por chat
# --------------------------------------------------------------------------- #
def test_s03_resultado_por_chat(service, telegram):
    rows = service.publish(ITEM, "Arrival (2016)", ["a", "b"], "key-s3", "manual")

    assert len(rows) == 2
    assert {r["chat_id"]: r["status"] for r in rows} == {"a": "sent", "b": "sent"}
    assert all(r["message_id"] is not None for r in rows)
    assert len({r["message_id"] for r in rows}) == 2
    assert all(r["attempt_count"] == 1 for r in rows)


# --------------------------------------------------------------------------- #
# S4 — Fallo parcial: A éxito, B fallo
# --------------------------------------------------------------------------- #
def test_s04_fallo_parcial_a_ok_b_failed(service, telegram):
    telegram.outcomes["b"] = SendResult("b", "failed", error_type="Forbidden")

    rows = service.publish(ITEM, "Arrival (2016)", ["a", "b"], "key-s4", "manual")
    by_chat = {r["chat_id"]: r for r in rows}

    assert by_chat["a"]["status"] == "sent"
    assert by_chat["a"]["message_id"] is not None
    assert by_chat["b"]["status"] == "failed"
    assert by_chat["b"]["error_type"] == "Forbidden"
    assert by_chat["b"]["message_id"] is None
    # No se declara éxito global ni se reenvía A.
    assert telegram.calls.count("a") == 1


# --------------------------------------------------------------------------- #
# S5 — Reintento solo de B
# --------------------------------------------------------------------------- #
def test_s05_retry_solo_b(service, telegram):
    telegram.outcomes["b"] = SendResult("b", "failed", error_type="Forbidden")
    rows = service.publish(ITEM, "Arrival (2016)", ["a", "b"], "key-s5", "manual")
    by_chat = {r["chat_id"]: r for r in rows}
    a_calls, b_calls = telegram.calls.count("a"), telegram.calls.count("b")

    telegram.outcomes["b"] = "sent"
    retried = service.retry(by_chat["b"]["id"], "manual-retry-1")

    assert retried["status"] == "sent"
    assert telegram.calls.count("a") == a_calls          # A no se repite
    assert telegram.calls.count("b") == b_calls + 1      # solo B
    assert len(service.store.attempts(by_chat["a"]["id"])) == 1
    assert len(service.store.attempts(by_chat["b"]["id"])) == 2


# --------------------------------------------------------------------------- #
# S6 — Incierto requiere decisión explícita
# --------------------------------------------------------------------------- #
def test_s06_incierto_requiere_decision_explicita(service, telegram):
    telegram.outcomes["a"] = TimeoutError("timeout tras transmitir")

    rows = service.publish(ITEM, "Arrival (2016)", ["a"], "key-s6", "manual")
    assert rows[0]["status"] == "uncertain"
    assert rows[0]["error_type"] == "TimeoutError"
    assert telegram.calls.count("a") == 1  # sin reintento automático

    # Reintentar un incierto sin confirmación explícita debe exigir decisión.
    with pytest.raises(DecisionRequired):
        service.retry(rows[0]["id"], "retry-sin-confirmar")

    # Con confirmación explícita sí procede.
    telegram.outcomes["a"] = "sent"
    confirmed = service.retry(rows[0]["id"], "retry-confirmado", allow_uncertain=True)
    assert confirmed["status"] == "sent"


# --------------------------------------------------------------------------- #
# S7 — Historial paginado y restringido a admin privado
# --------------------------------------------------------------------------- #
def test_s07a_historial_paginado_en_store(store):
    for index in range(1, 8):
        store.prepare(ITEM, f"caption {index}", ["chat-a"], f"key-{index}", "manual")

    page1, total = store.history(page=1, page_size=5)
    page2, _ = store.history(page=2, page_size=5)

    assert total == 7
    assert len(page1) == 5
    assert len(page2) == 2
    assert {r["id"] for r in page1}.isdisjoint({r["id"] for r in page2})
    with pytest.raises(ValueError):
        store.history(page=0)
    with pytest.raises(ValueError):
        store.history(page=1, page_size=21)
    with pytest.raises(ValueError):
        store.history(page=1, status="inventado")


def test_s07b_historial_solo_admin_privado(monkeypatch, tmp_path, store):
    app = _webhook_app(monkeypatch, tmp_path, store)
    store.prepare(ITEM, "caption", ["-1001"], "key-admin", "manual")

    admin = _post_message(app, 42, "/historial")
    assert admin.status_code == 200
    assert "Historial · pagina 1" in FakeTelegram.latest.texts[-1][0]

    intruder = _post_message(app, 99, "/historial")
    assert intruder.status_code == 200
    assert "Solo administradores configurados en privado." in FakeTelegram.latest.texts[-1][0]

    group = _post_message(app, -1001, "/historial", chat_type="group")
    assert group.status_code == 200
    assert "Solo administradores configurados en privado." in FakeTelegram.latest.texts[-1][0]


# --------------------------------------------------------------------------- #
# S8 — Doble clic idempotente
# --------------------------------------------------------------------------- #
def test_s08a_doble_publish_mismo_request_key(service, telegram):
    service.publish(ITEM, "Arrival (2016)", ["a"], "same-key", "manual")
    service.publish(ITEM, "Arrival (2016)", ["a"], "same-key", "manual")

    assert telegram.calls.count("a") == 1
    assert service.store.history(1)[1] == 1


def test_s08b_doble_webhook_mismo_item(monkeypatch, tmp_path, store):
    app = _webhook_app(monkeypatch, tmp_path, store)
    payload = {"Event": "library.new", "Item": dict(ITEM)}

    first = app.test_client().post("/embyhook", json=payload)
    second = app.test_client().post("/embyhook", json=payload)

    assert first.status_code == 200 and second.status_code == 200
    assert FakeTelegram.latest.calls.count("-1001") == 1
    assert store.history(1)[1] == 1


def test_s08c_claim_repetido_no_llama(store):
    rows = store.prepare(ITEM, "caption", ["a"], "key-claim", "manual")
    delivery_id = rows[0]["id"]

    first = store.claim(delivery_id, "action:1")
    assert first is not None
    assert store.claim(delivery_id, "action:1") is None  # replay exacto
    store.finish(first, "sent", message_id=1)
    assert store.claim(delivery_id, "action:1") is None


# --------------------------------------------------------------------------- #
# S9 — DB no escribible => no se envía
# --------------------------------------------------------------------------- #
def _make_readonly(directory):
    for name in os.listdir(directory):
        os.chmod(os.path.join(directory, name), 0o400)
    os.chmod(directory, 0o500)


def _restore(directory):
    os.chmod(directory, 0o700)
    for name in os.listdir(directory):
        os.chmod(os.path.join(directory, name), 0o600)


def test_s09_db_no_escribible_no_envia(monkeypatch, tmp_path, store):
    app = _webhook_app(monkeypatch, tmp_path, store)
    db_dir = os.path.dirname(store.path)
    _make_readonly(db_dir)
    try:
        response = app.test_client().post(
            "/embyhook", json={"Event": "library.new", "Item": dict(ITEM)}
        )
    finally:
        _restore(db_dir)

    assert response.status_code == 503
    assert "Historial no disponible" in response.get_data(as_text=True)
    assert FakeTelegram.latest.calls == []


def test_s09b_store_rechaza_memoria_y_vacio(tmp_path):
    with pytest.raises(ValueError):
        DeliveryStore(":memory:")
    with pytest.raises(ValueError):
        DeliveryStore("   ")


# --------------------------------------------------------------------------- #
# S11 — Errores y metadatos sin credenciales
# --------------------------------------------------------------------------- #
def test_s11_errores_sin_credenciales(service, telegram):
    secret = "SECRET-API-KEY-123"
    item = dict(ITEM, Path=f"http://emby:8096/emby/Items?api_key={secret}")
    telegram.outcomes["a"] = TimeoutError(f"http://emby:8096/emby?api_key={secret}")

    rows = service.publish(item, "Arrival", ["a"], "key-s11", "manual")
    row = rows[0]

    assert row["error_type"] == "TimeoutError"
    assert secret not in json.dumps(row, ensure_ascii=False)
    assert secret not in json.dumps(service.store.attempts(row["id"]), ensure_ascii=False)


# --------------------------------------------------------------------------- #
# Extra — destinos duplicados no duplican entregas (hallazgo A6 de la auditoría)
# --------------------------------------------------------------------------- #
def test_s12_destinos_duplicados_no_duplican(store):
    rows = store.prepare(ITEM, "caption", ["a", "a", "b"], "key-dup", "manual")
    assert sorted(r["chat_id"] for r in rows) == ["a", "b"]
