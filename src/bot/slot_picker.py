from __future__ import annotations

import re
from datetime import date
from typing import Callable

from aiogram.types import BufferedInputFile, Message
from aiogram.fsm.context import FSMContext
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot.ui_utils import replace_inline_message_panel, replace_inline_message_text
from src.config import Settings
from src.db.models import Slot
from src.services.booking import DayOption, format_local_datetime
from src.services.schedule_image import (
    build_schedule_image_pages_data,
    is_schedule_image_enabled,
    render_schedule_image_bytes,
)

WEEKDAY_PREFERENCE_KEYWORDS = (
    (0, ("понедельник", "пн")),
    (1, ("вторник", "вт")),
    (2, ("среда", "ср")),
    (3, ("четверг", "чт")),
    (4, ("пятница", "пт")),
    (5, ("суббота", "сб")),
    (6, ("воскресенье", "вс")),
)
TIME_AFTER_RE = re.compile(r"(?:после|с)\s*(\d{1,2})(?::(\d{2}))?", re.IGNORECASE)
TIME_BEFORE_RE = re.compile(r"до\s*(\d{1,2})(?::(\d{2}))?", re.IGNORECASE)


def _extract_preferred_weekdays(preferred_days_note: str | None) -> list[int]:
    """Extract weekday hints from a saved free-form preference note."""
    if not preferred_days_note:
        return []
    note = preferred_days_note.casefold()
    matches: list[int] = []
    for weekday, aliases in WEEKDAY_PREFERENCE_KEYWORDS:
        if any(alias in note for alias in aliases):
            matches.append(weekday)
    if "выходн" in note:
        matches.extend([5, 6])
    if "будн" in note:
        matches.extend([0, 1, 2, 3, 4])
    ordered_matches: list[int] = []
    for weekday in matches:
        if weekday not in ordered_matches:
            ordered_matches.append(weekday)
    return ordered_matches


def order_day_options_by_preference(
    day_options: list[DayOption],
    preferred_days_note: str | None,
) -> list[DayOption]:
    """Move days matching the client's saved preference to the top."""
    preferred_weekdays = _extract_preferred_weekdays(preferred_days_note)
    if not preferred_weekdays:
        return list(day_options)
    weekday_order = {weekday: index for index, weekday in enumerate(preferred_weekdays)}
    return sorted(
        day_options,
        key=lambda item: (
            0 if item.local_date.weekday() in weekday_order else 1,
            weekday_order.get(item.local_date.weekday(), 99),
            item.local_date,
        ),
    )


def _minutes_from_match(match: re.Match[str] | None) -> int | None:
    """Convert a regex time match into minutes since midnight."""
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or "0")
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def order_slots_by_time_preference(
    slots: list[Slot],
    preferred_time_note: str | None,
    *,
    tz_name: str,
) -> list[Slot]:
    """Prioritize slots that better match the client's saved time preference."""
    if not preferred_time_note:
        return list(slots)
    note = preferred_time_note.casefold()

    target_after = _minutes_from_match(TIME_AFTER_RE.search(note))
    target_before = _minutes_from_match(TIME_BEFORE_RE.search(note))

    def slot_minutes(slot: Slot) -> int:
        local_dt = format_local_datetime(slot.start_at, tz_name)
        return local_dt.hour * 60 + local_dt.minute

    if target_after is not None:
        return sorted(
            slots,
            key=lambda slot: (
                0 if slot_minutes(slot) >= target_after else 1,
                abs(slot_minutes(slot) - target_after),
                slot.start_at,
            ),
        )
    if target_before is not None:
        return sorted(
            slots,
            key=lambda slot: (
                0 if slot_minutes(slot) <= target_before else 1,
                abs(slot_minutes(slot) - target_before),
                slot.start_at,
            ),
        )
    if "после работы" in note or "вечер" in note:
        return sorted(
            slots,
            key=lambda slot: (
                0 if slot_minutes(slot) >= 18 * 60 else 1,
                abs(slot_minutes(slot) - 18 * 60),
                slot.start_at,
            ),
        )
    if "утр" in note or "до обеда" in note:
        return sorted(
            slots,
            key=lambda slot: (
                0 if slot_minutes(slot) < 12 * 60 else 1,
                slot_minutes(slot),
                slot.start_at,
            ),
        )
    if "днем" in note or "днём" in note or "после обеда" in note:
        return sorted(
            slots,
            key=lambda slot: (
                0 if 12 * 60 <= slot_minutes(slot) < 18 * 60 else 1,
                abs(slot_minutes(slot) - 14 * 60),
                slot.start_at,
            ),
        )
    return list(slots)


