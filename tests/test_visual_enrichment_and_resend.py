from __future__ import annotations

import pytest
from emby_telegram_bot.config import Settings
from emby_telegram_bot.formatting import (
    build_moria_movies_reports,
    build_moria_series_reports,
    build_caption,
)
from emby_telegram_bot.telegram_client import TelegramClient


def test_moria_report_includes_resolution_audio_trailer_and_tmdb() -> None:
    movie_item = {
        "Id": "101",
        "Name": "Dune: Part Two",
        "ProductionYear": 2024,
        "Overview": "Paul Atreides unites with Chani and the Fremen.",
        "Genres": ["Sci-Fi", "Adventure"],
        "CommunityRating": 8.6,
        "MediaStreams": [
            {"Type": "Video", "Width": 3840, "Height": 2160},
            {"Type": "Audio", "Language": "spa", "DisplayTitle": "Castellano (DTS-HD MA 5.1)"},
            {"Type": "Audio", "Language": "eng", "DisplayTitle": "English (Dolby Atmos)"},
        ],
        "ProviderIds": {"Tmdb": "693134"},
        "RemoteTrailers": [{"Url": "https://www.youtube.com/watch?v=Way9Dexny3w"}],
    }

    reports = build_moria_movies_reports([movie_item])
    assert len(reports) == 1
    text = reports[0][0]

    # Verify quality, audio, trailer and tmdb
    assert "🖥️ 4K" in text
    assert "🔊 Español" in text
    assert "🎬 Tráiler: https://www.youtube.com/watch?v=Way9Dexny3w" in text
    assert "TMDb: https://www.themoviedb.org/movie/693134" in text


def test_telegram_build_item_reply_markup() -> None:
    client = TelegramClient(token="dummy:token", chat_ids=["123"], emby_public_url="https://emby.midominio.com")
    item = {"Id": "9999"}
    markup = client.build_item_reply_markup(item)
    assert markup is not None
    assert len(markup.inline_keyboard) == 1
    button = markup.inline_keyboard[0][0]
    assert button.text == "▶️ Ver en Emby"
    assert button.url == "https://emby.midominio.com/web/index.html#!/item?id=9999"

    # Client without emby_public_url returns None
    client_no_url = TelegramClient(token="dummy:token", chat_ids=["123"], emby_public_url="")
    assert client_no_url.build_item_reply_markup(item) is None


def test_send_resend_item_menu_has_search_button() -> None:
    client = TelegramClient(token="dummy:token", chat_ids=["123"])
    items = [{"Id": f"{i}", "Name": f"Movie {i}", "Type": "Movie"} for i in range(15)]
    
    sent_calls = []
    client.send_text = lambda text, chat_ids=None, reply_markup=None: sent_calls.append((text, reply_markup))

    client.send_resend_item_menu("123", items)
    assert len(sent_calls) == 1
    text, markup = sent_calls[0]
    assert "Elige qué contenido quieres reenviar:" in text
    assert markup is not None
    # 15 items + 1 search button = 16 rows
    assert len(markup.inline_keyboard) == 16
    assert markup.inline_keyboard[-1][0].text == "🔎 Buscar otro para reenviar"
    assert markup.inline_keyboard[-1][0].callback_data == "search:start"


def test_send_admin_menu_has_clear_options() -> None:
    client = TelegramClient(token="dummy:token", chat_ids=["123"])
    sent_calls = []
    client.send_text = lambda text, chat_ids=None, reply_markup=None: sent_calls.append((text, reply_markup))

    client.send_admin_menu("123")
    assert len(sent_calls) == 1
    text, markup = sent_calls[0]
    assert "Panel de Control de Administrador" in text
    
    # Flatten button labels
    labels = [btn.text for row in markup.inline_keyboard for btn in row]
    assert "📦 Elegir de recientes" in labels
    assert "⚡ Reenviar último" in labels
    assert "🔎 Buscar y reenviar" in labels
    assert "📊 Buffer Moria" in labels
    assert "🚀 Forzar Moria" in labels
    assert "🩺 Diagnóstico" in labels
