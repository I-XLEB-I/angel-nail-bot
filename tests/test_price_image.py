from __future__ import annotations

from src.bot import texts
from src.services.admin_defaults import get_template_definition


def test_price_is_template_media_not_dynamic_image() -> None:
    definition = get_template_definition("price")

    assert definition is not None
    assert definition.supports_media is True
    assert definition.default_content == texts.DEFAULT_PRICE_TEMPLATE
