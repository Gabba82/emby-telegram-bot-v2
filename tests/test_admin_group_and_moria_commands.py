import pytest
from emby_telegram_bot.config import Settings
from emby_telegram_bot.deliveries import DeliveryStore
from emby_telegram_bot.webhook import create_app


class _FakeEmbyClient:
    latest = None

    def __init__(self, *args, **kwargs) -> None:
        self.item_requests = []
        _FakeEmbyClient.latest = self

    def validate_credentials(self) -> str:
        return "Monsta 4.10.2.0"

    def get_latest_added_item(self):
        return self.get_item_info("latest-1")

    def get_item_info(self, item_id: str):
        return self.get_item_by_id(item_id)

    def get_recently_added_items(self, limit: int = 10):
        return [
            {"Id": "latest-1", "Type": "Movie", "Name": "Inception", "ProductionYear": 2010},
        ][:limit]

    def get_item_by_id(self, item_id: str):
        self.item_requests.append(item_id)
        if "moria" in str(item_id):
            return {
                "Id": item_id,
                "Type": "Movie",
                "Name": "Moria Movie",
                "ProductionYear": 2024,
                "Path": "/mnt/16G/PalaEmby-Pilot/Movies/Moria Movie.strm",
                "Container": "strm",
            }
        return {
            "Id": item_id,
            "Type": "Movie",
            "Name": "Inception",
            "ProductionYear": 2010,
            "Path": "/mnt/4TB/Pelis/Inception (2010)/Inception.mkv",
            "Container": "mkv",
        }

    def get_item_image(self, item: dict) -> bytes:
        return b"image-data"


class _FakeTelegramClient:
    latest = None

    def __init__(self, *args, **kwargs) -> None:
        self.sent_media = []
        self.sent_texts = []
        self.resend_item_menus = []
        self.resend_target_menus = []
        self.admin_menus = []
        self.callbacks = []
        _FakeTelegramClient.latest = self

    def send(self, caption: str, image_bytes: bytes | None, chat_ids=None) -> None:
        self.sent_media.append((caption, image_bytes, chat_ids))

    def send_media_group(self, caption: str, images, chat_ids=None):
        self.sent_media.append((caption, images[0] if images else None, chat_ids))
        from emby_telegram_bot.telegram_client import SendResult
        return [SendResult(cid, "sent", message_id=len(self.sent_media)) for cid in (chat_ids or ["-1001"])]

    def send_text(self, text: str, chat_ids=None, reply_markup=None) -> None:
        self.sent_texts.append((text, chat_ids))

    def send_admin_menu(self, chat_id: str) -> None:
        self.admin_menus.append(chat_id)
        self.sent_texts.append(("Panel de Control", [chat_id]))

    def send_resend_item_menu(self, chat_id: str, items: list) -> None:
        self.resend_item_menus.append((chat_id, items))

    def send_resend_target_menu(self, chat_id: str, item_id: str, item_name: str, targets) -> None:
        self.resend_target_menus.append((chat_id, item_id, item_name, targets))

    def answer_callback_query(self, callback_query_id: str, text: str = "", show_alert: bool = False) -> None:
        self.callbacks.append((callback_query_id, text, show_alert))

    def validate_credentials(self) -> str:
        return "@TestBot"

    def configure_bot_commands(self, admin_chat_ids) -> None:
        pass


def _settings(**kwargs) -> Settings:
    defaults = {
        "telegram_token": "token",
        "chat_ids": ["-1001"],
        "admin_chat_ids": ["42"],
        "library_chat_ids": ["-10099"],
        "playback_chat_ids": ["-10099"],
        "emby_api_url": "http://emby:8096/emby",
        "emby_api_key": "key",
        "request_timeout_seconds": 15,
        "episode_buffer_seconds": 60,
        "library_debounce_seconds": 0,
        "playback_debounce_seconds": 10,
        "enable_library_notifications": True,
        "enable_playback_notifications": True,
        "playback_notify_pause": False,
        "playback_with_image": False,
        "playback_style": "compact",
        "app_timezone": "Europe/Madrid",
        "telegram_webhook_secret": "",
        "chat_labels": {},
        "history_db_path": "data/history.sqlite3",
        "moria_buffer_seconds": 120,
        "moria_library_indicators": ["strm", "PalaEmby"],
        "enable_moria_batch": True,
    }
    defaults.update(kwargs)
    return Settings(**defaults)


