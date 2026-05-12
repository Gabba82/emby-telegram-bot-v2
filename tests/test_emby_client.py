from emby_telegram_bot.emby_client import EmbyClient


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def test_search_items_returns_movie_and_series_results(monkeypatch) -> None:
    client = EmbyClient(base_url="http://emby:8096/emby", api_key="key", timeout_seconds=15)

    def fake_get(path, params=None, stream=False):
        assert path == "Items"
        assert params["SearchTerm"] == "wick"
        assert params["IncludeItemTypes"] == "Movie,Series"
        assert params["Recursive"] == "true"
        assert params["Limit"] == 10
        return _FakeResponse({"Items": [{"Type": "Movie", "Name": "John Wick"}]})

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.search_items(" wick ") == [{"Type": "Movie", "Name": "John Wick"}]


def test_search_items_ignores_empty_query() -> None:
    client = EmbyClient(base_url="http://emby:8096/emby", api_key="key", timeout_seconds=15)

    assert client.search_items(" ") == []


def test_get_item_by_id_uses_items_fallback(monkeypatch) -> None:
    client = EmbyClient(base_url="http://emby:8096/emby", api_key="key", timeout_seconds=15)

    def fake_get(path, params=None, stream=False):
        if path == "Items/item-1":
            raise RuntimeError("not found")
        assert path == "Items"
        assert params["Ids"] == "item-1"
        return _FakeResponse({"Items": [{"Id": "item-1", "Name": "John Wick"}]})

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.get_item_by_id("item-1") == {"Id": "item-1", "Name": "John Wick"}


def test_get_series_seasons(monkeypatch) -> None:
    client = EmbyClient(base_url="http://emby:8096/emby", api_key="key", timeout_seconds=15)

    def fake_get(path, params=None, stream=False):
        assert path == "Shows/series-1/Seasons"
        return _FakeResponse({"Items": [{"Id": "season-1", "IndexNumber": 1}]})

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.get_series_seasons("series-1") == [{"Id": "season-1", "IndexNumber": 1}]


def test_get_season_episodes(monkeypatch) -> None:
    client = EmbyClient(base_url="http://emby:8096/emby", api_key="key", timeout_seconds=15)

    def fake_get(path, params=None, stream=False):
        assert path == "Shows/series-1/Episodes"
        assert params["SeasonId"] == "season-1"
        return _FakeResponse({"Items": [{"Id": "ep-1", "IndexNumber": 1}]})

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.get_season_episodes("series-1", "season-1") == [{"Id": "ep-1", "IndexNumber": 1}]
