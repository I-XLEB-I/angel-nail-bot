"""Dynamic client loyalty-card renderer used by the admin-only concept preview."""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from src.services.image_core import (
    ACCENT,
    DIVIDER,
    FONT_SANS_CANDIDATES,
    FONT_SERIF_CANDIDATES,
    INK,
    INK_MUTED,
    INK_SOFT,
    draw_brand_wordmark,
    load_font,
    new_canvas,
    text_size,
    wrap_text,
)

CARD_WIDTH = 1080
CARD_HEIGHT = 1350
MARGIN_X = 78
PANEL_FILL = (250, 242, 236)
PANEL_HIGHLIGHT = (255, 250, 246)


@dataclass(frozen=True, slots=True)
class LoyaltyCardData:
    """Display-only values for one rendered loyalty-card image."""

    display_name: str
    status_label: str
    completed_visits: int
    progress_visits: int
    target_visits: int
    favorite_service: str
    next_visit: str | None
    reward_label: str = "следующий бонус"


def _visit_word(value: int) -> str:
    normalized = abs(value)
    tail = normalized % 100
    if 11 <= tail <= 14:
        return "визитов"
    last = normalized % 10
    if last == 1:
        return "визит"
    if last in {2, 3, 4}:
        return "визита"
    return "визитов"


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    candidates: tuple[str, ...],
    initial_size: int,
    min_size: int,
    max_width: int,
) -> ImageFont.ImageFont:
    size = initial_size
    while size > min_size:
        font = load_font(candidates, size)
        if text_size(draw, text, font)[0] <= max_width:
            return font
        size -= 2
    return load_font(candidates, min_size)


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    center_x: int,
    top: int,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int],
) -> int:
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = center_x - width // 2 - bbox[0]
    y = top - bbox[1]
    draw.text((x, y), text, fill=fill, font=font)
    return top + height


def _draw_stat_panel(
    draw: ImageDraw.ImageDraw,
    *,
    box: tuple[int, int, int, int],
    label: str,
    value: str,
) -> None:
    draw.rounded_rectangle(
        box,
        radius=30,
        fill=PANEL_FILL,
        outline=DIVIDER,
        width=2,
    )
    left, top, right, _ = box
    label_font = load_font(FONT_SANS_CANDIDATES, 24)
    value_font = load_font(FONT_SERIF_CANDIDATES, 38)
    draw.text((left + 30, top + 26), label.upper(), fill=INK_MUTED, font=label_font)
    lines = wrap_text(
        draw,
        value,
        font=value_font,
        max_width=right - left - 60,
    )[:2]
    cursor_y = top + 72
    for line in lines:
        draw.text((left + 30, cursor_y), line, fill=INK, font=value_font)
        cursor_y += text_size(draw, line, value_font)[1] + 4