def _read_page_index(state_data: dict[str, object], *, page_state_key: str) -> int | None:
    """Read a persisted page index from FSM state data."""
    stored_page = state_data.get(page_state_key)
    if isinstance(stored_page, int):
        return stored_page
    if isinstance(stored_page, str) and stored_page.isdigit():
        return int(stored_page)
    return None


async def render_day_picker(
    message: Message,
    *,
    db_session: AsyncSession,
    settings: Settings,
    slots: list[Slot],
    day_options: list[DayOption],
    prompt_text: str,
    no_slots_text: str,
    replace: bool,
    no_slots_reply_markup,
    text_reply_markup_builder: Callable[[list[DayOption]], object],
    image_reply_markup_builder: Callable[[list[DayOption], int, int], object],
    schedule_caption_text: str | None = None,
    image_caption_text: str | None = None,
    state: FSMContext | None = None,
    page_state_key: str | None = None,
    image_page: int | None = None,
    focus_day: date | None = None,
) -> None:
    """Render a shared day picker with schedule-image pagination when enabled."""
    if not day_options:
        if replace:
            await replace_inline_message_text(
                message,
                no_slots_text,
                reply_markup=no_slots_reply_markup,
            )
        else:
            await message.answer(no_slots_text, reply_markup=no_slots_reply_markup)
        return

    if await is_schedule_image_enabled(db_session):
        try:
            await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")
            image_pages = await build_schedule_image_pages_data(
                db_session,
                tz_name=settings.tz,
                slots=slots,
            )
        except Exception:
            image_pages = []
        if image_pages:
            current_index = 0
            if image_page is not None:
                current_index = max(0, min(image_page, len(image_pages) - 1))
            elif state is not None and page_state_key is not None:
                state_data = await state.get_data()
                stored_page = _read_page_index(state_data, page_state_key=page_state_key)
                if stored_page is not None:
                    current_index = max(0, min(stored_page, len(image_pages) - 1))
            if image_page is None:
                target_day = focus_day or (day_options[0].local_date if day_options else None)
                if target_day is not None:
                    for page_index, page in enumerate(image_pages):
                        if any(entry.local_date == target_day for entry in page.entries):
                            current_index = page_index
                            break

            current_page = image_pages[current_index]
            visible_day_options = [
                day_option
                for day_option in day_options
                if any(entry.local_date == day_option.local_date for entry in current_page.entries)
            ]
            if state is not None and page_state_key is not None:
                await state.update_data(**{page_state_key: current_index})
            photo_bytes = render_schedule_image_bytes(
                current_page.entries,
                period=current_page.period,
                caption=current_page.caption,
                page_number=current_page.page_number,
                total_pages=current_page.total_pages,
            )
            caption = image_caption_text if image_caption_text is not None else prompt_text
            if image_caption_text is None and schedule_caption_text:
                caption = f"{prompt_text}\n\n{schedule_caption_text}"
            if replace:
                await replace_inline_message_panel(
                    message,
                    photo_bytes=photo_bytes,
                    filename="schedule.png",
                    caption=caption,
                    reply_markup=image_reply_markup_builder(
                        visible_day_options,
                        current_index,
                        current_page.total_pages,
                    ),
                )
            else:
                await message.answer_photo(
                    photo=BufferedInputFile(photo_bytes, filename="schedule.png"),
                    caption=caption,
                    reply_markup=image_reply_markup_builder(
                        visible_day_options,
                        current_index,
                        current_page.total_pages,
                    ),
                )
            return

    if replace:
        await replace_inline_message_text(
            message,
            prompt_text,
            reply_markup=text_reply_markup_builder(day_options),
        )
    else:
        await message.answer(
            prompt_text,
            reply_markup=text_reply_markup_builder(day_options),
        )


async def render_time_picker(
    message: Message,
    *,
    prompt_text: str,
    replace: bool,
    reply_markup,
) -> None:
    """Render a shared time picker panel."""
    if replace:
        await replace_inline_message_text(
            message,
            prompt_text,
            reply_markup=reply_markup,
        )
        return
    await message.answer(prompt_text, reply_markup=reply_markup)
