from __future__ import annotations

from PIL import ImageDraw

from src.services import image_theme
from src.services.image_core import (
    INK,
    INK_SOFT,
    draw_brand_wordmark,
    new_canvas,
)


def test_load_theme_background_falls_back_to_valid_canvas() -> None:
    image = image_theme.load_theme_background(kind="schedule")

    assert image.size == (image_theme.IMAGE_WIDTH, image_theme.IMAGE_HEIGHT)
    assert image.mode == "RGB"


def test_load_theme_background_respects_requested_size() -> None:
    image = image_theme.load_theme_background(kind="schedule", width=600, height=900)

    assert image.size == (600, 900)
    assert image.mode == "RGB"


def test_brand_wordmark_keeps_subtitle_below_main_letters() -> None:
    image = new_canvas(600, 300)
    draw = ImageDraw.Draw(image)

    bottom = draw_brand_wordmark(
        draw,
        center_x=300,
        top=40,
        size=68,
        subtitle_size=22,
    )

    main_rows = [
        y for y in range(image.height) for x in range(image.width) if image.getpixel((x, y)) == INK
    ]
    subtitle_rows = [
        y
        for y in range(image.height)
        for x in range(image.width)
        if image.getpixel((x, y)) == INK_SOFT
    ]

    assert main_rows
    assert subtitle_rows
    assert min(subtitle_rows) - max(main_rows) >= 12
    assert bottom > max(subtitle_rows)