def test_admin_commands_in_group_allowed_for_admin_user(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())
    client = app.test_client()

    # /reenviar from group -10099 by admin user 42
    resp = client.post(
        "/telegramhook",
        json={"message": {"chat": {"id": -10099, "type": "supergroup"}, "from": {"id": 42}, "text": "/reenviar"}},
    )
    assert resp.status_code == 200
    assert len(_FakeTelegramClient.latest.resend_item_menus) == 1
    assert _FakeTelegramClient.latest.resend_item_menus[0][0] == "-10099"

    # /reenviaultimo from group -10099 by admin user 42
    resp2 = client.post(
        "/telegramhook",
        json={"message": {"chat": {"id": -10099, "type": "supergroup"}, "from": {"id": 42}, "text": "/reenviaultimo"}},
    )
    assert resp2.status_code == 200
    assert len(_FakeTelegramClient.latest.resend_target_menus) == 1
    assert _FakeTelegramClient.latest.resend_target_menus[0][0] == "-10099"

    # /help in group by admin user 42 includes Admin: and Moria commands
    resp3 = client.post(
        "/telegramhook",
        json={"message": {"chat": {"id": -10099, "type": "supergroup"}, "from": {"id": 42}, "text": "/help"}},
    )
    assert resp3.status_code == 200
    help_text = _FakeTelegramClient.latest.sent_texts[-1][0]
    assert "Admin:" in help_text
    assert "/moria_status" in help_text
    assert "/moria_flush" in help_text


def test_admin_commands_in_group_rejected_for_non_admin_user(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())
    client = app.test_client()

    resp = client.post(
        "/telegramhook",
        json={"message": {"chat": {"id": -10099, "type": "supergroup"}, "from": {"id": 9999}, "text": "/reenviar"}},
    )
    assert resp.status_code == 200
    assert "Este comando solo esta disponible para administradores." in _FakeTelegramClient.latest.sent_texts[-1][0]
    assert len(_FakeTelegramClient.latest.resend_item_menus) == 0

    resp2 = client.post(
        "/telegramhook",
        json={"message": {"chat": {"id": -10099, "type": "supergroup"}, "from": {"id": 9999}, "text": "/moria_status"}},
    )
    assert resp2.status_code == 200
    assert "Este comando solo esta disponible para administradores." in _FakeTelegramClient.latest.sent_texts[-1][0]


def test_moria_status_and_flush_commands(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)

    db_path = str(tmp_path / "test_history.sqlite3")
    store = DeliveryStore(db_path)
    settings = _settings()
    app = create_app(settings, store)
    client = app.test_client()

    # Initially buffer is empty
    client.post(
        "/telegramhook",
        json={"message": {"chat": {"id": -10099, "type": "supergroup"}, "from": {"id": 42}, "text": "/moria_status"}},
    )
    status_text = _FakeTelegramClient.latest.sent_texts[-1][0]
    assert "Peliculas pendientes: 0" in status_text
    assert "Total en cola: 0" in status_text

    # Flush when empty
    client.post(
        "/telegramhook",
        json={"message": {"chat": {"id": -10099, "type": "supergroup"}, "from": {"id": 42}, "text": "/moria_flush"}},
    )
    assert "vacio" in _FakeTelegramClient.latest.sent_texts[-1][0].lower()

    # Add a Moria movie
    moria_item = {
        "Id": "moria-1",
        "Type": "Movie",
        "Name": "El Senor de los Anillos",
        "ProductionYear": 2001,
        "Path": "/mnt/16G/PalaEmby-Pilot/Movies/LotR.strm",
        "Container": "strm",
    }
    client.post("/embyhook", json={"Event": "library.new", "Item": moria_item})

    # Status now shows 1 pending
    client.post(
        "/telegramhook",
        json={"message": {"chat": {"id": -10099, "type": "supergroup"}, "from": {"id": 42}, "text": "/moria_status"}},
    )
    status_text2 = _FakeTelegramClient.latest.sent_texts[-1][0]
    assert "Peliculas pendientes: 1" in status_text2
    assert "Total en cola: 1" in status_text2

    # Flush command forces immediate delivery
    client.post(
        "/telegramhook",
        json={"message": {"chat": {"id": -10099, "type": "supergroup"}, "from": {"id": 42}, "text": "/moria_flush"}},
    )
    assert len(_FakeTelegramClient.latest.sent_media) == 1
    assert "NUEVAS PELÍCULAS EN MORIA" in _FakeTelegramClient.latest.sent_media[0][0]


