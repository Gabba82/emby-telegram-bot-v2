from emby_telegram_bot.config import Settings
from emby_telegram_bot.telegram_client import ADMIN_LATEST_BUTTON_TEXT
from emby_telegram_bot.webhook import create_app


def _settings(secret: str = "") -> Settings:
    return Settings(
        telegram_token="token",
        chat_ids=["-1001"],
        admin_chat_ids=["42"],
        library_chat_ids=[],
        playback_chat_ids=[],
        emby_api_url="http://emby:8096/emby",
        emby_api_key="key",
        request_timeout_seconds=15,
        episode_buffer_seconds=60,
        library_debounce_seconds=120,
        playback_debounce_seconds=10,
        enable_library_notifications=True,
        enable_playback_notifications=True,
        playback_notify_pause=False,
        playback_with_image=False,
        playback_style="compact",
        app_timezone="Europe/Madrid",
        telegram_webhook_secret=secret,
    )


class _FakeEmbyClient:
    latest = None

    def __init__(self, *args, **kwargs) -> None:
        self.searches = []
        self.item_requests = []
        _FakeEmbyClient.latest = self

    def search_items(self, query: str, limit: int = 10):
        self.searches.append((query, limit))
        return [{"Id": "item-1", "Type": "Movie", "Name": "John Wick", "ProductionYear": 2014}]

    def get_item_info(self, item_id: str):
        self.item_requests.append(item_id)
        return {
            "Id": item_id,
            "Type": "Movie",
            "Name": "John Wick",
            "ProductionYear": 2014,
            "Overview": "Un asesino retirado vuelve a la accion.",
        }

    def get_item_by_id(self, item_id: str):
        return self.get_item_info(item_id)

    def get_latest_added_item(self):
        return self.get_item_info("latest-1")

    def get_recently_added_items(self, limit: int = 10):
        return [
            {"Id": "latest-1", "Type": "Movie", "Name": "John Wick", "ProductionYear": 2014},
            {"Id": "latest-2", "Type": "Series", "Name": "Dorohedoro"},
        ][:limit]

    def validate_credentials(self) -> str:
        return "Emby Test 1.0"

    def get_series_seasons(self, series_id: str):
        return [{"Id": "season-1", "IndexNumber": 1}]

    def get_season_episodes(self, series_id: str, season_id: str):
        return [{"IndexNumber": 1}, {"IndexNumber": 2}]

    def get_item_image(self, item):
        return b"image"


class _FakeTelegramClient:
    latest = None

    def __init__(self, *args, **kwargs) -> None:
        self.sent_texts = []
        self.sent_media = []
        self.selection_menus = []
        self.resend_item_menus = []
        self.resend_target_menus = []
        self.menus = []
        self.private_menu_helps = []
        self.command_configs = []
        self.search_requests = []
        self.callbacks = []
        _FakeTelegramClient.latest = self

    def send(self, caption: str, image_bytes, chat_ids=None) -> None:
        self.sent_media.append((caption, image_bytes, chat_ids))

    def send_text(self, text: str, chat_ids=None, reply_markup=None) -> None:
        self.sent_texts.append((text, chat_ids))

    def send_search_menu(self, chat_id: str) -> None:
        self.menus.append(chat_id)

    def send_search_selection_menu(self, chat_id: str, query: str, items) -> None:
        self.selection_menus.append((chat_id, query, items))

    def send_resend_item_menu(self, chat_id: str, items) -> None:
        self.resend_item_menus.append((chat_id, items))

    def send_resend_target_menu(self, chat_id: str, item_id: str, item_name: str, targets) -> None:
        self.resend_target_menus.append((chat_id, item_id, item_name, targets))

    def send_private_menu_help(self, chat_id: str, is_admin: bool = False) -> None:
        self.private_menu_helps.append((chat_id, is_admin))

    def request_search_query(self, chat_id: str) -> None:
        self.search_requests.append(chat_id)

    def configure_bot_commands(self, admin_chat_ids) -> None:
        self.command_configs.append(list(admin_chat_ids))

    def answer_callback_query(self, callback_query_id: str, text: str = "", show_alert: bool = False) -> None:
        self.callbacks.append((callback_query_id, text, show_alert))

    def validate_credentials(self) -> str:
        return "@testbot"