def render_loyalty_card_bytes(data: LoyaltyCardData) -> bytes:
    """Render a compact 4:5 PNG profile card from supplied client data."""
    canvas = new_canvas(CARD_WIDTH, CARD_HEIGHT)
    draw = ImageDraw.Draw(canvas)
    center_x = CARD_WIDTH // 2

    draw.rounded_rectangle(
        (38, 38, CARD_WIDTH - 38, CARD_HEIGHT - 38),
        radius=56,
        outline=ACCENT,
        width=3,
    )
    draw.rounded_rectangle(
        (52, 52, CARD_WIDTH - 52, CARD_HEIGHT - 52),
        radius=48,
        outline=(226, 199, 184),
        width=1,
    )

    brand_bottom = draw_brand_wordmark(
        draw,
        center_x=center_x,
        top=88,
        size=68,
        subtitle_size=22,
    )
    eyebrow_font = load_font(FONT_SANS_CANDIDATES, 23)
    _draw_centered(
        draw,
        "ЛИЧНАЯ КАРТА ГОСТЬИ",
        center_x=center_x,
        top=brand_bottom + 30,
        font=eyebrow_font,
        fill=INK_MUTED,
    )

    safe_name = " ".join(data.display_name.split())[:40] or "Гостья"
    name_font = _fit_font(
        draw,
        safe_name,
        candidates=FONT_SERIF_CANDIDATES,
        initial_size=76,
        min_size=44,
        max_width=CARD_WIDTH - MARGIN_X * 2,
    )
    name_bottom = _draw_centered(
        draw,
        safe_name,
        center_x=center_x,
        top=brand_bottom + 78,
        font=name_font,
        fill=INK,
    )
    status_font = load_font(FONT_SANS_CANDIDATES, 28)
    status_bottom = _draw_centered(
        draw,
        data.status_label,
        center_x=center_x,
        top=name_bottom + 14,
        font=status_font,
        fill=INK_SOFT,
    )

    progress_top = status_bottom + 48
    progress_box = (MARGIN_X, progress_top, CARD_WIDTH - MARGIN_X, progress_top + 290)
    draw.rounded_rectangle(
        progress_box,
        radius=38,
        fill=PANEL_HIGHLIGHT,
        outline=DIVIDER,
        width=2,
    )
    label_font = load_font(FONT_SANS_CANDIDATES, 25)
    draw.text(
        (progress_box[0] + 38, progress_top + 34),
        data.reward_label.upper(),
        fill=INK_MUTED,
        font=label_font,
    )

    target = max(1, data.target_visits)
    progress = max(0, min(data.progress_visits, target))
    remaining = max(0, target - progress)
    progress_label = "Бонус доступен" if remaining == 0 else f"Осталось {remaining}"
    progress_font = load_font(FONT_SERIF_CANDIDATES, 46)
    progress_width, _ = text_size(draw, progress_label, progress_font)
    draw.text(
        (progress_box[2] - 38 - progress_width, progress_top + 26),
        progress_label,
        fill=INK,
        font=progress_font,
    )

    marker_count = min(target, 8)
    filled_markers = min(marker_count, round(marker_count * progress / target))
    marker_gap = 18
    available_width = progress_box[2] - progress_box[0] - 76
    marker_width = (available_width - marker_gap * (marker_count - 1)) // marker_count
    marker_top = progress_top + 118
    marker_height = 58
    for index in range(marker_count):
        left = progress_box[0] + 38 + index * (marker_width + marker_gap)
        right = left + marker_width
        is_filled = index < filled_markers
        draw.rounded_rectangle(
            (left, marker_top, right, marker_top + marker_height),
            radius=marker_height // 2,
            fill=ACCENT if is_filled else PANEL_FILL,
            outline=ACCENT,
            width=2,
        )

    counter_font = load_font(FONT_SANS_CANDIDATES, 27)
    counter = f"{progress} из {target} {_visit_word(target)} в текущем цикле"
    draw.text(
        (progress_box[0] + 38, marker_top + marker_height + 30),
        counter,
        fill=INK_SOFT,
        font=counter_font,
    )

    stats_top = progress_box[3] + 30
    gap = 22
    panel_width = (CARD_WIDTH - MARGIN_X * 2 - gap) // 2
    _draw_stat_panel(
        draw,
        box=(MARGIN_X, stats_top, MARGIN_X + panel_width, stats_top + 176),
        label="Завершено",
        value=(f"{max(0, data.completed_visits)} {_visit_word(max(0, data.completed_visits))}"),
    )
    _draw_stat_panel(
        draw,
        box=(
            MARGIN_X + panel_width + gap,
            stats_top,
            CARD_WIDTH - MARGIN_X,
            stats_top + 176,
        ),
        label="Любимая услуга",
        value=data.favorite_service or "Пока узнаём",
    )

    next_top = stats_top + 206
    next_box = (MARGIN_X, next_top, CARD_WIDTH - MARGIN_X, next_top + 156)
    draw.rounded_rectangle(
        next_box,
        radius=30,
        fill=PANEL_FILL,
        outline=DIVIDER,
        width=2,
    )
    draw.text(
        (next_box[0] + 34, next_top + 28),
        "БЛИЖАЙШАЯ ЗАПИСЬ",
        fill=INK_MUTED,
        font=label_font,
    )
    next_font = load_font(FONT_SERIF_CANDIDATES, 42)
    draw.text(
        (next_box[0] + 34, next_top + 73),
        data.next_visit or "Пока без записи",
        fill=INK,
        font=next_font,
    )

    footer_font = load_font(FONT_SANS_CANDIDATES, 24)
    _draw_centered(
        draw,
        "Карта обновляется после каждого завершённого визита",
        center_x=center_x,
        top=CARD_HEIGHT - 102,
        font=footer_font,
        fill=INK_MUTED,
    )

    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_loyalty_stamps_card_bytes(data: LoyaltyCardData) -> bytes:
    """Render a simple visit-stamp card focused on one understandable reward cycle."""
    canvas = new_canvas(CARD_WIDTH, CARD_HEIGHT)
    draw = ImageDraw.Draw(canvas)
    center_x = CARD_WIDTH // 2

    draw.rounded_rectangle(
        (38, 38, CARD_WIDTH - 38, CARD_HEIGHT - 38),
        radius=56,
        fill=PANEL_HIGHLIGHT,
        outline=ACCENT,
        width=3,
    )
    brand_bottom = draw_brand_wordmark(
        draw,
        center_x=center_x,
        top=82,
        size=64,
        subtitle_size=21,
    )
    eyebrow_font = load_font(FONT_SANS_CANDIDATES, 23)
    heading_bottom = _draw_centered(
        draw,
        "ВИЗИТЫ ДО ПОДАРКА",
        center_x=center_x,
        top=brand_bottom + 42,
        font=eyebrow_font,
        fill=INK_MUTED,
    )

    safe_name = " ".join(data.display_name.split())[:40] or "Гостья"
    name_font = _fit_font(
        draw,
        safe_name,
        candidates=FONT_SERIF_CANDIDATES,
        initial_size=72,
        min_size=42,
        max_width=CARD_WIDTH - MARGIN_X * 2,
    )
    name_bottom = _draw_centered(
        draw,
        safe_name,
        center_x=center_x,
        top=heading_bottom + 34,
        font=name_font,
        fill=INK,
    )

    target = max(1, min(data.target_visits, 8))
    progress = max(0, min(data.progress_visits, target))
    remaining = max(0, target - progress)
    progress_font = load_font(FONT_SERIF_CANDIDATES, 104)
    progress_bottom = _draw_centered(
        draw,
        f"{progress} / {target}",
        center_x=center_x,
        top=name_bottom + 46,
        font=progress_font,
        fill=INK,
    )
    caption_font = load_font(FONT_SANS_CANDIDATES, 27)
    caption_bottom = _draw_centered(
        draw,
        "визитов в текущем цикле",
        center_x=center_x,
        top=progress_bottom + 8,
        font=caption_font,
        fill=INK_SOFT,
    )

    marker_gap = 24 if target > 5 else 34
    marker_available_width = CARD_WIDTH - (MARGIN_X + 24) * 2
    marker_diameter = min(
        104,
        (marker_available_width - (target - 1) * marker_gap) // target,
    )
    markers_width = target * marker_diameter + (target - 1) * marker_gap
    marker_left = center_x - markers_width // 2
    marker_top = caption_bottom + 48
    marker_font = load_font(FONT_SANS_CANDIDATES, 34)
    for index in range(target):
        left = marker_left + index * (marker_diameter + marker_gap)
        filled = index < progress
        draw.ellipse(
            (left, marker_top, left + marker_diameter, marker_top + marker_diameter),
            fill=ACCENT if filled else PANEL_FILL,
            outline=ACCENT,
            width=3,
        )
        marker_label = str(index + 1)
        marker_bbox = draw.textbbox((0, 0), marker_label, font=marker_font)
        marker_width = marker_bbox[2] - marker_bbox[0]
        marker_height = marker_bbox[3] - marker_bbox[1]
        draw.text(
            (
                left + (marker_diameter - marker_width) // 2 - marker_bbox[0],
                marker_top + (marker_diameter - marker_height) // 2 - marker_bbox[1],
            ),
            marker_label,
            fill=PANEL_HIGHLIGHT if filled else INK_SOFT,
            font=marker_font,
        )

    reward_top = marker_top + marker_diameter + 54
    reward_box = (MARGIN_X, reward_top, CARD_WIDTH - MARGIN_X, reward_top + 204)
    draw.rounded_rectangle(
        reward_box,
        radius=34,
        fill=PANEL_FILL,
        outline=DIVIDER,
        width=2,
    )
    reward_font = load_font(FONT_SERIF_CANDIDATES, 48)
    reward_title = (
        "Подарок доступен" if remaining == 0 else f"Осталось {remaining} {_visit_word(remaining)}"
    )
    reward_bottom = _draw_centered(
        draw,
        reward_title,
        center_x=center_x,
        top=reward_top + 36,
        font=reward_font,
        fill=INK,
    )
    _draw_centered(
        draw,
        "до персонального подарка от Ангелы",
        center_x=center_x,
        top=reward_bottom + 18,
        font=caption_font,
        fill=INK_SOFT,
    )

    next_top = reward_box[3] + 28
    next_box = (MARGIN_X, next_top, CARD_WIDTH - MARGIN_X, next_top + 142)
    draw.rounded_rectangle(
        next_box,
        radius=30,
        fill=PANEL_FILL,
        outline=DIVIDER,
        width=2,
    )
    label_font = load_font(FONT_SANS_CANDIDATES, 23)
    draw.text(
        (next_box[0] + 34, next_top + 24),
        "БЛИЖАЙШАЯ ЗАПИСЬ",
        fill=INK_MUTED,
        font=label_font,
    )
    next_font = load_font(FONT_SERIF_CANDIDATES, 40)
    draw.text(
        (next_box[0] + 34, next_top + 66),
        data.next_visit or "Пока без записи",
        fill=INK,
        font=next_font,
    )

    footer_font = load_font(FONT_SANS_CANDIDATES, 23)
    _draw_centered(
        draw,
        "Демо · условия и подарок пока не утверждены",
        center_x=center_x,
        top=CARD_HEIGHT - 92,
        font=footer_font,
        fill=INK_MUTED,
    )

    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


