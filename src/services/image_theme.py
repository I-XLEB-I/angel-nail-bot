from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

logger = logging.getLogger(__name__)

IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1920

# Kept under the historical name because renderers import it directly. The
# palette itself now describes the new champagne / prism direction.
PALETTE_DARK = {
    "bg_top": (124, 86, 80),
    "bg_mid": (193, 157, 146),
    "bg_bottom": (244, 225, 215),
    "text_primary": (255, 247, 242),
    "text_soft": (248, 234, 226),
    "text_muted": (230, 213, 204),
    "ink": (98, 66, 60),
    "ink_soft": (126, 96, 88),
    "ink_muted": (162, 136, 126),
    "accent": (255, 246, 241),
    "accent_soft": (237, 214, 205),
    "sparkle": (255, 252, 249),
    "shadow": (117, 82, 74, 88),
    "panel": (255, 248, 244, 76),
    "panel_border": (255, 251, 247, 214),
    "panel_soft": (255, 248, 243, 44),
    "panel_shadow": (103, 72, 66, 30),
}

DEFAULT_ASSETS_DIR = Path(__file__).resolve().parent.parent.parent / "assets"

_ASSETS_FONTS = DEFAULT_ASSETS_DIR / "fonts"

FONT_CANDIDATES_SERIF = [
    str(_ASSETS_FONTS / "EBGaramond-Bold.ttf"),
    str(_ASSETS_FONTS / "EBGaramond-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/System/Library/Fonts/Supplemental/Didot.ttc",
    "/System/Library/Fonts/Supplemental/Baskerville.ttc",
    "/Library/Fonts/Times New Roman Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]
FONT_CANDIDATES_SCRIPT = [
    str(_ASSETS_FONTS / "EBGaramond-Italic.ttf"),
    str(_ASSETS_FONTS / "EBGaramond-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/SnellRoundhand.ttc",
    "/System/Library/Fonts/Supplemental/Apple Chancery.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf",
    "/Library/Fonts/Times New Roman Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]
FONT_CANDIDATES_BODY = [
    str(_ASSETS_FONTS / "EBGaramond-Regular.ttf"),
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Georgia.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
]


def load_font(candidates: Iterable[str], size: int) -> ImageFont.ImageFont:
    """Return the first available font, or Pillow's bitmap default."""
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except OSError:
                continue
    logger.warning("No TTF font found; falling back to bitmap default.")
    return ImageFont.load_default()


def text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
) -> tuple[int, int]:
    """Return (width, height) of rendered text."""
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def cover_fit(
    image: Image.Image,
    *,
    width: int = IMAGE_WIDTH,
    height: int = IMAGE_HEIGHT,
) -> Image.Image:
    """Resize an image to fully cover the target canvas."""
    src_w, src_h = image.size
    scale = max(width / src_w, height / src_h)
    new_size = (round(src_w * scale), round(src_h * scale))
    resized = image.resize(new_size, Image.LANCZOS)
    left = (new_size[0] - width) // 2
    top = (new_size[1] - height) // 2
    return resized.crop((left, top, left + width, top + height))


def _mix_color(
    start: tuple[int, int, int],
    end: tuple[int, int, int],
    blend: float,
) -> tuple[int, int, int]:
    return tuple(round(start[i] + (end[i] - start[i]) * blend) for i in range(3))


def _build_gradient(
    *,
    width: int = IMAGE_WIDTH,
    height: int = IMAGE_HEIGHT,
) -> Image.Image:
    """Create the default champagne base used across all dynamic images."""
    image = Image.new("RGB", (width, height), color=PALETTE_DARK["bg_top"])
    draw = ImageDraw.Draw(image)
    for y in range(height):
        vertical = y / max(1, height - 1)
        if vertical < 0.42:
            color = _mix_color(
                PALETTE_DARK["bg_top"],
                PALETTE_DARK["bg_mid"],
                vertical / 0.42,
            )
        else:
            color = _mix_color(
                PALETTE_DARK["bg_mid"],
                PALETTE_DARK["bg_bottom"],
                (vertical - 0.42) / 0.58,
            )
        draw.line([(0, y), (width, y)], fill=color)

    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.ellipse(
        (-int(width * 0.12), -int(height * 0.06), int(width * 0.48), int(height * 0.42)),
        fill=(84, 58, 54, 52),
    )
    overlay_draw.ellipse(
        (int(width * 0.46), -int(height * 0.12), int(width * 1.08), int(height * 0.54)),
        fill=(255, 248, 244, 74),
    )
    overlay_draw.ellipse(
        (int(width * 0.58), int(height * 0.42), int(width * 1.12), int(height * 1.04)),
        fill=(255, 245, 238, 58),
    )
    overlay_draw.ellipse(
        (-int(width * 0.08), int(height * 0.58), int(width * 0.36), int(height * 1.06)),
        fill=(116, 86, 80, 34),
    )
    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _draw_prism_burst(
    draw: ImageDraw.ImageDraw,
    *,
    center_x: float,
    center_y: float,
    sweep_deg: float,
    heading_deg: float,
    inner_radius: float,
    outer_radius: float,
    base_width: float,
    colors: list[tuple[int, int, int, int]],
    rays: int,
) -> None:
    """Draw one iridescent radial burst inspired by the repo references."""
    if rays <= 0:
        return
    for index in range(rays):
        position = index / max(1, rays - 1)
        angle = math.radians(heading_deg - sweep_deg / 2 + sweep_deg * position)
        length = outer_radius * (0.68 + 0.32 * ((index % 4) / 3))
        width = base_width * (0.62 + 0.38 * (1 - abs(position - 0.5) * 2))
        inner = inner_radius * (0.2 + 0.12 * ((index + 1) % 3))
        perpendicular = angle + math.pi / 2

        x1 = center_x + math.cos(angle) * inner
        y1 = center_y + math.sin(angle) * inner
        x2 = center_x + math.cos(angle) * length
        y2 = center_y + math.sin(angle) * length

        dx = math.cos(perpendicular) * width / 2
        dy = math.sin(perpendicular) * width / 2
        draw.polygon(
            [
                (x1 - dx * 0.35, y1 - dy * 0.35),
                (x1 + dx * 0.35, y1 + dy * 0.35),
                (x2 + dx, y2 + dy),
                (x2 - dx, y2 - dy),
            ],
            fill=colors[index % len(colors)],
        )


def _build_prism_layer(size: tuple[int, int]) -> Image.Image:
    """Create the airy prism flares that define the new brand direction."""
    width, height = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    colors = [
        (255, 246, 240, 82),
        (255, 255, 255, 90),
        (255, 224, 192, 68),
        (214, 232, 255, 62),
        (255, 220, 235, 56),
    ]
    _draw_prism_burst(
        draw,
        center_x=width * 0.08,
        center_y=height * 0.43,
        sweep_deg=102,
        heading_deg=0,
        inner_radius=width * 0.02,
        outer_radius=max(width, height) * 0.26,
        base_width=max(20, width * 0.018),
        colors=colors,
        rays=14,
    )
    _draw_prism_burst(
        draw,
        center_x=width * 0.94,
        center_y=height * 0.63,
        sweep_deg=108,
        heading_deg=180,
        inner_radius=width * 0.02,
        outer_radius=max(width, height) * 0.28,
        base_width=max(22, width * 0.02),
        colors=colors[1:] + colors[:1],
        rays=15,
    )
    _draw_prism_burst(
        draw,
        center_x=width * 0.48,
        center_y=height * 0.26,
        sweep_deg=46,
        heading_deg=92,
        inner_radius=width * 0.01,
        outer_radius=max(width, height) * 0.12,
        base_width=max(14, width * 0.012),
        colors=[(255, 255, 255, 42), (255, 236, 222, 38)],
        rays=8,
    )
    return layer.filter(ImageFilter.GaussianBlur(radius=15))


def draw_soft_orbs(image: Image.Image, *, count: int = 6, seed: int = 0) -> None:
    """Add milky blurred blooms behind the layout."""
    specs = [
        (0.18, 0.18, 180, 40),
        (0.82, 0.22, 220, 34),
        (0.30, 0.62, 210, 28),
        (0.78, 0.82, 280, 32),
        (0.12, 0.86, 160, 24),
        (0.56, 0.44, 230, 18),
        (0.90, 0.08, 120, 20),
        (0.10, 0.68, 180, 20),
    ]
    layer = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    palette = [
        (255, 247, 242),
        (246, 231, 225),
        (255, 255, 255),
        (235, 210, 201),
    ]
    for index, (x, y, radius, alpha) in enumerate(specs[seed : seed + count]):
        color = palette[index % len(palette)]
        center_x = int(image.width * x)
        center_y = int(image.height * y)
        draw.ellipse(
            (
                center_x - radius,
                center_y - radius,
                center_x + radius,
                center_y + radius,
            ),
            fill=(*color, alpha),
        )
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(radius=56)))


def _build_silk_layer(size: tuple[int, int]) -> Image.Image:
    """Create soft silk-like waves so plain backgrounds still feel intentional."""
    width, height = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for index in range(6):
        top = height * (0.18 + index * 0.12)
        draw.arc(
            (
                -width * 0.12,
                top - height * 0.12,
                width * 1.12,
                top + height * 0.18,
            ),
            start=198,
            end=344,
            fill=(255, 247, 243, max(10, 26 - index * 3)),
            width=max(2, width // 220),
        )
    return layer.filter(ImageFilter.GaussianBlur(radius=9))


def _apply_vignette(canvas: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = canvas.size
    draw.ellipse(
        (-int(width * 0.08), -int(height * 0.06), int(width * 0.22), int(height * 0.22)),
        fill=(86, 60, 54, 22),
    )
    draw.ellipse(
        (-int(width * 0.02), int(height * 0.78), int(width * 0.18), int(height * 1.02)),
        fill=(94, 68, 61, 18),
    )
    for inset, alpha in [(0, 18), (70, 12), (150, 8)]:
        draw.rounded_rectangle(
            (inset, inset, width - inset, height - inset),
            radius=120,
            outline=(114, 80, 72, alpha),
            width=42,
        )
    return Image.alpha_composite(canvas, overlay.filter(ImageFilter.GaussianBlur(radius=28)))


def stylize_theme_background(base: Image.Image) -> Image.Image:
    """Normalize custom and generated backgrounds into the shared luxury look."""
    image = base.filter(ImageFilter.GaussianBlur(radius=1.3))
    image = ImageEnhance.Color(image).enhance(0.78)
    image = ImageEnhance.Brightness(image).enhance(1.12)
    image = ImageEnhance.Contrast(image).enhance(0.86)
    gradient = _build_gradient(width=image.width, height=image.height)
    image = Image.blend(image.convert("RGB"), gradient, 0.54)
    canvas = image.convert("RGBA")
    canvas = Image.alpha_composite(canvas, Image.new("RGBA", canvas.size, (255, 245, 239, 18)))
    canvas = Image.alpha_composite(canvas, _build_silk_layer(canvas.size))
    canvas = Image.alpha_composite(canvas, _build_prism_layer(canvas.size))
    draw_soft_orbs(canvas, count=5, seed=0)
    return _apply_vignette(canvas).convert("RGB")


def draw_glass_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    radius: int = 44,
    fill: tuple[int, int, int, int] | None = None,
    outline: tuple[int, int, int, int] | None = None,
    width: int = 2,
) -> None:
    """Draw the shared translucent frosted panel used on every image."""
    left, top, right, bottom = box
    shadow_offset = max(12, radius // 3)
    draw.rounded_rectangle(
        (left + 6, top + shadow_offset, right + 6, bottom + shadow_offset),
        radius=radius + 4,
        fill=PALETTE_DARK["panel_shadow"],
    )
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=fill or PALETTE_DARK["panel"],
        outline=outline or PALETTE_DARK["panel_border"],
        width=width,
    )
    inset = max(8, width * 4)
    draw.rounded_rectangle(
        (left + inset, top + inset, right - inset, bottom - inset),
        radius=max(12, radius - inset),
        fill=PALETTE_DARK["panel_soft"],
        outline=(255, 255, 255, 72),
        width=1,
    )
    highlight_y = top + max(18, radius // 2)
    draw.line(
        (left + radius, highlight_y, right - radius, highlight_y),
        fill=(255, 255, 255, 128),
        width=2,
    )
    draw.line(
        (left + radius + 30, bottom - max(18, radius // 2), right - radius - 30, bottom - 18),
        fill=(227, 196, 184, 54),
        width=1,
    )


def draw_soft_badge(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int, int] | None = None,
    outline: tuple[int, int, int, int] | None = None,
) -> None:
    """Draw a compact pill used for chips, tags, and compact stat cards."""
    radius = max(12, (box[3] - box[1]) // 2)
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=fill or (255, 249, 245, 98),
        outline=outline or (255, 252, 249, 188),
        width=1,
    )


def draw_dotted_leader(
    draw: ImageDraw.ImageDraw,
    *,
    start_x: int,
    end_x: int,
    y: int,
    fill: tuple[int, int, int, int] | None = None,
    dot: int = 2,
    gap: int = 10,
) -> None:
    """Draw dotted leader lines between labels and values."""
    color = fill or (*PALETTE_DARK["ink_muted"], 148)
    x = start_x
    while x < end_x:
        draw.ellipse((x, y - dot, x + dot * 2, y + dot), fill=color)
        x += gap


def load_theme_background(
    *,
    kind: str = "schedule",
    width: int = IMAGE_WIDTH,
    height: int = IMAGE_HEIGHT,
) -> Image.Image:
    """Synthesize the shared styled background used by the branded text card."""
    del kind
    return stylize_theme_background(_build_gradient(width=width, height=height))


def tracked_text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    *,
    tracking: int,
) -> tuple[int, int]:
    """Return the size of manually tracked text."""
    widths = []
    max_height = 0
    for character in text:
        char_width, char_height = text_size(draw, character, font)
        widths.append(char_width)
        max_height = max(max_height, char_height)
    if not widths:
        return 0, 0
    return sum(widths) + tracking * (len(widths) - 1), max_height


def draw_tracked_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    center_x: int,
    top: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    tracking: int,
) -> tuple[int, int]:
    """Draw tracked text centered horizontally and return its size."""
    width, height = tracked_text_size(draw, text, font, tracking=tracking)
    cursor_x = center_x - width // 2
    for character in text:
        draw.text((cursor_x, top), character, fill=fill, font=font)
        char_width, _ = text_size(draw, character, font)
        cursor_x += char_width + tracking
    return width, height


def fit_tracked_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    candidates: Iterable[str] = FONT_CANDIDATES_SERIF,
    initial_size: int,
    max_width: int,
    min_size: int = 32,
) -> tuple[ImageFont.ImageFont, int, tuple[int, int]]:
    """Find a tracked font that fits inside max_width."""
    size = initial_size
    while size >= min_size:
        font = load_font(candidates, size)
        tracking = max(3, size // 12)
        width, height = tracked_text_size(draw, text, font, tracking=tracking)
        if width <= max_width:
            return font, tracking, (width, height)
        size -= 4
    font = load_font(candidates, min_size)
    tracking = max(3, min_size // 12)
    return font, tracking, tracked_text_size(draw, text, font, tracking=tracking)


def _draw_sparkle(
    draw: ImageDraw.ImageDraw,
    *,
    center_x: int,
    center_y: int,
    size: int = 10,
    fill: tuple[int, int, int, int] | None = None,
) -> None:
    color = fill or (*PALETTE_DARK["accent"], 225)
    draw.line((center_x - size, center_y, center_x + size, center_y), fill=color, width=1)
    draw.line((center_x, center_y - size, center_x, center_y + size), fill=color, width=1)
    diagonal = max(4, size - 3)
    draw.line(
        (center_x - diagonal, center_y - diagonal, center_x + diagonal, center_y + diagonal),
        fill=(*PALETTE_DARK["accent"], 132),
        width=1,
    )
    draw.line(
        (center_x - diagonal, center_y + diagonal, center_x + diagonal, center_y - diagonal),
        fill=(*PALETTE_DARK["accent"], 132),
        width=1,
    )


def draw_accent_divider(
    draw: ImageDraw.ImageDraw,
    *,
    y: int,
    center_x: int = IMAGE_WIDTH // 2,
    span: int = 460,
) -> None:
    """Draw the shared thin divider with a small center sparkle."""
    half = span // 2
    draw.line(
        (center_x - half, y, center_x + half, y),
        fill=(*PALETTE_DARK["accent"], 170),
        width=1,
    )
    _draw_sparkle(draw, center_x=center_x, center_y=y, size=8)


def draw_header_serif(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    y: int,
    max_width: int,
    center_x: int = IMAGE_WIDTH // 2,
    initial_size: int = 104,
) -> tuple[int, int]:
    """Draw a centered serif header with subtle shadow and auto-shrink."""
    header_text = " ".join(text.strip().upper().split())
    font, tracking, (_, height) = fit_tracked_font(
        draw,
        header_text,
        initial_size=initial_size,
        max_width=max_width,
    )
    draw_tracked_text(
        draw,
        header_text,
        center_x=center_x,
        top=y + 5,
        font=font,
        fill=(*PALETTE_DARK["shadow"][:3], 124),
        tracking=tracking,
    )
    return draw_tracked_text(
        draw,
        header_text,
        center_x=center_x,
        top=y,
        font=font,
        fill=(*PALETTE_DARK["text_primary"], 245),
        tracking=tracking,
    ) or (0, height)


def draw_footer_brand(
    draw: ImageDraw.ImageDraw,
    text: str = "ANGELS NAIL SPACE",
    *,
    y_bottom_offset: int = 118,
    center_x: int = IMAGE_WIDTH // 2,
    image_height: int = IMAGE_HEIGHT,
) -> None:
    """Draw the shared ANGELS NAIL SPACE footer."""
    cleaned = " ".join(text.split()).upper() or "ANGELS NAIL SPACE"
    main, _, sub = cleaned.partition(" NAIL ")
    subtitle = f"NAIL {sub}" if sub else "NAIL SPACE"
    font, tracking, (_, height) = fit_tracked_font(
        draw,
        main,
        initial_size=52,
        max_width=430,
        min_size=28,
    )
    y = image_height - y_bottom_offset - height - 38
    draw_tracked_text(
        draw,
        main,
        center_x=center_x,
        top=y + 4,
        font=font,
        fill=(*PALETTE_DARK["shadow"][:3], 92),
        tracking=tracking,
    )
    draw_tracked_text(
        draw,
        main,
        center_x=center_x,
        top=y,
        font=font,
        fill=(*PALETTE_DARK["text_primary"], 226),
        tracking=tracking,
    )
    subtitle_font = load_font(FONT_CANDIDATES_BODY, 28)
    subtitle_w, _ = text_size(draw, subtitle, subtitle_font)
    draw.text(
        (center_x - subtitle_w // 2, y + height + 10),
        subtitle,
        fill=(*PALETTE_DARK["text_muted"], 210),
        font=subtitle_font,
    )


def _draw_wing_mark(
    draw: ImageDraw.ImageDraw,
    *,
    center_x: int,
    top: int,
    width: int = 118,
    height: int = 30,
    fill: tuple[int, int, int, int] | None = None,
) -> None:
    color = fill or (*PALETTE_DARK["text_primary"], 232)
    half = width // 2
    for shrink, y_shift in [(0, 0), (16, 4), (30, 8)]:
        left_box = (
            center_x - half + shrink,
            top + y_shift,
            center_x - 4,
            top + height + y_shift,
        )
        right_box = (
            center_x + 4,
            top + y_shift,
            center_x + half - shrink,
            top + height + y_shift,
        )
        draw.arc(left_box, start=200, end=330, fill=color, width=1)
        draw.arc(right_box, start=210, end=340, fill=color, width=1)
    draw.line(
        (center_x - 8, top + height - 2, center_x + 8, top + height - 2),
        fill=(*PALETTE_DARK["accent"], 180),
        width=1,
    )


def draw_angels_brand(
    draw: ImageDraw.ImageDraw,
    *,
    top: int = 118,
    center_x: int = IMAGE_WIDTH // 2,
    main_size: int = 104,
    max_width: int = 640,
) -> int:
    """Draw the main ANGELS / NAIL SPACE lockup and return the next y."""
    _draw_wing_mark(draw, center_x=center_x, top=max(0, top - 46), width=max_width // 5)
    font, tracking, (_, height) = fit_tracked_font(
        draw,
        "ANGELS",
        initial_size=main_size,
        max_width=max_width,
        min_size=42,
    )
    draw_tracked_text(
        draw,
        "ANGELS",
        center_x=center_x,
        top=top + 6,
        font=font,
        fill=(*PALETTE_DARK["shadow"][:3], 132),
        tracking=tracking,
    )
    draw_tracked_text(
        draw,
        "ANGELS",
        center_x=center_x,
        top=top,
        font=font,
        fill=(*PALETTE_DARK["text_primary"], 246),
        tracking=tracking,
    )
    subtitle = "NAIL SPACE"
    subtitle_font = load_font(FONT_CANDIDATES_BODY, max(26, main_size // 4))
    subtitle_w, subtitle_h = text_size(draw, subtitle, subtitle_font)
    subtitle_y = top + height + 12
    draw.text(
        (center_x - subtitle_w // 2, subtitle_y),
        subtitle,
        fill=(*PALETTE_DARK["text_soft"], 222),
        font=subtitle_font,
    )
    return subtitle_y + subtitle_h


def draw_section_title(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    top: int,
    center_x: int = IMAGE_WIDTH // 2,
    initial_size: int = 60,
    max_width: int = 760,
) -> int:
    """Draw a shared centered title with the new divider treatment."""
    _, height = draw_header_serif(
        draw,
        text,
        y=top,
        max_width=max_width,
        center_x=center_x,
        initial_size=initial_size,
    )
    line_y = top + height + 32
    draw_accent_divider(draw, y=line_y, center_x=center_x)
    return line_y + 34
