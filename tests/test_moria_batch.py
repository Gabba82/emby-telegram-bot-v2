from __future__ import annotations

import io
import pytest

from emby_telegram_bot.config import Settings
from emby_telegram_bot.deliveries import DeliveryStore
from emby_telegram_bot.formatting import (
    build_moria_movies_reports,
    build_moria_series_reports,
    is_moria_item,
)
from emby_telegram_bot.moria_aggregator import MoriaBatchAggregator
from emby_telegram_bot.webhook import create_app
from test_webhook import _FakeEmbyClient, _FakeTelegramClient


def _settings(enable_moria_batch: bool = True) -> Settings:
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
        library_debounce_seconds=0,
        playback_debounce_seconds=10,
        enable_library_notifications=True,
        enable_playback_notifications=True,
        playback_notify_pause=False,
        playback_with_image=False,
        playback_style="compact",
        app_timezone="Europe/Madrid",
        telegram_webhook_secret="",
        chat_labels={},
        history_db_path="data/history.sqlite3",
        moria_buffer_seconds=120,
        moria_library_indicators=["strm", "PalaEmby"],
        enable_moria_batch=enable_moria_batch,
    )


def test_is_moria_item_classification() -> None:
    # 1. Moria items (strm / PalaEmby)
    assert is_moria_item({"Path": "/mnt/16G/PalaEmby-Pilot/Movies/Test/Test.strm"})
    assert is_moria_item({"Container": "strm"})
    assert is_moria_item({"Container": "STRM"})
    assert is_moria_item({"Path": "/media/devmon/PalaEmby/video.mkv"})
    assert is_moria_item({"MediaSources": [{"Path": "http://palaemby:8787/stream/xyz.strm", "Container": "strm"}]})

    # 2. Torrent / local items
    assert not is_moria_item({"Path": "/mnt/4TB/Pelis/Inception (2010)/Inception.mkv", "Container": "mkv"})
    assert not is_moria_item({"Path": "/mnt/8TB/Series/Breaking Bad/S01E01.mp4", "Container": "mp4"})
    assert not is_moria_item({"MediaSources": [{"Path": "/mnt/8TB/Conciertos/Live.mkv", "Container": "mkv"}]})
    assert not is_moria_item({})
    assert not is_moria_item(None)


def test_moria_batch_aggregator_buffers_and_flushes() -> None:
    flushed_movies = []
    flushed_series = []

    aggregator = MoriaBatchAggregator(
        flush_delay_seconds=60,
        flush_movies_callback=lambda movies: flushed_movies.extend(movies),
        flush_series_callback=lambda series: flushed_series.extend(series),
    )

    movie1 = {"Id": "m1", "Type": "Movie", "Name": "Movie 1"}
    movie2 = {"Id": "m2", "Type": "Movie", "Name": "Movie 2"}
    ep1 = {"Id": "e1", "Type": "Episode", "Name": "Ep 1", "SeriesName": "Show A", "ParentIndexNumber": 1, "IndexNumber": 1}

    aggregator.add_movie(movie1)
    aggregator.add_movie(movie2)
    aggregator.add_episode(ep1)

    assert aggregator.pending_count() == (2, 1)

    # Flushes both lists
    aggregator.flush_now()

    assert aggregator.pending_count() == (0, 0)
    assert [m["Id"] for m in flushed_movies] == ["m1", "m2"]
    assert [e["Id"] for e in flushed_series] == ["e1"]