def render_loyalty_minimal_card_bytes(data: LoyaltyCardData) -> bytes:
    """Render a restrained dark membership-card concept with minimal detail."""
    background = (66, 43, 39)
    cream = (247, 235, 224)
    gold = (211, 164, 132)
    muted_gold = (190, 142, 116)
    panel = (82, 54, 49)
    canvas = Image.new("RGB", (CARD_WIDTH, CARD_HEIGHT), color=background)
    draw = ImageDraw.Draw(canvas)
    center_x = CARD_WIDTH // 2

    draw.rounded_rectangle(
        (38, 38, CARD_WIDTH - 38, CARD_HEIGHT - 38),
        radius=56,
        outline=gold,
        width=3,
    )
    draw.rounded_rectangle(
        (54, 54, CARD_WIDTH - 54, CARD_HEIGHT - 54),
        radius=46,
        outline=(117, 76, 66),
        width=1,
    )
    brand_bottom = draw_brand_wordmark(
        draw,
        center_x=center_x,
        top=92,
        size=68,
        subtitle_size=22,
        main_fill=cream,
        subtitle_fill=gold,
    )

    eyebrow_font = load_font(FONT_SANS_CANDIDATES, 22)
    heading_bottom = _draw_centered(
        draw,
        "PRIVATE CLIENT CARD",
        center_x=center_x,
        top=brand_bottom + 54,
        font=eyebrow_font,
        fill=muted_gold,
    )
    safe_name = " ".join(data.display_name.split())[:40] or "Гостья"
    name_font = _fit_font(
        draw,
        safe_name,
        candidates=FONT_SERIF_CANDIDATES,
        initial_size=82,
        min_size=46,
        max_width=CARD_WIDTH - MARGIN_X * 2,
    )
    name_bottom = _draw_centered(
        draw,
        safe_name,
        center_x=center_x,
        top=heading_bottom + 52,
        font=name_font,
        fill=cream,
    )
    status_font = load_font(FONT_SANS_CANDIDATES, 29)
    status_bottom = _draw_centered(
        draw,
        data.status_label,
        center_x=center_x,
        top=name_bottom + 18,
        font=status_font,
        fill=gold,
    )

    draw.line(
        (MARGIN_X + 80, status_bottom + 62, CARD_WIDTH - MARGIN_X - 80, status_bottom + 62),
        fill=(117, 76, 66),
        width=2,
    )

    target = max(1, min(data.target_visits, 8))
    progress = max(0, min(data.progress_visits, target))
    remaining = max(0, target - progress)
    progress_top = status_bottom + 124
    count_font = load_font(FONT_SERIF_CANDIDATES, 92)
    count_bottom = _draw_centered(
        draw,
        f"{progress} из {target}",
        center_x=center_x,
        top=progress_top,
        font=count_font,
        fill=cream,
    )
    progress_caption = (
        "подарок уже доступен"
        if remaining == 0
        else f"ещё {remaining} {_visit_word(remaining)} до подарка"
    )
    caption_font = load_font(FONT_SANS_CANDIDATES, 28)
    _draw_centered(
        draw,
        progress_caption,
        center_x=center_x,
        top=count_bottom + 16,
        font=caption_font,
        fill=gold,
    )

    line_left = MARGIN_X + 90
    line_right = CARD_WIDTH - MARGIN_X - 90
    line_top = count_bottom + 92
    segment_gap = 12
    segment_width = (line_right - line_left - segment_gap * (target - 1)) // target
    for index in range(target):
        left = line_left + index * (segment_width + segment_gap)
        draw.rounded_rectangle(
            (left, line_top, left + segment_width, line_top + 18),
            radius=9,
            fill=gold if index < progress else (117, 76, 66),
        )

    details_top = line_top + 92
    details_box = (MARGIN_X, details_top, CARD_WIDTH - MARGIN_X, details_top + 270)
    draw.rounded_rectangle(details_box, radius=34, fill=panel, outline=(117, 76, 66), width=2)
    label_font = load_font(FONT_SANS_CANDIDATES, 22)
    value_font = load_font(FONT_SERIF_CANDIDATES, 39)
    draw.text(
        (details_box[0] + 38, details_top + 34),
        "ЗАВЕРШЁННЫЕ ВИЗИТЫ",
        fill=muted_gold,
        font=label_font,
    )
    draw.text(
        (details_box[0] + 38, details_top + 76),
        str(max(0, data.completed_visits)),
        fill=cream,
        font=value_font,
    )
    draw.text(
        (details_box[0] + 38, details_top + 146),
        "БЛИЖАЙШАЯ ЗАПИСЬ",
        fill=muted_gold,
        font=label_font,
    )
    draw.text(
        (details_box[0] + 38, details_top + 188),
        data.next_visit or "Пока без записи",
        fill=cream,
        font=value_font,
    )

    footer_font = load_font(FONT_SANS_CANDIDATES, 22)
    _draw_centered(
        draw,
        "ДЕМО · ANGELS NAIL SPACE",
        center_x=center_x,
        top=CARD_HEIGHT - 96,
        font=footer_font,
        fill=muted_gold,
    )

    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()
