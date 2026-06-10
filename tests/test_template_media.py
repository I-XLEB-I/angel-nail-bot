from __future__ import annotations

import io

from PIL import Image

from src.services import template_media


def test_template_media_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(template_media, "TEMPLATE_MEDIA_ROOT", tmp_path)

    source = Image.new("RGB", (120, 120), color=(210, 190, 180))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")

    path = template_media.save_template_media("booking_confirm", buffer.getvalue())

    assert path.exists()
    assert template_media.has_template_media("booking_confirm") is True
    assert template_media.remove_template_media("booking_confirm") is True
    assert template_media.has_template_media("booking_confirm") is False


def test_template_media_flattens_transparent_images_on_white(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(template_media, "TEMPLATE_MEDIA_ROOT", tmp_path)

    source = Image.new("RGBA", (10, 10), color=(0, 0, 0, 0))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")

    path = template_media.save_template_media("transparent", buffer.getvalue())

    with Image.open(path) as saved:
        pixel = saved.convert("RGB").getpixel((0, 0))

    assert pixel == (255, 255, 255)
