from emby_telegram_bot.formatting import (
    build_activity_caption,
    build_caption,
    infer_activity_event_code,
    is_activity_payload,
    release_type_from_filename,
    resolution_from_filename,
)


def test_resolution_from_filename() -> None:
    assert resolution_from_filename("/media/Movie.2024.1080p.mkv") == "1080p"
    assert resolution_from_filename("/media/unknown.file") == "?"


def test_release_type_from_filename() -> None:
    assert release_type_from_filename("/media/Movie.2024.WEB-DL.mkv") == "WEB-DL"
    assert release_type_from_filename("/media/Movie.2024.Custom.mkv") == "?"


def test_build_caption_movie() -> None:
    item = {
        "Type": "Movie",
        "Name": "Inception",
        "ProductionYear": 2010,
        "CommunityRating": 8.8,
        "Path": "/media/Inception.2010.1080p.WEB-DL.mkv",
        "Container": "mkv",
        "Size": 1073741824,
    }
    caption = build_caption(item)
    assert "Película: Inception (2010)" in caption
    assert "Valoración: 8.8/10" in caption
    assert "Archivo: Pelicula" in caption
    assert "WEB-DL" in caption


def test_build_activity_caption_playback() -> None:
    payload = {
        "Event": "playback.start",
        "UserName": "gabba",
        "Client": "Android TV",
        "Item": {"Name": "John Wick"},
    }
    caption = build_activity_caption(payload)
    assert "Reproduccion iniciada" in caption
    assert "Usuario: gabba" in caption
    assert "Contenido: John Wick" in caption
    assert "Cliente: Android TV" in caption


def test_build_activity_caption_episode_includes_series_and_code() -> None:
    payload = {
        "Event": "playback.start",
        "UserName": "gabba",
    }
    item = {
        "Type": "Episode",
        "SeriesName": "Dorohedoro",
        "ParentIndexNumber": 1,
        "IndexNumber": 2,
        "Name": "La batalla",
    }
    caption = build_activity_caption(payload, item_override=item)
    assert "Dorohedoro S01E02 - La batalla" in caption
    assert "Usuario: gabba" in caption


def test_build_activity_caption_ignores_test_event() -> None:
    payload = {"Event": "system.notificationtest", "Title": "Test"}
    assert build_activity_caption(payload) == ""


def test_build_activity_caption_detailed_adds_quality_and_year() -> None:
    payload = {"Event": "playback.start"}
    item = {
        "Type": "Movie",
        "Name": "Inception",
        "ProductionYear": 2010,
        "Path": "/media/Inception.1080p.mkv",
    }
    caption = build_activity_caption(payload, item_override=item, style="detailed")
    assert "Calidad: 1080p" in caption
    assert "Año: 2010" in caption


def test_build_activity_caption_includes_time_when_date_exists() -> None:
    payload = {
        "Event": "playback.start",
        "Date": "2026-04-02T10:06:44.4940000Z",
        "Item": {"Name": "John Wick"},
    }
    caption = build_activity_caption(payload, timezone_name="Europe/Madrid")
    assert "Hora: 12:06" in caption


def test_build_activity_caption_reads_client_from_session() -> None:
    payload = {
        "Event": "playback.pause",
        "Session": {"DeviceName": "Samsung TV App"},
        "Item": {"Name": "Dorohedoro"},
    }
    caption = build_activity_caption(payload)
    assert "Cliente: Samsung TV App" in caption


def test_infer_activity_event_from_title_when_event_missing() -> None:
    payload = {"Title": "Playback paused", "Description": "User paused playback"}
    assert infer_activity_event_code(payload) == "playback.pause"


def test_is_activity_payload_with_user_and_item() -> None:
    payload = {
        "Item": {"Name": "Dorohedoro S01E01"},
        "UserName": "gabba",
        "Client": "Android TV",
    }
    assert is_activity_payload(payload) is True
