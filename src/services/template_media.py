from __future__ import annotations

import io
from pathlib import Path
from typing import Literal

from PIL import Image

from src.services.image_theme import DEFAULT_ASSETS_DIR

BUNDLED_TEMPLATE_MEDIA_ROOT = DEFAULT_ASSETS_DIR / "template_media"
TEMPLATE_MEDIA_ROOT = DEFAULT_ASSETS_DIR.parent / "data" / "template_media"
TemplateMediaSource = Literal["uploaded", "bundled"]


def _normalize_key(key: str) -> str:
    return key.strip().replace("/", "_").replace("\\", "_")


def _uploaded_media_path(key: str) -> Path:
    return TEMPLATE_MEDIA_ROOT / f"{_normalize_key(key)}.jpg"


def _bundled_media_path(key: str) -> Path:
    return BUNDLED_TEMPLATE_MEDIA_ROOT / f"{_normalize_key(key)}.jpg"


def _disabled_marker_path(key: str) -> Path:
    return TEMPLATE_MEDIA_ROOT / f"{_normalize_key(key)}.disabled"


def template_media_source(key: str) -> TemplateMediaSource | None:
    """Return where the effective template image comes from."""
    if _uploaded_media_path(key).exists():
        return "uploaded"
    if _disabled_marker_path(key).exists():
        return None
    if _bundled_media_path(key).exists():
        return "bundled"
    return None


def template_media_path(key: str) -> Path:
    """Return the effective filesystem path for one template image."""
    if template_media_source(key) == "bundled":
        return _bundled_media_path(key)
    return _uploaded_media_path(key)


def has_template_media(key: str) -> bool:
    """Return whether an effective template image exists."""
    return template_media_source(key) is not None


def has_bundled_template_media(key: str) -> bool:
    """Return whether the application ships a default image for this template."""
    return _bundled_media_path(key).exists()


def remove_template_media(key: str) -> bool:
    """Disable the current image without mutating bundled application assets."""
    if not has_template_media(key):
        return False
    uploaded_path = _uploaded_media_path(key)
    uploaded_path.unlink(missing_ok=True)
    if has_bundled_template_media(key):
        marker_path = _disabled_marker_path(key)
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.touch()
    return True


def restore_bundled_template_media(key: str) -> bool:
    """Restore the application-provided image after an override or deletion."""
    if not has_bundled_template_media(key):
        return False
    _uploaded_media_path(key).unlink(missing_ok=True)
    _disabled_marker_path(key).unlink(missing_ok=True)
    return True


def save_template_media(key: str, content: bytes) -> Path:
    """Persist an admin-uploaded image in the durable data volume."""
    path = _uploaded_media_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(io.BytesIO(content)) as raw:
        raw.load()
        has_alpha = raw.mode in {"RGBA", "LA"} or (
            raw.mode == "P" and "transparency" in raw.info
        )
        if has_alpha:
            rgba = raw.convert("RGBA")
            image = Image.new("RGB", rgba.size, (255, 255, 255))
            image.paste(rgba, mask=rgba.getchannel("A"))
        else:
            image = raw.convert("RGB")
    image.save(path, format="JPEG", quality=92, optimize=True)
    _disabled_marker_path(key).unlink(missing_ok=True)
    return path
