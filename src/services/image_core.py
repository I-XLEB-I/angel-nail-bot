"""Minimal image primitives shared by the three dynamic renderers.

The dynamic cards intentionally avoid the stylized gradients, glass panels
and prism overlays the project used before. They now render on a flat
champagne background with a single serif/sans type family and a handful
of small helpers for wrapping and measuring text.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
BRAND_IMAGE_PATH = ASSETS_DIR / "brand.jpg"

BG_COLOR = (243, 232, 222)
INK = (74, 48, 42)
INK_SOFT = (128, 92, 82)
INK_MUTED = (172, 140, 128)
ACCENT = (176, 118, 88)
DIVIDER = (198, 168, 148)

FONT_SERIF_CANDIDATES: tuple[str, ...] = (
    str(FONTS_DIR / "EBGaramond-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
)
FONT_SERIF_ITALIC_CANDIDATES: tuple[str, ...] = (
    str(FONTS_DIR / "EBGaramond-Italic.ttf"),
    str(FONTS_DIR / "EBGaramond-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
)
FONT_SANS_CANDIDATES: tuple[str, ...] = (
    str(FONTS_DIR / "Inter-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def load_font(candidates: Iterable[str], size: int) -> ImageFont.ImageFont:
    """Return the first existing font or Pillow's bitmap default."""
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
) -> tuple[int, int]:
    """Return (width, height) of rendered text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    """Word-wrap a string so each line fits inside max_width."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if text_size(draw, candidate, font)[0] <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def new_canvas(width: int, height: int) -> Image.Image:
    """Create a flat champagne background of the requested size."""
    return Image.new("RGB", (width, height), color=BG_COLOR)


def draw_brand_wordmark(
    draw: ImageDraw.ImageDraw,
    *,
    center_x: int,
    top: int,
    size: int = 68,
    subtitle_size: int = 24,
) -> int:
    """Draw the ANGELS / NAIL SPACE wordmark and return the y below it."""
    main_font = load_font(FONT_SERIF_CANDIDATES, size)
    sub_font = load_font(FONT_SANS_CANDIDATES, subtitle_size)
    main_text = "ANGELS"
    main_w, main_h = text_size(draw, main_text, main_font)
    draw.text((center_x - main_w // 2, top), main_text, fill=INK, font=main_font)
    sub_text = "NAIL SPACE"
    sub_w, sub_h = text_size(draw, sub_text, sub_font)
    sub_y = top + main_h + 12
    draw.text((center_x - sub_w // 2, sub_y), sub_text, fill=INK_SOFT, font=sub_font)
    return sub_y + sub_h


def draw_divider(
    draw: ImageDraw.ImageDraw,
    *,
    y: int,
    center_x: int,
    span: int = 220,
    color: tuple[int, int, int] = DIVIDER,
) -> None:
    """Thin horizontal divider used between title and body."""
    half = span // 2
    draw.line((center_x - half, y, center_x + half, y), fill=color, width=2)
