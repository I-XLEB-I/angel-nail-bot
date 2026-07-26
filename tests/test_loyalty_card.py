from __future__ import annotations

import io

import pytest
from PIL import Image

from src.services.loyalty_card import (
    LoyaltyCardData,
    render_loyalty_card_bytes,
    render_loyalty_minimal_card_bytes,
    render_loyalty_stamps_card_bytes,
)


def test_loyalty_card_renderer_builds_telegram_friendly_png() -> None:
    content = render_loyalty_card_bytes(
        LoyaltyCardData(
            display_name="Мария",
            status_label="Постоянная гостья",
            completed_visits=8,
            progress_visits=3,
            target_visits=5,
            favorite_service="Покрытие гель-лак",
            next_visit="27.07.2026 · 14:00",
        )
    )

    with Image.open(io.BytesIO(content)) as image:
        assert image.format == "PNG"
        assert image.size == (1080, 1350)


def test_loyalty_card_renderer_clamps_progress_safely() -> None:
    content = render_loyalty_card_bytes(
        LoyaltyCardData(
            display_name="Очень длинное имя клиентки для проверки",
            status_label="Гостья",
            completed_visits=20,
            progress_visits=99,
            target_visits=5,
            favorite_service="Маникюр с очень длинным названием услуги",
            next_visit=None,
        )
    )

    assert content.startswith(b"\x89PNG")


@pytest.mark.parametrize(
    "renderer",
    [
        render_loyalty_card_bytes,
        render_loyalty_stamps_card_bytes,
        render_loyalty_minimal_card_bytes,
    ],
)
def test_all_loyalty_visual_concepts_render_as_telegram_images(renderer) -> None:
    content = renderer(
        LoyaltyCardData(
            display_name="Мария",
            status_label="Постоянная гостья",
            completed_visits=8,
            progress_visits=3,
            target_visits=5,
            favorite_service="Покрытие гель-лак",
            next_visit="27.07.2026 · 14:00",
        )
    )

    with Image.open(io.BytesIO(content)) as image:
        assert image.format == "PNG"
        assert image.size == (1080, 1350)
