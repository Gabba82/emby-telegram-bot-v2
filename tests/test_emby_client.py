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


def test_get_latest_added_item_fetches_details(monkeypatch) -> None:
    client = EmbyClient(base_url="http://emby:8096/emby", api_key="key", timeout_seconds=15)
    calls = []

    def fake_get(path, params=None, stream=False):
        calls.append((path, params))
        if path == "Items" and params.get("Limit") == 50:
            assert params["SortBy"] == "DateCreated"
            assert params["SortOrder"] == "Descending"
            return _FakeResponse({"Items": [{"Id": "item-1", "Name": "Old name"}]})
        if path == "Items/item-1":
            return _FakeResponse({"Id": "item-1", "Name": "Correct name"})
        raise AssertionError(path)

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.get_latest_added_item() == {"Id": "item-1", "Name": "Correct name"}


def test_get_recently_added_items_collapses_episodes_to_series(monkeypatch) -> None:
    client = EmbyClient(base_url="http://emby:8096/emby", api_key="key", timeout_seconds=15)

    def fake_get(path, params=None, stream=False):
        if path == "Items" and params.get("Limit") == 50:
            return _FakeResponse(
                {
                    "Items": [
                        {"Id": "ep-2", "Type": "Episode", "Name": "Episodio 2", "SeriesId": "series-1"},
                        {"Id": "ep-1", "Type": "Episode", "Name": "Episodio 1", "SeriesId": "series-1"},
                        {"Id": "movie-1", "Type": "Movie", "Name": "Arrival"},
                    ]
                }
            )
        if path == "Items/series-1":
            return _FakeResponse({"Id": "series-1", "Type": "Series", "Name": "Dorohedoro"})
        raise AssertionError(path)

    monkeypatch.setattr(client, "_get", fake_get)

    assert client.get_recently_added_items(limit=10) == [
        {"Id": "series-1", "Type": "Series", "Name": "Dorohedoro"},
        {"Id": "movie-1", "Type": "Movie", "Name": "Arrival"},
    ]


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
