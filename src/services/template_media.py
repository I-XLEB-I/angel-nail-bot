from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

from src.services.image_theme import DEFAULT_ASSETS_DIR

TEMPLATE_MEDIA_ROOT = DEFAULT_ASSETS_DIR / "template_media"


def _normalize_key(key: str) -> str:
    return key.strip().replace("/", "_").replace("\\", "_")


def template_media_path(key: str) -> Path:
    """Return the filesystem path for one template attachment image."""
    return TEMPLATE_MEDIA_ROOT / f"{_normalize_key(key)}.jpg"


def has_template_media(key: str) -> bool:
    """Return whether a template image attachment exists."""
    return template_media_path(key).exists()


def remove_template_media(key: str) -> bool:
    """Delete a template attachment image if it exists."""
    path = template_media_path(key)
    if not path.exists():
        return False
    path.unlink()
    return True


def save_template_media(key: str, content: bytes) -> Path:
    """Persist a template attachment image as a normalized JPEG."""
    path = template_media_path(key)
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
    return path