def test_build_moria_movies_reports_single_and_paginated() -> None:
    # 3 movies -> 1 report part
    movies = [
        {
            "Id": f"m{i}",
            "Name": f"Película {i}",
            "ProductionYear": 2020 + i,
            "CommunityRating": 7.5,
            "Genres": ["Acción", "Drama"],
            "RunTimeTicks": 7200 * 10_000_000,
            "Overview": f"Sinopsis detallada de la película {i}.",
        }
        for i in range(1, 4)
    ]

    reports = build_moria_movies_reports(movies)
    assert len(reports) == 1
    caption, batch_items = reports[0]
    assert "🎬 NUEVAS PELÍCULAS EN MORIA (PalaEmby) · 3 películas" in caption
    assert "🍿 Película 1 (2021) · ⭐ 7.5/10 · Acción, Drama · ⏱️ 2h 0m" in caption
    assert "Sinopsis:" in caption
    assert len(batch_items) == 3

    # 15 movies with max_album_images=10 -> 2 parts (10 + 5)
    movies_15 = [
        {
            "Id": f"m{i}",
            "Name": f"Película {i}",
            "ProductionYear": 2024,
            "Overview": "Sinopsis corta",
        }
        for i in range(1, 16)
    ]
    paginated_reports = build_moria_movies_reports(movies_15, max_album_images=10)
    assert len(paginated_reports) == 2
    assert "Parte 1/2 (10 de 15 películas)" in paginated_reports[0][0]
    assert len(paginated_reports[0][1]) == 10
    assert "Parte 2/2 (5 de 15 películas)" in paginated_reports[1][0]
    assert len(paginated_reports[1][1]) == 5


class _CustomEmbyClient(_FakeEmbyClient):
    registered_items: dict[str, dict] = {}

    def get_item_by_id(self, item_id: str):
        if item_id in _CustomEmbyClient.registered_items:
            return dict(_CustomEmbyClient.registered_items[item_id])
        return super().get_item_by_id(item_id)

    def get_item_info(self, item_id: str):
        if item_id in _CustomEmbyClient.registered_items:
            return dict(_CustomEmbyClient.registered_items[item_id])
        return super().get_item_info(item_id)


def test_build_moria_series_reports_groups_episodes() -> None:
    episodes = [
        {"Id": "e1", "SeriesName": "Arcane", "ParentIndexNumber": 2, "IndexNumber": 1},
        {"Id": "e2", "SeriesName": "Arcane", "ParentIndexNumber": 2, "IndexNumber": 2},
        {"Id": "e3", "SeriesName": "Arcane", "ParentIndexNumber": 2, "IndexNumber": 3},
        {"Id": "e4", "SeriesName": "Yellowstone", "ParentIndexNumber": 5, "IndexNumber": 9},
    ]

    reports = build_moria_series_reports(episodes)
    assert len(reports) == 1
    caption, samples = reports[0]
    assert "📺 NUEVAS SERIES Y TEMPORADAS EN MORIA (PalaEmby) · 2 series actualizadas" in caption
    assert "🔹 Arcane · Temporada 2" in caption
    assert "🧩 Episodios añadidos: E01-E03" in caption
    assert "🔹 Yellowstone · Temporada 5" in caption
    assert "🧩 Episodios añadidos: E09" in caption
    assert len(samples) == 2