def test_telegramhook_search_command(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": -1001, "type": "private"}, "text": "/buscar wick"}},
    )

    assert response.status_code == 200
    assert _FakeEmbyClient.latest.searches == [("wick", 10)]
    assert _FakeEmbyClient.latest.item_requests == ["item-1"]
    assert "John Wick" in _FakeTelegramClient.latest.sent_media[0][0]
    assert _FakeTelegramClient.latest.sent_media[0][1] == b"image"


def test_telegramhook_rejects_invalid_secret(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings(secret="expected"))

    response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": -1001}, "text": "/buscar wick"}},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong"},
    )

    assert response.status_code == 403


def test_telegramhook_group_button_requests_private_search(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={
            "callback_query": {
                "id": "callback-1",
                "from": {"id": 42},
                "data": "search:start",
                "message": {"chat": {"id": -1001, "type": "group"}},
            }
        },
    )

    assert response.status_code == 200
    assert _FakeTelegramClient.latest.search_requests == ["42"]
    assert _FakeTelegramClient.latest.callbacks == [
        ("callback-1", "Te he escrito por privado. Si no llega, abre el bot y pulsa Iniciar.", True)
    ]


def test_telegramhook_private_start_shows_persistent_keyboard(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": -1001, "type": "private"}, "text": "/start"}},
    )

    assert response.status_code == 200
    assert _FakeTelegramClient.latest.private_menu_helps == [("-1001", False)]
    assert _FakeTelegramClient.latest.command_configs == [["42"]]


def test_telegramhook_private_keyboard_button_requests_search_for_started_user(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    start_response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": 99, "type": "private"}, "text": "/start"}},
    )
    button_response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": 99, "type": "private"}, "text": "🔎 Buscar pelicula o serie"}},
    )

    assert start_response.status_code == 200
    assert button_response.status_code == 200
    assert _FakeTelegramClient.latest.private_menu_helps == [("99", False)]
    assert _FakeTelegramClient.latest.search_requests == ["99"]
    assert _FakeEmbyClient.latest.searches == []


def test_telegramhook_private_search_command_requests_query_for_normal_user(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": 99, "type": "private"}, "text": "/buscar"}},
    )

    assert response.status_code == 200
    assert _FakeTelegramClient.latest.search_requests == ["99"]
    assert _FakeEmbyClient.latest.searches == []


def test_telegramhook_private_search_command_with_query_searches_for_normal_user(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": 99, "type": "private"}, "text": "/buscar wick"}},
    )

    assert response.status_code == 200
    assert _FakeEmbyClient.latest.searches == [("wick", 10)]
    assert "John Wick" in _FakeTelegramClient.latest.sent_media[0][0]


def test_telegramhook_private_admin_start_shows_admin_keyboard(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": 42, "type": "private"}, "text": "/start"}},
    )

    assert response.status_code == 200
    assert _FakeTelegramClient.latest.private_menu_helps == [("42", True)]


def test_telegramhook_private_admin_latest_button_shows_target_menu(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": 42, "type": "private"}, "text": ADMIN_LATEST_BUTTON_TEXT}},
    )

    assert response.status_code == 200
    assert _FakeEmbyClient.latest.item_requests == ["latest-1"]
    assert _FakeTelegramClient.latest.resend_target_menus[0][1] == "latest-1"


