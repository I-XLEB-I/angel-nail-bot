"""Dynamic schedule card: 1080×1920, free windows only.

Layout:
  header      — ANGELS wordmark + "Свободные окошки" title
  body        — list of days, each as `date` + chips of free times
  footer      — editable short caption (schedule_caption_text template)

The renderer is deliberately minimal: flat champagne background, serif for
dates, sans for times. No overlays, no stylized panels.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date

from PIL import ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Slot
from src.db.repositories.settings import SettingRepository
from src.db.repositories.slots import PUBLIC_BOOKING_HORIZON_DAYS, SlotRepository
from src.db.repositories.templates import TemplateRepository
from src.services.admin_defaults import required_template_defaults
from src.services.booking import format_local_datetime, group_slots_by_local_day
from src.services.image_core import (
    ACCENT,
    DIVIDER,
    FONT_SANS_CANDIDATES,
    FONT_SERIF_CANDIDATES,
    INK,
    INK_MUTED,
    INK_SOFT,
    draw_brand_wordmark,
    draw_divider,
    load_font,
    new_canvas,
    text_size,
    wrap_text,
)
from src.services.runtime_settings import get_bool_setting

IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1920

MARGIN_X = 96
BODY_TOP = 480
BODY_BOTTOM = 1680
FOOTER_Y = 1760

WEEKDAY_LABELS = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]
MONTH_GENITIVE = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]


@dataclass(slots=True, frozen=True)
class ScheduleImageEntry:
    local_date: date
    day_label: str
    times: list[str]


@dataclass(slots=True, frozen=True)
class ScheduleImagePage:
    entries: list[ScheduleImageEntry]
    period: str
    caption: str
    page_number: int
    total_pages: int


def _format_day_label(local_date) -> str:
    weekday = WEEKDAY_LABELS[local_date.weekday()]
    return f"{local_date.day} {MONTH_GENITIVE[local_date.month - 1]} · {weekday}"


def _format_period_label(local_dates: list) -> str:
    if not local_dates:
        return ""
    first, last = local_dates[0], local_dates[-1]
    if first == last:
        return f"{first.day} {MONTH_GENITIVE[first.month - 1]}"
    if first.month == last.month:
        return f"{first.day}–{last.day} {MONTH_GENITIVE[first.month - 1]}"
    return (
        f"{first.day} {MONTH_GENITIVE[first.month - 1]} — "
        f"{last.day} {MONTH_GENITIVE[last.month - 1]}"
    )


def _collect_free_times(slots: list[Slot], local_date, tz_name: str) -> list[str]:
    times: list[str] = []
    for slot in slots:
        local_dt = format_local_datetime(slot.start_at, tz_name)
        if local_dt.date() == local_date:
            times.append(local_dt.strftime("%H:%M"))
    times.sort()
    return times


def _measure_time_chips_height(
    draw: ImageDraw.ImageDraw,
    times: list[str],
    *,
    font,
    left: int,
    right: int,
) -> int:
    """Measure the wrapped chip block height without drawing it."""
    chip_gap_x = 16
    chip_gap_y = 14
    padding_x = 18
    padding_y = 10
    cursor_x = left
    cursor_y = 0
    row_h = text_size(draw, "00:00", font)[1] + padding_y * 2
    for time_label in times:
        text_w, _ = text_size(draw, time_label, font)
        chip_w = text_w + padding_x * 2
        if cursor_x + chip_w > right and cursor_x > left:
            cursor_x = left
            cursor_y += row_h + chip_gap_y
        cursor_x += chip_w + chip_gap_x
    return cursor_y + row_h


def _draw_empty_body(
    draw: ImageDraw.ImageDraw,
    *,
    y: int,
) -> None:
    font = load_font(FONT_SERIF_CANDIDATES, 44)
    message = "Сейчас всё занято — напиши Ангеле, найдём окошко 🤍"
    lines = wrap_text(draw, message, font=font, max_width=IMAGE_WIDTH - MARGIN_X * 2)
    cursor_y = y
    for line in lines:
        line_w, line_h = text_size(draw, line, font)
        draw.text(
            ((IMAGE_WIDTH - line_w) // 2, cursor_y),
            line,
            fill=INK_SOFT,
            font=font,
        )
        cursor_y += line_h + 14


def _draw_time_chips(
    draw: ImageDraw.ImageDraw,
    times: list[str],
    *,
    top: int,
    font,
    left: int,
    right: int,
) -> int:
    """Render time chips left-to-right, wrapping; return y below last row."""
    chip_gap_x = 16
    chip_gap_y = 14
    padding_x = 18
    padding_y = 10
    cursor_x = left
    cursor_y = top
    row_h = text_size(draw, "00:00", font)[1] + padding_y * 2
    for time_label in times:
        text_w, _ = text_size(draw, time_label, font)
        chip_w = text_w + padding_x * 2
        if cursor_x + chip_w > right and cursor_x > left:
            cursor_x = left
            cursor_y += row_h + chip_gap_y
        draw.rounded_rectangle(
            (cursor_x, cursor_y, cursor_x + chip_w, cursor_y + row_h),
            radius=row_h // 2,
            outline=ACCENT,
            width=2,
        )
        draw.text(
            (cursor_x + padding_x, cursor_y + padding_y - 2),
            time_label,
            fill=INK,
            font=font,
        )
        cursor_x += chip_w + chip_gap_x
    return cursor_y + row_h


def _build_schedule_entries(slots: list[Slot], tz_name: str) -> list[ScheduleImageEntry]:
    """Build one grouped schedule entry per local day."""
    day_options = group_slots_by_local_day(slots, tz_name)
    entries: list[ScheduleImageEntry] = []
    for option in day_options:
        times = _collect_free_times(slots, option.local_date, tz_name)
        if not times:
            continue
        entries.append(
            ScheduleImageEntry(
                local_date=option.local_date,
                day_label=_format_day_label(option.local_date),
                times=times,
            )
        )
    return entries


def _paginate_schedule_entries(entries: list[ScheduleImageEntry]) -> list[list[ScheduleImageEntry]]:
    """Split one free-windows schedule into vertical pages."""
    if not entries:
        return [[]]

    canvas = new_canvas(IMAGE_WIDTH, IMAGE_HEIGHT)
    draw = ImageDraw.Draw(canvas)
    day_font = load_font(FONT_SERIF_CANDIDATES, 44)
    time_font = load_font(FONT_SANS_CANDIDATES, 34)
    body_left = MARGIN_X
    body_right = IMAGE_WIDTH - MARGIN_X

    pages: list[list[ScheduleImageEntry]] = []
    current_page: list[ScheduleImageEntry] = []
    cursor_y = BODY_TOP
    divider_gap = 28

    for entry in entries:
        _, day_h = text_size(draw, entry.day_label, day_font)
        chips_h = _measure_time_chips_height(
            draw,
            entry.times,
            font=time_font,
            left=body_left,
            right=body_right,
        )
        block_height = day_h + 16 + chips_h + 36 + 1 + divider_gap
        if cursor_y + block_height > BODY_BOTTOM and current_page:
            pages.append(current_page)
            current_page = []
            cursor_y = BODY_TOP
        current_page.append(entry)
        cursor_y += block_height

    if current_page:
        pages.append(current_page)
    return pages


def render_schedule_image_bytes(
    entries: list[ScheduleImageEntry],
    *,
    period: str,
    caption: str,
    page_number: int,
    total_pages: int,
) -> bytes:
    """Render the 9:16 free-windows card."""
    canvas = new_canvas(IMAGE_WIDTH, IMAGE_HEIGHT)
    draw = ImageDraw.Draw(canvas)

    brand_bottom = draw_brand_wordmark(
        draw,
        center_x=IMAGE_WIDTH // 2,
        top=150,
        size=80,
        subtitle_size=28,
    )

    title_font = load_font(FONT_SERIF_CANDIDATES, 66)
    title = "Свободные окошки"
    title_w, title_h = text_size(draw, title, title_font)
    title_y = brand_bottom + 60
    draw.text(
        ((IMAGE_WIDTH - title_w) // 2, title_y),
        title,
        fill=INK,
        font=title_font,
    )

    subtitle_font = load_font(FONT_SANS_CANDIDATES, 30)
    if period:
        sub_w, sub_h = text_size(draw, period, subtitle_font)
        draw.text(
            ((IMAGE_WIDTH - sub_w) // 2, title_y + title_h + 18),
            period,
            fill=INK_MUTED,
            font=subtitle_font,
        )

    draw_divider(
        draw,
        y=title_y + title_h + 90,
        center_x=IMAGE_WIDTH // 2,
        span=260,
    )

    body_left = MARGIN_X
    body_right = IMAGE_WIDTH - MARGIN_X
    cursor_y = BODY_TOP

    day_font = load_font(FONT_SERIF_CANDIDATES, 44)
    time_font = load_font(FONT_SANS_CANDIDATES, 34)

    if not entries:
        _draw_empty_body(draw, y=cursor_y + 60)
    else:
        for entry in entries:
            day_label = entry.day_label
            _, day_h = text_size(draw, day_label, day_font)
            draw.text((body_left, cursor_y), day_label, fill=INK, font=day_font)
            cursor_y += day_h + 16
            cursor_y = _draw_time_chips(
                draw,
                entry.times,
                top=cursor_y,
                font=time_font,
                left=body_left,
                right=body_right,
            )
            cursor_y += 36
            draw.line(
                (body_left, cursor_y, body_right, cursor_y),
                fill=DIVIDER,
                width=1,
            )
            cursor_y += 28

    caption_text = caption.strip()
    if caption_text:
        caption_font = load_font(FONT_SANS_CANDIDATES, 28)
        lines = wrap_text(
            draw,
            caption_text,
            font=caption_font,
            max_width=IMAGE_WIDTH - MARGIN_X * 2,
        )[:2]
        cursor_y = FOOTER_Y
        for line in lines:
            line_w, line_h = text_size(draw, line, caption_font)
            draw.text(
                ((IMAGE_WIDTH - line_w) // 2, cursor_y),
                line,
                fill=INK_SOFT,
                font=caption_font,
            )
            cursor_y += line_h + 8

    page_font = load_font(FONT_SANS_CANDIDATES, 24)
    page_text = f"стр. {page_number}/{total_pages}"
    page_w, page_h = text_size(draw, page_text, page_font)
    draw.text(
        ((IMAGE_WIDTH - page_w) // 2, IMAGE_HEIGHT - 72 - page_h),
        page_text,
        fill=INK_MUTED,
        font=page_font,
    )

    output = io.BytesIO()
    canvas.save(output, format="PNG", optimize=True)
    return output.getvalue()


async def build_schedule_image_bytes(
    db_session: AsyncSession,
    *,
    tz_name: str,
    slots: list[Slot] | None = None,
) -> bytes:
    """Load the current free slots and render the first 9:16 schedule page."""
    pages = await build_schedule_image_pages_bytes(
        db_session,
        tz_name=tz_name,
        slots=slots,
    )
    return pages[0]


async def build_schedule_image_pages_bytes(
    db_session: AsyncSession,
    *,
    tz_name: str,
    slots: list[Slot] | None = None,
) -> list[bytes]:
    """Load the current free slots and render paginated 9:16 schedule cards."""
    pages = await build_schedule_image_pages_data(
        db_session,
        tz_name=tz_name,
        slots=slots,
    )
    return [
        render_schedule_image_bytes(
            page.entries,
            period=page.period,
            caption=page.caption,
            page_number=page.page_number,
            total_pages=page.total_pages,
        )
        for page in pages
    ]


async def build_schedule_image_pages_data(
    db_session: AsyncSession,
    *,
    tz_name: str,
    slots: list[Slot] | None = None,
) -> list[ScheduleImagePage]:
    """Return structured schedule-image pages for one-photo-at-a-time viewers."""
    if slots is None:
        slots = await SlotRepository(db_session).list_free_future(
            horizon_days=PUBLIC_BOOKING_HORIZON_DAYS
        )
    defaults = required_template_defaults()
    caption = await TemplateRepository(db_session).get_content_or_default(
        "schedule_caption_text",
        defaults["schedule_caption_text"],
    )
    entries = _build_schedule_entries(slots, tz_name)
    local_dates = [format_local_datetime(slot.start_at, tz_name).date() for slot in slots]
    period = _format_period_label(sorted(set(local_dates)))
    paginated_entries = _paginate_schedule_entries(entries)
    total_pages = len(paginated_entries)
    return [
        ScheduleImagePage(
            entries=page_entries,
            period=period,
            caption=caption,
            page_number=index + 1,
            total_pages=total_pages,
        )
        for index, page_entries in enumerate(paginated_entries)
    ]


async def is_schedule_image_enabled(db_session: AsyncSession) -> bool:
    """Return whether the schedule card is shown to clients in the booking flow."""
    repository = SettingRepository(db_session)
    return await get_bool_setting(repository, key="schedule_image_enabled", default=True)