def test_webhook_distinguishes_moria_from_torrents(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _CustomEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)

    db_path = str(tmp_path / "test_history.sqlite3")
    store = DeliveryStore(db_path)
    settings = _settings(enable_moria_batch=True)
    app = create_app(settings, store)
    client = app.test_client()

    # 1. Non-Moria Torrent movie: must be sent IMMEDIATELY as individual post
    torrent_movie = {
        "Id": "torrent-movie-1",
        "Type": "Movie",
        "Name": "Torrente Movie",
        "Path": "/mnt/4TB/Pelis/Torrente Movie (2020)/Torrente Movie.mkv",
        "Container": "mkv",
        "MediaStreams": [{"Type": "Video", "Height": 1080}],
    }
    _CustomEmbyClient.registered_items["torrent-movie-1"] = torrent_movie

    resp1 = client.post("/embyhook", json={"Event": "library.new", "Item": torrent_movie})
    assert resp1.status_code == 200

    # Verify that FakeTelegramClient immediately sent an individual post
    sent_media = _FakeTelegramClient.latest.sent_media
    assert len(sent_media) == 1
    assert "Película: Torrente Movie" in sent_media[0][0]
    assert "NUEVAS PELÍCULAS EN MORIA" not in sent_media[0][0]

    # 2. Moria movies: must be BUFFERED and not sent immediately
    moria_movie1 = {
        "Id": "moria-movie-1",
        "Type": "Movie",
        "Name": "5 metros cuadrados",
        "ProductionYear": 2011,
        "Path": "/mnt/16G/PalaEmby-Pilot/Movies/5 metros cuadrados (2011)/5 metros cuadrados.strm",
        "Container": "strm",
        "MediaStreams": [{"Type": "Video", "Height": 1080}],
    }
    moria_movie2 = {
        "Id": "moria-movie-2",
        "Type": "Movie",
        "Name": "La Gran Aventura",
        "ProductionYear": 2024,
        "Path": "/mnt/16G/PalaEmby-Pilot/Movies/La Gran Aventura (2024)/La Gran Aventura.strm",
        "Container": "strm",
        "MediaStreams": [{"Type": "Video", "Height": 1080}],
    }
    _CustomEmbyClient.registered_items["moria-movie-1"] = moria_movie1
    _CustomEmbyClient.registered_items["moria-movie-2"] = moria_movie2

    resp2 = client.post("/embyhook", json={"Event": "library.new", "Item": moria_movie1})
    resp3 = client.post("/embyhook", json={"Event": "library.new", "Item": moria_movie2})
    assert resp2.status_code == 200
    assert resp3.status_code == 200

    # Still only 1 message sent so far (the torrent movie)
    assert len(_FakeTelegramClient.latest.sent_media) == 1

    # 3. Flush the Moria aggregator
    moria_agg = app.extensions["moria_aggregator"]
    moria_agg.flush_now()

    # Now the consolidated post has been sent
    assert len(_FakeTelegramClient.latest.sent_media) == 2
    consolidated_caption = _FakeTelegramClient.latest.sent_media[1][0]
    assert "🎬 NUEVAS PELÍCULAS EN MORIA (PalaEmby) · 2 películas" in consolidated_caption
    assert "5 metros cuadrados" in consolidated_caption
    assert "La Gran Aventura" in consolidated_caption

    # Check delivery ledger: both Moria movies must be registered in SQLite history
    status_m1 = store.item_status("moria-movie-1", "-1001")
    status_m2 = store.item_status("moria-movie-2", "-1001")
    assert status_m1 == "sent"
    assert status_m2 == "sent"


def test_webhook_moria_series_batch(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr("emby_telegram_bot.webhook.EmbyClient", _CustomEmbyClient)
    monkeypatch.setattr("emby_telegram_bot.webhook.TelegramClient", _FakeTelegramClient)

    db_path = str(tmp_path / "test_history_series.sqlite3")
    store = DeliveryStore(db_path)
    settings = _settings(enable_moria_batch=True)
    app = create_app(settings, store)
    client = app.test_client()

    ep1 = {
        "Id": "moria-ep-1",
        "Type": "Episode",
        "SeriesName": "Arcane",
        "ParentIndexNumber": 2,
        "IndexNumber": 1,
        "Path": "/mnt/16G/PalaEmby-Pilot/Series/Arcane/Season 02/Arcane - S02E01.strm",
        "Container": "strm",
        "MediaStreams": [{"Type": "Video", "Height": 1080}],
    }
    ep2 = {
        "Id": "moria-ep-2",
        "Type": "Episode",
        "SeriesName": "Arcane",
        "ParentIndexNumber": 2,
        "IndexNumber": 2,
        "Path": "/mnt/16G/PalaEmby-Pilot/Series/Arcane/Season 02/Arcane - S02E02.strm",
        "Container": "strm",
        "MediaStreams": [{"Type": "Video", "Height": 1080}],
    }
    _CustomEmbyClient.registered_items["moria-ep-1"] = ep1
    _CustomEmbyClient.registered_items["moria-ep-2"] = ep2

    client.post("/embyhook", json={"Event": "library.new", "Item": ep1})
    client.post("/embyhook", json={"Event": "library.new", "Item": ep2})

    # Nothing sent immediately
    assert len(_FakeTelegramClient.latest.sent_media) == 0

    app.extensions["moria_aggregator"].flush_now()

    # Consolidated series post sent
    assert len(_FakeTelegramClient.latest.sent_media) == 1
    caption = _FakeTelegramClient.latest.sent_media[0][0]
    assert "📺 NUEVAS SERIES Y TEMPORADAS EN MORIA (PalaEmby) · 1 serie actualizada" in caption
    assert "Arcane · Temporada 2" in caption
    assert "E01-E02" in caption

    # Check store history
    assert store.item_status("moria-ep-1", "-1001") == "sent"
    assert store.item_status("moria-ep-2", "-1001") == "sent"
