from __future__ import annotations

import io

from PIL import Image

from src.services import template_media


def configure_media_roots(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(template_media, "TEMPLATE_MEDIA_ROOT", tmp_path / "uploaded")
    monkeypatch.setattr(
        template_media,
        "BUNDLED_TEMPLATE_MEDIA_ROOT",
        tmp_path / "bundled",
    )


def test_template_media_roundtrip(tmp_path, monkeypatch) -> None:
    configure_media_roots(tmp_path, monkeypatch)

    source = Image.new("RGB", (120, 120), color=(210, 190, 180))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")

    path = template_media.save_template_media("booking_confirm", buffer.getvalue())

    assert path.exists()
    assert template_media.has_template_media("booking_confirm") is True
    assert template_media.remove_template_media("booking_confirm") is True
    assert template_media.has_template_media("booking_confirm") is False


def test_template_media_flattens_transparent_images_on_white(tmp_path, monkeypatch) -> None:
    configure_media_roots(tmp_path, monkeypatch)

    source = Image.new("RGBA", (10, 10), color=(0, 0, 0, 0))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")

    path = template_media.save_template_media("transparent", buffer.getvalue())

    with Image.open(path) as saved:
        pixel = saved.convert("RGB").getpixel((0, 0))

    assert pixel == (255, 255, 255)


def test_bundled_media_can_be_disabled_and_restored(tmp_path, monkeypatch) -> None:
    configure_media_roots(tmp_path, monkeypatch)
    bundled_path = template_media.BUNDLED_TEMPLATE_MEDIA_ROOT / "navigation_public.jpg"
    bundled_path.parent.mkdir(parents=True)
    bundled_path.write_bytes(b"bundled-image")

    assert template_media.template_media_source("navigation_public") == "bundled"
    assert template_media.template_media_path("navigation_public") == bundled_path

    assert template_media.remove_template_media("navigation_public") is True
    assert template_media.has_template_media("navigation_public") is False
    assert bundled_path.exists()

    assert template_media.restore_bundled_template_media("navigation_public") is True
    assert template_media.template_media_source("navigation_public") == "bundled"


def test_uploaded_media_overrides_bundled_media(tmp_path, monkeypatch) -> None:
    configure_media_roots(tmp_path, monkeypatch)
    bundled_path = template_media.BUNDLED_TEMPLATE_MEDIA_ROOT / "price.jpg"
    bundled_path.parent.mkdir(parents=True)
    bundled_path.write_bytes(b"bundled-image")

    source = Image.new("RGB", (20, 20), color=(210, 190, 180))
    buffer = io.BytesIO()
    source.save(buffer, format="PNG")
    uploaded_path = template_media.save_template_media("price", buffer.getvalue())

    assert template_media.template_media_source("price") == "uploaded"
    assert template_media.template_media_path("price") == uploaded_path

    assert template_media.restore_bundled_template_media("price") is True
    assert uploaded_path.exists() is False
    assert template_media.template_media_source("price") == "bundled"


def test_greeting_uses_brand_image_as_its_bundled_media(tmp_path, monkeypatch) -> None:
    configure_media_roots(tmp_path, monkeypatch)
    brand_path = template_media.BUNDLED_TEMPLATE_MEDIA_ROOT.parent / "brand.jpg"
    brand_path.write_bytes(b"brand-image")

    assert template_media.template_media_source("greeting_header") == "bundled"
    assert template_media.template_media_path("greeting_header") == brand_path
