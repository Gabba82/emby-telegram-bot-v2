from emby_telegram_bot.formatting import (
    build_caption,
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
    assert "Pelicula: Inception (2010)" in caption
    assert "Rating: 8.8/10" in caption
    assert "WEB-DL" in caption