def test_telegramhook_multiple_results_sends_selection_menu(monkeypatch) -> None:
    class MultiResultEmbyClient(_FakeEmbyClient):
        def search_items(self, query: str, limit: int = 10):
            self.searches.append((query, limit))
            return [
                {"Id": "item-1", "Type": "Movie", "Name": "John Wick", "ProductionYear": 2014},
                {"Id": "item-2", "Type": "Movie", "Name": "John Wick 2", "ProductionYear": 2017},
            ]

    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", MultiResultEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": -1001, "type": "private"}, "text": "/buscar wick"}},
    )

    assert response.status_code == 200
    assert _FakeTelegramClient.latest.selection_menus[0][1] == "wick"
    assert _FakeTelegramClient.latest.sent_media == []


def test_telegramhook_selected_result_sends_item_card(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={
            "callback_query": {
                "id": "callback-2",
                "from": {"id": 42},
                "data": "search:item:item-1",
                "message": {"chat": {"id": 42, "type": "private"}},
            }
        },
    )

    assert response.status_code == 200
    assert _FakeEmbyClient.latest.item_requests
    assert "John Wick" in _FakeTelegramClient.latest.sent_media[0][0]
    assert "Un asesino retirado" in _FakeTelegramClient.latest.sent_media[0][0]


def test_telegramhook_reenviaultimo_shows_target_menu_to_private_admin(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": 42, "type": "private"}, "text": "/reenviaultimo"}},
    )

    assert response.status_code == 200
    assert _FakeEmbyClient.latest.item_requests == ["latest-1"]
    assert _FakeTelegramClient.latest.resend_target_menus[0][1] == "latest-1"
    assert _FakeTelegramClient.latest.sent_media == []


def test_telegramhook_reenvia_shows_target_menu_to_private_admin(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": 42, "type": "private"}, "text": "/reenvia 12345"}},
    )

    assert response.status_code == 200
    assert _FakeEmbyClient.latest.item_requests == ["12345"]
    assert _FakeTelegramClient.latest.resend_target_menus[0][1] == "12345"
    assert _FakeTelegramClient.latest.sent_media == []


def test_telegramhook_reenviar_shows_recent_item_menu(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={"message": {"chat": {"id": 42, "type": "private"}, "text": "/reenviar"}},
    )

    assert response.status_code == 200
    assert _FakeTelegramClient.latest.resend_item_menus[0][0] == "42"
    assert _FakeTelegramClient.latest.resend_item_menus[0][1][0]["Id"] == "latest-1"


def test_telegramhook_resend_callback_sends_to_selected_target(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/telegramhook",
        json={
            "callback_query": {
                "id": "callback-3",
                "from": {"id": 42},
                "data": "resend:to:chat:12345",
                "message": {"chat": {"id": 42, "type": "private"}},
            }
        },
    )

    assert response.status_code == 200
    assert _FakeEmbyClient.latest.item_requests == ["12345"]
    assert "John Wick" in _FakeTelegramClient.latest.sent_media[0][0]
    assert _FakeTelegramClient.latest.sent_media[0][2] == ["-1001"]
    assert _FakeTelegramClient.latest.callbacks[0] == ("callback-3", "Reenviando...", False)


def test_embyhook_accepts_pascal_case_playback_event(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())

    response = app.test_client().post(
        "/embyhook",
        json={
            "Event": "PlaybackStart",
            "UserName": "gabba",
            "Client": "Android TV",
            "Item": {"Id": "item-1", "Type": "Movie", "Name": "John Wick"},
        },
    )

    assert response.status_code == 200
    assert "Reproduccion iniciada" in _FakeTelegramClient.latest.sent_media[0][0]
    assert _FakeTelegramClient.latest.sent_media[0][2] == ["-1001"]


def test_embyhook_debounces_duplicate_library_event(monkeypatch) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _FakeEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)
    app = create_app(_settings())
    payload = {
        "Event": "library.new",
        "Item": {"Id": "movie-1", "Type": "Movie", "Name": "Arrival"},
    }

    first_response = app.test_client().post("/embyhook", json=payload)
    second_response = app.test_client().post("/embyhook", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert len(_FakeTelegramClient.latest.sent_media) == 1
