from telegram.constants import ParseMode

from emby_telegram_bot.formatting import EXPANDABLE_SECTION_END, EXPANDABLE_SECTION_START
from emby_telegram_bot.telegram_client import format_caption_for_telegram


def test_format_caption_for_telegram_uses_expandable_blockquote() -> None:
    caption = (
        f"Pelicula: Arrival\n\nSinopsis:\n"
        f"{EXPANDABLE_SECTION_START}Una linguista intenta comunicarse con visitantes extraterrestres."
        f"{EXPANDABLE_SECTION_END}\nAudio: Español"
    )

    formatted, parse_mode = format_caption_for_telegram(caption)

    assert parse_mode == ParseMode.HTML
    assert EXPANDABLE_SECTION_START not in formatted
    assert EXPANDABLE_SECTION_END not in formatted
    assert "<blockquote expandable>Una linguista" in formatted
    assert "</blockquote>" in formatted
    assert "Audio: Español" in formatted


def test_format_caption_for_telegram_escapes_html_inside_expandable_blockquote() -> None:
    caption = f"Sinopsis:\n{EXPANDABLE_SECTION_START}A < B & C > D{EXPANDABLE_SECTION_END}"

    formatted, parse_mode = format_caption_for_telegram(caption)

    assert parse_mode == ParseMode.HTML
    assert "A &lt; B &amp; C &gt; D" in formatted
