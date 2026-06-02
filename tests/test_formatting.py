from emby_telegram_bot.formatting import (
    build_activity_caption,
    build_caption,
    build_search_item_caption,
    build_search_results_message,
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


def test_build_caption_movie_includes_overview() -> None:
    item = {
        "Type": "Movie",
        "Name": "Inception",
        "Overview": "Un ladron experto roba secretos del subconsciente durante los suenos.",
    }

    caption = build_caption(item)

    assert "Un ladron experto" in caption


def test_build_caption_movie_uses_media_source_fallbacks() -> None:
    item = {
        "Type": "Movie",
        "Name": "The Smashing Machine",
        "ProductionYear": 2025,
        "Path": "",
        "Container": "",
        "Size": None,
        "MediaSources": [
            {
                "Path": "/media/The.Smashing.Machine.2025.1080p.WEB-DL.mkv",
                "Container": "mkv",
                "Size": 1073741824,
            }
        ],
    }
    caption = build_caption(item)
    assert "WEB-DL" in caption
    assert "1080p" in caption
    assert "MKV" in caption
    assert "1.0 GB" in caption


def test_build_caption_movie_includes_imdb_link() -> None:
    caption = build_caption(
        {
            "Type": "Movie",
            "Name": "Inception",
            "ProviderIds": {"Imdb": "tt1375666"},
        }
    )

    assert "IMDb: https://www.imdb.com/title/tt1375666/" in caption


def test_build_caption_movie_hides_unknown_fields_instead_of_nd() -> None:
    item = {
        "Type": "Movie",
        "Name": "Unknown Source",
    }
    caption = build_caption(item)
    assert "Archivo: Pelicula" in caption
    assert "N/D" not in caption


def test_build_caption_grouped_episodes_uses_safe_wording_and_ranges() -> None:
    item = {
        "Type": "Episode",
        "SeriesName": "The Bear",
        "ParentIndexNumber": 3,
        "MediaSources": [
            {
                "Container": "mkv",
                "MediaStreams": [
                    {"Type": "Video", "Height": 1080, "Codec": "hevc"},
                    {"Type": "Audio", "Language": "spa", "Codec": "eac3", "Channels": 6},
                    {"Type": "Subtitle", "Language": "spa", "IsForced": True},
                ],
            }
        ],
    }

    caption = build_caption(item, season_mode=True, episode_list=["S03E01", "S03E02", "S03E04"])

    assert "Serie actualizada: The Bear T03" in caption
    assert "Temporada completa" not in caption
    assert "Episodios añadidos: E01-E02, E04" in caption
    assert "Video: HEVC" in caption
    assert "Audio: Español · EAC3 · 5.1" in caption
    assert "Subs: Español (forzados)" in caption


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


def test_infer_activity_event_from_emby_pascal_case() -> None:
    assert infer_activity_event_code({"Event": "PlaybackStart"}) == "playback.start"
    assert infer_activity_event_code({"Event": "PlaybackStop"}) == "playback.stop"
    assert infer_activity_event_code({"Event": "SessionStart"}) == "session.start"
    assert is_activity_payload({"Event": "SessionStart", "UserName": "gabba"}) is True


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


def test_build_search_results_message_lists_movies_and_series() -> None:
    message = build_search_results_message(
        "wick",
        [
            {"Type": "Movie", "Name": "John Wick", "ProductionYear": 2014},
            {"Type": "Series", "Name": "Wicked City"},
        ],
    )
    assert "Busqueda: wick" in message
    assert "Pelicula: John Wick (2014)" in message
    assert "Serie: Wicked City" in message


def test_build_search_results_message_empty() -> None:
    message = build_search_results_message("zzzz", [])
    assert "No he encontrado" in message


def test_build_search_item_caption_includes_overview() -> None:
    caption = build_search_item_caption(
        {
            "Type": "Movie",
            "Name": "John Wick",
            "ProductionYear": 2014,
            "Overview": "Un asesino retirado vuelve a la accion.",
        }
    )
    assert "Pelicula: John Wick (2014)" in caption
    assert "Un asesino retirado" in caption


def test_build_search_item_caption_lists_movie_versions() -> None:
    caption = build_search_item_caption(
        {
            "Type": "Movie",
            "Name": "Dune",
            "MediaSources": [
                {
                    "Container": "mkv",
                    "Size": 1073741824,
                    "MediaStreams": [
                        {"Type": "Video", "Height": 2160},
                        {"Type": "Audio", "Language": "spa", "Codec": "ac3", "Channels": 6},
                    ],
                },
                {
                    "Container": "mp4",
                    "Size": 536870912,
                    "MediaStreams": [
                        {"Type": "Video", "Height": 1080},
                        {"Type": "Audio", "Language": "eng", "Codec": "aac", "Channels": 2},
                    ],
                },
            ],
        }
    )
    assert "Versiones disponibles" in caption
    assert "4K" in caption
    assert "1080p" in caption
    assert "Audio: Español" in caption


def test_build_search_item_caption_lists_single_movie_version_details() -> None:
    caption = build_search_item_caption(
        {
            "Type": "Movie",
            "Name": "Arrival",
            "MediaSources": [
                {
                    "Container": "mkv",
                    "Size": 1073741824,
                    "MediaStreams": [
                        {"Type": "Video", "Height": 1080},
                        {"Type": "Audio", "Language": "spa", "Codec": "eac3", "Channels": 6},
                        {"Type": "Audio", "Language": "eng", "Codec": "aac", "Channels": 2},
                    ],
                },
            ],
        }
    )
    assert "Datos de la version" in caption
    assert "1080p" in caption
    assert "MKV" in caption
    assert "Audio: Español" in caption
    assert "Ingles" in caption


def test_build_search_item_caption_lists_series_availability() -> None:
    caption = build_search_item_caption(
        {"Type": "Series", "Name": "Dorohedoro"},
        series_seasons=[
            {
                "IndexNumber": 1,
                "Episodes": [
                    {"IndexNumber": 1},
                    {"IndexNumber": 2},
                    {"IndexNumber": 3},
                ],
            },
            {"IndexNumber": 2, "ChildCount": 4},
        ],
    )
    assert "Temporadas disponibles" in caption
    assert "2 temporadas · 7 episodios disponibles" in caption
    assert "T01: E01-E03" in caption
    assert "T02: 4 episodios" in caption


def test_build_search_item_caption_lists_common_episode_streams_and_imdb() -> None:
    caption = build_search_item_caption(
        {"Type": "Series", "Name": "Dorohedoro", "ProviderIds": {"Imdb": "tt1111111"}},
        series_seasons=[
            {
                "IndexNumber": 1,
                "Episodes": [
                    {
                        "IndexNumber": 1,
                        "MediaSources": [
                            {
                                "MediaStreams": [
                                    {"Type": "Audio", "Language": "spa", "Codec": "eac3", "Channels": 6},
                                    {"Type": "Audio", "Language": "eng", "Codec": "aac", "Channels": 2},
                                    {"Type": "Subtitle", "Language": "spa", "IsForced": True},
                                ],
                            }
                        ],
                    },
                    {
                        "IndexNumber": 2,
                        "MediaSources": [
                            {
                                "MediaStreams": [
                                    {"Type": "Audio", "Language": "spa", "Codec": "eac3", "Channels": 6},
                                    {"Type": "Subtitle", "Language": "spa", "IsForced": True},
                                ],
                            }
                        ],
                    },
                ],
            },
        ],
    )

    assert "T01: E01-E02" in caption
    assert "Audio comun: Español · EAC3 · 5.1" in caption
    assert "Ingles" not in caption
    assert "Subs comunes: Español (forzados)" in caption
    assert "IMDb: https://www.imdb.com/title/tt1111111/" in caption
