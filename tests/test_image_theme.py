from __future__ import annotations

from src.services import image_theme


def test_load_theme_background_falls_back_to_valid_canvas() -> None:
    image = image_theme.load_theme_background(kind="schedule")

    assert image.size == (image_theme.IMAGE_WIDTH, image_theme.IMAGE_HEIGHT)
    assert image.mode == "RGB"


def test_load_theme_background_respects_requested_size() -> None:
    image = image_theme.load_theme_background(kind="schedule", width=600, height=900)

    assert image.size == (600, 900)
    assert image.mode == "RGB"