def test_admin_resend_callback_in_group(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())
    client = app.test_client()

    # Admin user 42 clicks resend:item:item-1 in group
    resp = client.post(
        "/telegramhook",
        json={
            "callback_query": {
                "id": "cb-admin",
                "from": {"id": 42},
                "data": "resend:item:latest-1",
                "message": {"chat": {"id": -10099, "type": "supergroup"}},
            }
        },
    )
    assert resp.status_code == 200
    assert len(_FakeTelegramClient.latest.resend_target_menus) == 1
    assert _FakeTelegramClient.latest.resend_target_menus[0][1] == "latest-1"

    # Non-admin clicks resend:item in group -> alert "No autorizado"
    resp2 = client.post(
        "/telegramhook",
        json={
            "callback_query": {
                "id": "cb-unauth",
                "from": {"id": 9999},
                "data": "resend:item:latest-1",
                "message": {"chat": {"id": -10099, "type": "supergroup"}},
            }
        },
    )
    assert resp2.status_code == 200
    assert ("cb-unauth", "No autorizado", True) in _FakeTelegramClient.latest.callbacks


def test_admin_menu_command_and_callbacks_in_group(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())
    client = app.test_client()

    # Admin sends /menu in group -> shows admin menu
    resp = client.post(
        "/telegramhook",
        json={"message": {"chat": {"id": -10099, "type": "supergroup"}, "from": {"id": 42}, "text": "/menu"}},
    )
    assert resp.status_code == 200
    assert _FakeTelegramClient.latest.admin_menus == ["-10099"]

    # Admin clicks admin:menu:resend_recent in group
    resp2 = client.post(
        "/telegramhook",
        json={
            "callback_query": {
                "id": "cb-menu-recent",
                "from": {"id": 42},
                "data": "admin:menu:resend_recent",
                "message": {"chat": {"id": -10099, "type": "supergroup"}},
            }
        },
    )
    assert resp2.status_code == 200
    assert len(_FakeTelegramClient.latest.resend_item_menus) == 1

    # Admin clicks admin:menu:moria_status in group
    resp3 = client.post(
        "/telegramhook",
        json={
            "callback_query": {
                "id": "cb-menu-status",
                "from": {"id": 42},
                "data": "admin:menu:moria_status",
                "message": {"chat": {"id": -10099, "type": "supergroup"}},
            }
        },
    )
    assert resp3.status_code == 200
    assert "buffer Moria" in _FakeTelegramClient.latest.sent_texts[-1][0]

    # Non-admin clicks admin:menu in group -> rejected
    resp4 = client.post(
        "/telegramhook",
        json={
            "callback_query": {
                "id": "cb-menu-unauth",
                "from": {"id": 9999},
                "data": "admin:menu:resend_recent",
                "message": {"chat": {"id": -10099, "type": "supergroup"}},
            }
        },
    )
    assert resp4.status_code == 200
    assert ("cb-menu-unauth", "No autorizado", True) in _FakeTelegramClient.latest.callbacks

