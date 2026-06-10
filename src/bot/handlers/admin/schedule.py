from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import (
    ADMIN_PANEL_CHAT_ID_KEY,
    ADMIN_PANEL_MESSAGE_ID_KEY,
    clear_state_preserving_admin_panel,
    remember_admin_panel,
    send_admin_panel,
    send_admin_photo_panel,
)
from src.bot.handlers.admin.booking_cards import show_booking_card
from src.bot.handlers.admin.clients import show_client_card
from src.bot.handlers.admin.rescue_slots import send_rescue_slot_prompt_to_admins
from src.bot.keyboards.admin import (
    SLOT_STATUS_ICONS,
    build_admin_schedule_back_keyboard,
    build_admin_schedule_delete_confirm_keyboard,
    build_admin_schedule_delete_menu,
    build_admin_schedule_delete_period_confirm_keyboard,
    build_admin_schedule_image_viewer_keyboard,
    build_admin_schedule_input_keyboard,
    build_admin_schedule_menu,
    build_admin_schedule_month_keyboard,
    build_admin_schedule_slot_detail_keyboard,
    build_admin_schedule_week_keyboard,
    build_schedule_preview_keyboard,
    render_week_slot_text,
)
from src.bot.states import AdminSchedule, AdminScheduleMove
from src.bot.ui_utils import replace_inline_message_text, upsert_inline_panel
from src.config import Settings
from src.db.models import Slot, SlotStatus
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.slots import SlotRepository
from src.services import admin_schedule as admin_schedule_service
from src.services.anti_abuse import get_anti_abuse_settings, record_rate_event
from src.services.booking import (
    apply_booking_no_show,
    build_no_show_client_notice,
    format_local_datetime,
    group_slots_by_local_day,
)
from src.services.notifications import send_text_to_user
from src.services.rescue_slots import slot_is_rescuable
from src.services.schedule_image import (
    build_schedule_image_pages_data,
    is_schedule_image_enabled,
    render_schedule_image_bytes,
)
from src.services.schedule_parser import ParsedSlot, ParseError, parse_schedule

router = Router(name="admin_schedule")
SCHEDULE_WEEK_PAGE_SIZE = 8
SCHEDULE_MONTH_DAYS = 30
SCHEDULE_MONTH_PAGE_SIZE = 10


def parse_schedule_origin(parts: list[str], *, start_index: int) -> tuple[str, int]:
    """Parse a schedule callback origin from callback segments.

    Supports both the new explicit ``week|month`` format and the older
    ``page`` format that implied a weekly origin.
    """
    if len(parts) <= start_index:
        return "week", 0

    token = parts[start_index]
    if token == "page":
        value = int(parts[start_index + 1]) if len(parts) > start_index + 1 else 0
        return "week", value
    if token == "week":
        value = int(parts[start_index + 1]) if len(parts) > start_index + 1 else 0
        return "week", value
    if token == "month":
        if len(parts) > start_index + 2 and parts[start_index + 1] == "page":
            return "month", int(parts[start_index + 2])
        value = int(parts[start_index + 1]) if len(parts) > start_index + 1 else 0
        return "month", value
    return "week", 0


def build_schedule_origin_callback(origin_view: str, origin_value: int) -> str:
    """Return the callback that reopens the schedule list for the given origin."""
    if origin_view == "month":
        return f"admin_schedule:month:page:{origin_value}"
    return f"admin_schedule:week:{origin_value}"


def format_schedule_period_label(start_local_date: date, end_local_date: date) -> str:
    """Return a compact local-date period label for schedule bulk actions."""
    return admin_schedule_service.format_schedule_period_label(
        start_local_date,
        end_local_date,
    )


async def get_schedule_delete_period_payload(
    db_session: AsyncSession,
    *,
    settings: Settings,
    period_kind: str,
) -> tuple[list[Slot], str]:
    """Return deletable slots and the display label for one bulk-delete period."""
    return await admin_schedule_service.get_schedule_delete_period_payload(
        db_session,
        tz_name=settings.tz,
        period_kind=period_kind,
    )


async def show_schedule_origin_page(
    message: Message,
    *,
    db_session: AsyncSession,
    settings: Settings,
    origin_view: str,
    origin_value: int,
    state: FSMContext | None = None,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Render the schedule list page that corresponds to one slot origin."""
    if origin_view == "month":
        await show_schedule_month_page(
            message,
            db_session=db_session,
            settings=settings,
            offset=origin_value,
            state=state,
            edit=edit,
            notice_text=notice_text,
        )
        return
    await show_schedule_week_page(
        message,
        db_session=db_session,
        settings=settings,
        page=origin_value,
        state=state,
        edit=edit,
        notice_text=notice_text,
    )


def serialize_parsed_slots(parsed_slots: list[ParsedSlot]) -> list[dict[str, object]]:
    """Convert parsed slots into FSM-storable dicts."""
    return [
        {
            "date": slot.date.isoformat(),
            "time": slot.time.isoformat(),
            "line_no": slot.line_no,
            "raw_line": slot.raw_line,
        }
        for slot in parsed_slots
    ]


def deserialize_parsed_slots(items: list[dict[str, object]]) -> list[ParsedSlot]:
    """Convert FSM-stored slot dicts back into ParsedSlot objects."""
    parsed_slots: list[ParsedSlot] = []
    for item in items:
        parsed_slots.append(
            ParsedSlot(
                date=date.fromisoformat(str(item["date"])),
                time=time.fromisoformat(str(item["time"])),
                line_no=int(item["line_no"]),
                raw_line=str(item["raw_line"]),
            )
        )
    return parsed_slots


def serialize_errors(errors: list[ParseError]) -> list[dict[str, object]]:
    """Convert parse errors into FSM-storable dicts."""
    return [
        {
            "line_no": error.line_no,
            "raw_line": error.raw_line,
            "reason": error.reason,
        }
        for error in errors
    ]


def deserialize_errors(items: list[dict[str, object]]) -> list[ParseError]:
    """Convert FSM-stored error dicts back into ParseError objects."""
    return [
        ParseError(
            line_no=int(item["line_no"]),
            raw_line=str(item["raw_line"]),
            reason=str(item["reason"]),
        )
        for item in items
    ]


def build_schedule_preview_text(parsed_slots: list[ParsedSlot], errors: list[ParseError]) -> str:
    """Render the parser preview text from slots and errors."""
    lines = ["Распознала 📋", ""]
    grouped: dict[str, list[str]] = defaultdict(list)
    for slot in parsed_slots:
        grouped[slot.date.strftime("%d.%m")].append(slot.time.strftime("%H:%M"))

    for day_label, times in grouped.items():
        lines.append(f"{day_label} — {', '.join(times)}")

    if errors:
        if grouped:
            lines.append("")
        lines.append("⚠️ Не смогла разобрать:")
        lines.append("")
        for error in errors:
            lines.append(f'Строка {error.line_no}: "{error.raw_line}" — {error.reason}')

    if not grouped:
        lines.extend(["", texts.ADMIN_SCHEDULE_PREVIEW_EMPTY_TEXT])

    lines.extend(["", "Всё верно?"])
    return "\n".join(lines)


def parsed_slot_to_utc(parsed_slot: ParsedSlot, *, tz_name: str) -> datetime:
    """Convert a parsed local slot into a UTC start datetime."""
    return admin_schedule_service.parsed_slot_to_utc(parsed_slot, tz_name=tz_name)


async def upsert_schedule_panel_from_state(
    state: FSMContext,
    *,
    bot,
    text: str,
    reply_markup=None,
) -> Message | None:
    """Update the remembered admin schedule panel in place from FSM state."""
    data = await state.get_data()
    chat_id = data.get(ADMIN_PANEL_CHAT_ID_KEY)
    message_id = data.get(ADMIN_PANEL_MESSAGE_ID_KEY)
    if not chat_id or not message_id:
        return None
    panel = await upsert_inline_panel(
        bot,
        chat_id=int(chat_id),
        message_id=int(message_id),
        text=text,
        reply_markup=reply_markup,
    )
    await remember_admin_panel(state, panel)
    return panel


async def show_schedule_input_prompt(
    message: Message,
    *,
    state: FSMContext,
    edit: bool,
) -> None:
    """Show the schedule text input prompt in the shared panel."""
    if edit:
        await replace_inline_message_text(
            message,
            texts.ADMIN_SCHEDULE_INSTRUCTION_TEXT,
            reply_markup=build_admin_schedule_input_keyboard(),
        )
        await remember_admin_panel(state, message)
        return
    await upsert_schedule_panel_from_state(
        state,
        bot=message.bot,
        text=texts.ADMIN_SCHEDULE_INSTRUCTION_TEXT,
        reply_markup=build_admin_schedule_input_keyboard(),
    )


def build_schedule_week_text(
    slots: list[Slot],
    *,
    tz_name: str,
    page: int,
    page_size: int,
    notice_text: str | None = None,
) -> str:
    """Render one page of slots for the next 7 days."""
    lines = ["📆 Ближайшие 7 дней", ""]
    if notice_text:
        lines = [notice_text, "", *lines]
    start_index = page * page_size
    for offset, slot in enumerate(slots, start=1):
        lines.append(f"{start_index + offset}. {render_week_slot_text(slot, tz_name=tz_name)}")
    return "\n".join(lines)


def build_schedule_month_text(
    slots: list[Slot],
    *,
    tz_name: str,
    offset: int,
    page_size: int,
    notice_text: str | None = None,
) -> str:
    """Render a compact 30-day schedule grouped by local day."""
    day_options = group_slots_by_local_day(slots, tz_name)
    lines = [texts.ADMIN_SCHEDULE_MONTH_HEADER_TEXT, ""]
    if notice_text:
        lines = [notice_text, "", *lines]

    slots_by_day: dict[date, list[Slot]] = defaultdict(list)
    for slot in slots:
        local_dt = format_local_datetime(slot.start_at, tz_name)
        slots_by_day[local_dt.date()].append(slot)

    for day_option in day_options[offset : offset + page_size]:
        day_slots = sorted(slots_by_day[day_option.local_date], key=lambda item: item.start_at)
        rendered_times = []
        free_count = 0
        booked_count = 0
        blocked_count = 0
        for slot in day_slots:
            local_dt = format_local_datetime(slot.start_at, tz_name)
            rendered_times.append(f"{SLOT_STATUS_ICONS[slot.status]} {local_dt:%H:%M}")
            if slot.status == SlotStatus.FREE:
                free_count += 1
            elif slot.status == SlotStatus.BOOKED:
                booked_count += 1
            else:
                blocked_count += 1
        load_bits = [f"свободно {free_count}"]
        if booked_count:
            load_bits.append(f"занято {booked_count}")
        if blocked_count:
            load_bits.append(f"блок {blocked_count}")
        lines.append(
            f"{day_option.local_date:%d.%m} — {' · '.join(load_bits)}\n"
            f"{', '.join(rendered_times)}"
        )

    return "\n".join(lines)


async def show_schedule_week_page(
    message: Message,
    *,
    db_session: AsyncSession,
    settings: Settings,
    page: int = 0,
    state: FSMContext | None = None,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Show one paginated weekly schedule page in the shared panel."""
    repository = SlotRepository(db_session)
    slots = await repository.list_for_next_days(tz_name=settings.tz, days=7)
    if not slots:
        text = texts.ADMIN_SCHEDULE_WEEK_EMPTY_TEXT
        if notice_text:
            text = f"{notice_text}\n\n{text}"
        if edit:
            await replace_inline_message_text(
                message,
                text,
                reply_markup=build_admin_schedule_back_keyboard(),
            )
            if state is not None:
                await remember_admin_panel(state, message)
            return
        if state is not None:
            await upsert_schedule_panel_from_state(
                state,
                bot=message.bot,
                text=text,
                reply_markup=build_admin_schedule_back_keyboard(),
            )
            return
        await message.answer(text, reply_markup=build_admin_schedule_back_keyboard())
        return

    max_page = max(0, (len(slots) - 1) // SCHEDULE_WEEK_PAGE_SIZE)
    current_page = max(0, min(page, max_page))
    page_slots = slots[
        current_page * SCHEDULE_WEEK_PAGE_SIZE : (current_page + 1) * SCHEDULE_WEEK_PAGE_SIZE
    ]
    text = build_schedule_week_text(
        page_slots,
        tz_name=settings.tz,
        page=current_page,
        page_size=SCHEDULE_WEEK_PAGE_SIZE,
        notice_text=notice_text,
    )
    markup = build_admin_schedule_week_keyboard(
        page_slots,
        page=current_page,
        tz_name=settings.tz,
        has_prev=current_page > 0,
        has_next=current_page < max_page,
    )
    if edit:
        await replace_inline_message_text(message, text, reply_markup=markup)
        if state is not None:
            await remember_admin_panel(state, message)
        return
    if state is not None:
        await upsert_schedule_panel_from_state(
            state,
            bot=message.bot,
            text=text,
            reply_markup=markup,
        )
        return
    await message.answer(text, reply_markup=markup)


async def show_schedule_month_page(
    message: Message,
    *,
    db_session: AsyncSession,
    settings: Settings,
    offset: int = 0,
    state: FSMContext | None = None,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Show a paginated 30-day admin schedule grouped by days with slots."""
    repository = SlotRepository(db_session)
    slots = await repository.list_for_next_days(tz_name=settings.tz, days=SCHEDULE_MONTH_DAYS)
    day_options = group_slots_by_local_day(slots, settings.tz)
    if not day_options:
        text = texts.ADMIN_SCHEDULE_MONTH_EMPTY_TEXT
        if notice_text:
            text = f"{notice_text}\n\n{text}"
        if edit:
            await replace_inline_message_text(
                message,
                text,
                reply_markup=build_admin_schedule_back_keyboard(),
            )
            if state is not None:
                await remember_admin_panel(state, message)
            return
        if state is not None:
            await upsert_schedule_panel_from_state(
                state,
                bot=message.bot,
                text=text,
                reply_markup=build_admin_schedule_back_keyboard(),
            )
            return
        await message.answer(text, reply_markup=build_admin_schedule_back_keyboard())
        return

    max_offset = ((len(day_options) - 1) // SCHEDULE_MONTH_PAGE_SIZE) * SCHEDULE_MONTH_PAGE_SIZE
    current_offset = max(0, min(offset, max_offset))

    # Collect the dates visible on the current page so we can pass their slots to the keyboard.
    visible_days = {
        day_option.local_date
        for day_option in day_options[current_offset : current_offset + SCHEDULE_MONTH_PAGE_SIZE]
    }
    slots_page = sorted(
        [s for s in slots if format_local_datetime(s.start_at, settings.tz).date() in visible_days],
        key=lambda s: s.start_at,
    )

    text = build_schedule_month_text(
        slots,
        tz_name=settings.tz,
        offset=current_offset,
        page_size=SCHEDULE_MONTH_PAGE_SIZE,
        notice_text=notice_text,
    )
    markup = build_admin_schedule_month_keyboard(
        offset=current_offset,
        total_days=len(day_options),
        page_size=SCHEDULE_MONTH_PAGE_SIZE,
        slots_page=slots_page,
        tz_name=settings.tz,
    )
    if edit:
        await replace_inline_message_text(message, text, reply_markup=markup)
        if state is not None:
            await remember_admin_panel(state, message)
        return
    if state is not None:
        await upsert_schedule_panel_from_state(
            state,
            bot=message.bot,
            text=text,
            reply_markup=markup,
        )
        return
    await message.answer(text, reply_markup=markup)


async def show_schedule_slot_detail(
    message: Message,
    *,
    db_session: AsyncSession,
    settings: Settings,
    slot_id: int,
    origin_view: str,
    origin_value: int,
    state: FSMContext | None = None,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Show one slot detail card inside the schedule admin flow."""
    repository = SlotRepository(db_session)
    slot = await repository.get_by_id(slot_id)
    if slot is None:
        await show_schedule_origin_page(
            message,
            db_session=db_session,
            settings=settings,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=edit,
            notice_text="Слот уже не существует.",
        )
        return

    lines = ["🕒 Слот", "", render_week_slot_text(slot, tz_name=settings.tz)]
    if notice_text:
        lines = [notice_text, "", *lines]
    text = "\n".join(lines)
    markup = build_admin_schedule_slot_detail_keyboard(
        slot,
        origin_view=origin_view,
        origin_value=origin_value,
    )
    if edit:
        await replace_inline_message_text(message, text, reply_markup=markup)
        if state is not None:
            await remember_admin_panel(state, message)
        return
    if state is not None:
        await upsert_schedule_panel_from_state(
            state,
            bot=message.bot,
            text=text,
            reply_markup=markup,
        )
        return
    await message.answer(text, reply_markup=markup)


async def show_schedule_move_prompt(
    message: Message,
    *,
    state: FSMContext,
    edit: bool,
    notice_text: str | None = None,
) -> None:
    """Ask the admin for a new local date/time for the selected slot."""
    text = texts.ADMIN_SCHEDULE_MOVE_PROMPT_TEXT
    if notice_text:
        text = f"{notice_text}\n\n{text}"
    if edit:
        await replace_inline_message_text(
            message,
            text,
            reply_markup=build_admin_schedule_input_keyboard(),
        )
        await remember_admin_panel(state, message)
        return
    panel = await upsert_schedule_panel_from_state(
        state,
        bot=message.bot,
        text=text,
        reply_markup=build_admin_schedule_input_keyboard(),
    )
    if panel is None:
        await message.answer(text, reply_markup=build_admin_schedule_input_keyboard())


async def show_schedule_menu(
    message: Message,
    *,
    edit: bool = False,
    state: FSMContext | None = None,
) -> None:
    """Show the admin schedule submenu."""
    if edit:
        await replace_inline_message_text(
            message,
            texts.ADMIN_SCHEDULE_MENU_TEXT,
            reply_markup=build_admin_schedule_menu(),
        )
        if state is not None:
            await remember_admin_panel(state, message)
        return
    if state is not None:
        await send_admin_panel(
            message,
            state,
            text=texts.ADMIN_SCHEDULE_MENU_TEXT,
            reply_markup=build_admin_schedule_menu(),
        )
        return
    await message.answer(
        texts.ADMIN_SCHEDULE_MENU_TEXT,
        reply_markup=build_admin_schedule_menu(),
    )


async def show_schedule_home(
    message: Message,
    *,
    state: FSMContext,
    db_session: AsyncSession,
    settings: Settings,
    edit: bool = False,
    image_page: int = 0,
) -> None:
    """Show the root schedule screen, preferring the paginated preview image."""
    if not await is_schedule_image_enabled(db_session):
        await show_schedule_menu(message, edit=edit, state=state)
        return

    pages = await build_schedule_image_pages_data(db_session, tz_name=settings.tz)
    current_index = max(0, min(image_page, len(pages) - 1))
    current_page = pages[current_index]
    await state.update_data(admin_schedule_image_page=current_index)
    await send_admin_photo_panel(
        message,
        state,
        photo_bytes=render_schedule_image_bytes(
            current_page.entries,
            period=current_page.period,
            caption=current_page.caption,
            page_number=current_page.page_number,
            total_pages=current_page.total_pages,
        ),
        filename=f"schedule-{current_page.page_number}.png",
        caption="📅 РАСПИСАНИЕ\n\nЛистай страницы или выбери действие 👇",
        reply_markup=build_admin_schedule_image_viewer_keyboard(
            current_page=current_index,
            total_pages=current_page.total_pages,
        ),
    )


@router.message(lambda message: message.text == "📅 Расписание")
async def schedule_menu(
    message: Message,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Open the schedule admin section, prefixing with the schedule image if enabled."""
    if not is_admin:
        return
    try:
        await message.bot.send_chat_action(chat_id=message.chat.id, action="upload_photo")
        await show_schedule_home(
            message,
            state=state,
            db_session=db_session,
            settings=settings,
        )
    except Exception:
        await show_schedule_menu(message, state=state)


@router.callback_query(F.data == "admin_schedule:image")
async def schedule_show_image(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Legacy alias: reopen the schedule image viewer on the first page."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    try:
        await show_schedule_home(
            callback.message,
            state=state,
            db_session=db_session,
            settings=settings,
            edit=True,
            image_page=0,
        )
    except Exception:
        await replace_inline_message_text(
            callback.message,
            "Не удалось построить картинку 🤍",
            reply_markup=build_admin_schedule_back_keyboard(),
        )


@router.callback_query(F.data.startswith("admin_schedule:image_page:"))
async def schedule_image_page(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Flip one page inside the schedule preview image viewer."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    page = int(callback.data.rsplit(":", 1)[-1])
    await show_schedule_home(
        callback.message,
        state=state,
        db_session=db_session,
        settings=settings,
        edit=True,
        image_page=page,
    )


@router.callback_query(F.data == "admin_schedule:add")
async def schedule_add_start(callback: CallbackQuery, state: FSMContext, *, is_admin: bool) -> None:
    """Start the add-slots flow."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return

    await callback.answer()
    await state.set_state(AdminSchedule.input_text)
    if callback.message is not None:
        await show_schedule_input_prompt(
            callback.message,
            state=state,
            edit=True,
        )


@router.callback_query(F.data == "admin_schedule:cancel_input")
async def schedule_cancel_input(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Return from the text-input flow back to the schedule menu."""
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await show_schedule_home(
            callback.message,
            state=state,
            db_session=db_session,
            settings=settings,
            edit=True,
        )


@router.message(StateFilter(AdminSchedule.input_text))
async def schedule_parse_input(
    message: Message,
    state: FSMContext,
    *,
    settings: Settings,
) -> None:
    """Parse a schedule text and show a preview."""
    text = message.text or ""
    local_today = datetime.now(ZoneInfo(settings.tz)).date()
    parsed_slots, errors = parse_schedule(text, settings.tz, local_today)

    await state.set_state(AdminSchedule.preview)
    await state.update_data(
        admin_schedule_preview=serialize_parsed_slots(parsed_slots),
        admin_schedule_errors=serialize_errors(errors),
    )
    await upsert_schedule_panel_from_state(
        state,
        bot=message.bot,
        text=build_schedule_preview_text(parsed_slots, errors),
        reply_markup=build_schedule_preview_keyboard(
            allow_confirm=not errors and bool(parsed_slots)
        ),
    )


@router.callback_query(StateFilter(AdminSchedule.preview), F.data == "admin_schedule:retry")
async def schedule_retry(callback: CallbackQuery, state: FSMContext) -> None:
    """Retry the text schedule input."""
    await callback.answer()
    await state.set_state(AdminSchedule.input_text)
    if callback.message is not None:
        await show_schedule_input_prompt(
            callback.message,
            state=state,
            edit=True,
        )


@router.callback_query(StateFilter(AdminSchedule.preview), F.data == "admin_schedule:cancel")
async def schedule_cancel(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Cancel the schedule input flow."""
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await show_schedule_home(
            callback.message,
            state=state,
            db_session=db_session,
            settings=settings,
            edit=True,
        )


@router.callback_query(StateFilter(AdminSchedule.preview), F.data == "admin_schedule:confirm")
async def schedule_confirm(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Persist parsed slots into the database, skipping duplicates."""
    await callback.answer()
    if callback.message is None:
        return

    data = await state.get_data()
    parsed_slots = deserialize_parsed_slots(list(data.get("admin_schedule_preview", [])))
    errors = deserialize_errors(list(data.get("admin_schedule_errors", [])))
    if errors:
        await replace_inline_message_text(
            callback.message,
            build_schedule_preview_text(parsed_slots, errors),
            reply_markup=build_schedule_preview_keyboard(allow_confirm=False),
        )
        return
    repository = SlotRepository(db_session)

    created = 0
    skipped = 0
    for parsed_slot in parsed_slots:
        _, was_created = await repository.create_if_missing(
            parsed_slot_to_utc(parsed_slot, tz_name=settings.tz)
        )
        if was_created:
            created += 1
        else:
            skipped += 1

    await db_session.commit()
    await state.clear()

    if created == 0 and skipped > 0:
        notice_text = texts.ADMIN_SCHEDULE_ALL_DUPLICATES_TEXT
    elif skipped:
        notice_text = texts.ADMIN_SCHEDULE_ADDED_WITH_SKIPS_TEXT.format(
            created=created,
            skipped=skipped,
        )
    else:
        notice_text = texts.ADMIN_SCHEDULE_ADDED_TEXT.format(created=created)

    await replace_inline_message_text(
        callback.message,
        f"{notice_text}\n\n{texts.ADMIN_SCHEDULE_MENU_TEXT}",
        reply_markup=build_admin_schedule_menu(),
    )
    await remember_admin_panel(state, callback.message)


@router.callback_query(F.data == "admin_schedule:back")
async def schedule_back(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Return to the root schedule menu."""
    await callback.answer()
    if callback.message is not None:
        await show_schedule_home(
            callback.message,
            state=state,
            db_session=db_session,
            settings=settings,
            edit=True,
        )


@router.callback_query(F.data == "admin_schedule:week")
@router.callback_query(F.data.startswith("admin_schedule:week:"))
async def schedule_week(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Show slots for the next week."""
    await callback.answer()
    if callback.message is None:
        return
    page = 0 if callback.data == "admin_schedule:week" else int(callback.data.rsplit(":", 1)[-1])
    await show_schedule_week_page(
        callback.message,
        db_session=db_session,
        settings=settings,
        page=page,
        state=state,
        edit=True,
    )


@router.callback_query(F.data == "admin_schedule:month")
@router.callback_query(F.data.startswith("admin_schedule:month:page:"))
async def schedule_month(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Show slots for the next 30 days grouped by local day."""
    await callback.answer()
    if callback.message is None:
        return
    offset = 0
    if callback.data and callback.data.startswith("admin_schedule:month:page:"):
        offset = int(callback.data.rsplit(":", 1)[-1])
    await show_schedule_month_page(
        callback.message,
        db_session=db_session,
        settings=settings,
        offset=offset,
        state=state,
        edit=True,
    )


@router.callback_query(F.data == "admin_schedule:delete_menu")
async def schedule_delete_menu(callback: CallbackQuery) -> None:
    """Open the bulk-delete picker for schedule periods."""
    await callback.answer()
    if callback.message is None:
        return
    await replace_inline_message_text(
        callback.message,
        texts.ADMIN_SCHEDULE_DELETE_MENU_TEXT,
        reply_markup=build_admin_schedule_delete_menu(),
    )


@router.callback_query(F.data == "admin_schedule:noop")
async def schedule_noop(callback: CallbackQuery) -> None:
    """Acknowledge inert pagination-label buttons."""
    await callback.answer()


@router.callback_query(F.data.startswith("admin_schedule:delete_period:"))
async def schedule_delete_period_prompt(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Ask for confirmation before bulk-removing schedule slots in one period."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    period_kind = callback.data.rsplit(":", 1)[-1]
    deletable_slots, period_label = await get_schedule_delete_period_payload(
        db_session,
        settings=settings,
        period_kind=period_kind,
    )
    if not deletable_slots:
        if period_kind == "month":
            await show_schedule_month_page(
                callback.message,
                db_session=db_session,
                settings=settings,
                state=None,
                edit=True,
                notice_text=texts.ADMIN_SCHEDULE_DELETE_PERIOD_EMPTY_TEXT,
            )
        else:
            await show_schedule_week_page(
                callback.message,
                db_session=db_session,
                settings=settings,
                state=None,
                edit=True,
                notice_text=texts.ADMIN_SCHEDULE_DELETE_PERIOD_EMPTY_TEXT,
            )
        return

    await replace_inline_message_text(
        callback.message,
        texts.ADMIN_SCHEDULE_DELETE_PERIOD_CONFIRM_TEXT.format(
            period=period_label,
            count=len(deletable_slots),
        ),
        reply_markup=build_admin_schedule_delete_period_confirm_keyboard(period_kind),
    )


@router.callback_query(F.data.startswith("admin_schedule:delete_period_confirm:"))
async def schedule_delete_period_confirmed(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Delete all free/blocked schedule slots in one selected period."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    period_kind = callback.data.rsplit(":", 1)[-1]
    result = await admin_schedule_service.delete_schedule_period(
        db_session,
        tz_name=settings.tz,
        period_kind=period_kind,
    )
    if result.deleted_count == 0:
        notice_text = texts.ADMIN_SCHEDULE_DELETE_PERIOD_EMPTY_TEXT
    else:
        notice_text = texts.ADMIN_SCHEDULE_DELETE_PERIOD_DONE_TEXT.format(
            count=result.deleted_count,
            period=result.period_label,
        )

    if period_kind == "month":
        await show_schedule_month_page(
            callback.message,
            db_session=db_session,
            settings=settings,
            state=None,
            edit=True,
            notice_text=notice_text,
        )
        return
    await show_schedule_week_page(
        callback.message,
        db_session=db_session,
        settings=settings,
        state=None,
        edit=True,
        notice_text=notice_text,
    )


@router.callback_query(F.data.startswith("admin_schedule:open_client:"))
async def schedule_open_client_card(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Open the booked slot's client card and keep the schedule return context."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    parts = callback.data.split(":")
    slot_id = int(parts[2])
    origin_view, origin_value = parse_schedule_origin(parts, start_index=3)
    booking = await BookingRepository(db_session).get_by_slot_id(slot_id)
    if booking is None or booking.client is None:
        await show_schedule_slot_detail(
            callback.message,
            db_session=db_session,
            settings=settings,
            slot_id=slot_id,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    await show_client_card(
        callback.message,
        db_session=db_session,
        settings=settings,
        client_id=booking.client.id,
        back_callback=build_schedule_origin_callback(origin_view, origin_value),
        edit=True,
    )


@router.callback_query(F.data.startswith("admin_schedule:open_booking:"))
async def schedule_open_booking_card(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Open the booked slot's dedicated booking card from the schedule."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    parts = callback.data.split(":")
    slot_id = int(parts[2])
    origin_view, origin_value = parse_schedule_origin(parts, start_index=3)
    booking = await BookingRepository(db_session).get_by_slot_id(slot_id)
    if booking is None:
        await show_schedule_slot_detail(
            callback.message,
            db_session=db_session,
            settings=settings,
            slot_id=slot_id,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    await show_booking_card(
        callback.message,
        db_session=db_session,
        settings=settings,
        booking_id=booking.id,
        back_callback=build_schedule_origin_callback(origin_view, origin_value),
        edit=True,
    )


@router.callback_query(F.data.startswith("admin_schedule:no_show:"))
async def schedule_mark_no_show(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Mark a booked slot as no-show and update the client's risk flags."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    parts = callback.data.split(":")
    slot_id = int(parts[2])
    origin_view, origin_value = parse_schedule_origin(parts, start_index=3)
    booking = await BookingRepository(db_session).get_by_slot_id(slot_id)
    if booking is None or booking.client is None:
        await show_schedule_slot_detail(
            callback.message,
            db_session=db_session,
            settings=settings,
            slot_id=slot_id,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    anti_abuse_settings = await get_anti_abuse_settings(db_session)
    apply_booking_no_show(
        booking,
        no_show_strike_limit=anti_abuse_settings["no_show_strike_limit"],
        now_utc=datetime.now(UTC),
    )
    rescue_slot_id: int | None = None
    if booking.slot is not None and slot_is_rescuable(booking.slot):
        rescue_slot_id = booking.slot.id
    await record_rate_event(
        db_session,
        user_id=booking.client.id,
        kind="no_show",
        metadata={"booking_id": booking.id, "slot_id": slot_id},
    )
    await db_session.commit()

    await show_schedule_slot_detail(
        callback.message,
        db_session=db_session,
        settings=settings,
        slot_id=slot_id,
        origin_view=origin_view,
        origin_value=origin_value,
        state=state,
        edit=True,
        notice_text=(
            f"{texts.ADMIN_SCHEDULE_NO_SHOW_MARKED_TEXT}\n"
            f"Теперь strikes: {booking.client.strikes}/"
            f"{anti_abuse_settings['no_show_strike_limit'] * 2}"
        ),
    )
    await send_text_to_user(
        callback.bot,
        tg_id=booking.client.tg_id,
        text=build_no_show_client_notice(
            strikes=booking.client.strikes,
            strike_limit=anti_abuse_settings["no_show_strike_limit"] * 2,
            requires_manual_approval=booking.client.requires_manual_approval,
        ),
    )
    if rescue_slot_id is not None:
        await send_rescue_slot_prompt_to_admins(
            callback.bot,
            db_session=db_session,
            settings=settings,
            slot_id=rescue_slot_id,
            exclude_user_id=booking.client.id,
            client_id=booking.client.id,
        )


@router.callback_query(F.data.startswith("admin_schedule:slot:"))
async def schedule_open_slot_detail(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Open one slot detail from the weekly list."""
    await callback.answer()
    if callback.message is None:
        return
    parts = callback.data.split(":")
    slot_id = int(parts[2])
    origin_view, origin_value = parse_schedule_origin(parts, start_index=3)
    await show_schedule_slot_detail(
        callback.message,
        db_session=db_session,
        settings=settings,
        slot_id=slot_id,
        origin_view=origin_view,
        origin_value=origin_value,
        state=state,
        edit=True,
    )


@router.callback_query(F.data.startswith("admin_schedule:move:"))
async def schedule_move_start(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Start moving a free or blocked schedule slot."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    parts = callback.data.split(":")
    slot_id = int(parts[2])
    origin_view, origin_value = parse_schedule_origin(parts, start_index=3)
    repository = SlotRepository(db_session)
    slot = await repository.get_by_id(slot_id)
    if slot is None:
        await show_schedule_origin_page(
            callback.message,
            db_session=db_session,
            settings=settings,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text="Слот уже не существует.",
        )
        return
    if slot.status == SlotStatus.BOOKED:
        await show_schedule_slot_detail(
            callback.message,
            db_session=db_session,
            settings=settings,
            slot_id=slot_id,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text=texts.ADMIN_SCHEDULE_MOVE_BOOKED_FORBIDDEN_TEXT,
        )
        return

    await state.set_state(AdminScheduleMove.input_text)
    await state.update_data(
        admin_schedule_move_slot_id=slot_id,
        admin_schedule_move_origin_view=origin_view,
        admin_schedule_move_origin_value=origin_value,
    )
    await show_schedule_move_prompt(callback.message, state=state, edit=True)


@router.message(StateFilter(AdminScheduleMove.input_text))
async def schedule_move_parse_input(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Parse the new date/time and move the selected free or blocked slot."""
    data = await state.get_data()
    slot_id = int(data.get("admin_schedule_move_slot_id", 0))
    origin_view = str(data.get("admin_schedule_move_origin_view") or "week")
    origin_value = int(
        data.get(
            "admin_schedule_move_origin_value",
            data.get("admin_schedule_move_page", 0),
        )
    )
    repository = SlotRepository(db_session)
    slot = await repository.get_by_id(slot_id)
    if slot is None:
        await clear_state_preserving_admin_panel(state)
        await show_schedule_origin_page(
            message,
            db_session=db_session,
            settings=settings,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            notice_text="Слот уже не существует.",
        )
        return
    if slot.status == SlotStatus.BOOKED:
        await clear_state_preserving_admin_panel(state)
        await show_schedule_slot_detail(
            message,
            db_session=db_session,
            settings=settings,
            slot_id=slot_id,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            notice_text=texts.ADMIN_SCHEDULE_MOVE_BOOKED_FORBIDDEN_TEXT,
        )
        return

    result = await admin_schedule_service.move_schedule_slot(
        db_session,
        slot_id=slot.id,
        raw_text=message.text or "",
        tz_name=settings.tz,
    )
    if not result.ok and result.reason == "invalid":
        await show_schedule_move_prompt(
            message,
            state=state,
            edit=False,
            notice_text=texts.ADMIN_SCHEDULE_MOVE_INVALID_TEXT,
        )
        return
    if not result.ok and result.reason == "collision":
        await show_schedule_move_prompt(
            message,
            state=state,
            edit=False,
            notice_text=texts.ADMIN_SCHEDULE_MOVE_COLLISION_TEXT,
        )
        return
    if not result.ok and result.reason == "missing":
        await clear_state_preserving_admin_panel(state)
        await show_schedule_origin_page(
            message,
            db_session=db_session,
            settings=settings,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            notice_text="Слот уже не существует.",
        )
        return
    if not result.ok and result.reason == "booked":
        await clear_state_preserving_admin_panel(state)
        await show_schedule_slot_detail(
            message,
            db_session=db_session,
            settings=settings,
            slot_id=slot_id,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            notice_text=texts.ADMIN_SCHEDULE_MOVE_BOOKED_FORBIDDEN_TEXT,
        )
        return
    if result.slot is None:
        await show_schedule_move_prompt(
            message,
            state=state,
            edit=False,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    await clear_state_preserving_admin_panel(state)
    await show_schedule_slot_detail(
        message,
        db_session=db_session,
        settings=settings,
        slot_id=result.slot.id,
        origin_view=origin_view,
        origin_value=origin_value,
        state=state,
        notice_text=texts.ADMIN_SCHEDULE_MOVE_DONE_TEXT,
    )


@router.callback_query(F.data.startswith("admin_schedule:delete:"))
async def schedule_delete_slot(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Ask for confirmation before deleting a free or blocked slot."""
    await callback.answer()
    if callback.message is None:
        return

    parts = callback.data.split(":")
    slot_id = int(parts[2])
    origin_view, origin_value = parse_schedule_origin(parts, start_index=3)
    repository = SlotRepository(db_session)
    slot = await repository.get_by_id(slot_id)
    if slot is None:
        await show_schedule_origin_page(
            callback.message,
            db_session=db_session,
            settings=settings,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text="Слот уже не существует.",
        )
        return
    if slot.status == SlotStatus.BOOKED:
        await show_schedule_slot_detail(
            callback.message,
            db_session=db_session,
            settings=settings,
            slot_id=slot_id,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text=texts.ADMIN_SCHEDULE_BOOKED_DELETE_FORBIDDEN_TEXT,
        )
        return

    await replace_inline_message_text(
        callback.message,
        "Удалить это окошко из расписания? Это действие нельзя отменить.",
        reply_markup=build_admin_schedule_delete_confirm_keyboard(
            slot_id=slot_id,
            origin_view=origin_view,
            origin_value=origin_value,
        ),
    )


@router.callback_query(F.data.startswith("admin_schedule:delete_confirm:"))
async def schedule_delete_slot_confirmed(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Delete a free or blocked slot after explicit confirmation."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    parts = callback.data.split(":")
    slot_id = int(parts[2])
    origin_view, origin_value = parse_schedule_origin(parts, start_index=3)
    result = await admin_schedule_service.delete_schedule_slot(
        db_session,
        slot_id=slot_id,
    )
    if not result.ok and result.reason == "missing":
        await show_schedule_origin_page(
            callback.message,
            db_session=db_session,
            settings=settings,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text="Слот уже не существует.",
        )
        return
    if not result.ok and result.reason == "booked":
        await show_schedule_slot_detail(
            callback.message,
            db_session=db_session,
            settings=settings,
            slot_id=slot_id,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text=texts.ADMIN_SCHEDULE_BOOKED_DELETE_FORBIDDEN_TEXT,
        )
        return
    await show_schedule_origin_page(
        callback.message,
        db_session=db_session,
        settings=settings,
        origin_view=origin_view,
        origin_value=origin_value,
        state=state,
        edit=True,
        notice_text=texts.ADMIN_SCHEDULE_SLOT_DELETED_TEXT,
    )


@router.callback_query(F.data.startswith("admin_schedule:block:"))
async def schedule_block_slot(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Block a slot."""
    await callback.answer()
    if callback.message is None:
        return

    parts = callback.data.split(":")
    slot_id = int(parts[2])
    origin_view, origin_value = parse_schedule_origin(parts, start_index=3)
    result = await admin_schedule_service.block_schedule_slot(
        db_session,
        slot_id=slot_id,
    )
    if not result.ok and result.reason == "missing":
        await show_schedule_origin_page(
            callback.message,
            db_session=db_session,
            settings=settings,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text="Слот уже не существует.",
        )
        return
    if not result.ok and result.reason == "booked":
        await show_schedule_slot_detail(
            callback.message,
            db_session=db_session,
            settings=settings,
            slot_id=slot_id,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text=texts.ADMIN_SCHEDULE_BOOKED_DELETE_FORBIDDEN_TEXT,
        )
        return
    await show_schedule_slot_detail(
        callback.message,
        db_session=db_session,
        settings=settings,
        slot_id=slot_id,
        origin_view=origin_view,
        origin_value=origin_value,
        state=state,
        edit=True,
        notice_text=texts.ADMIN_SCHEDULE_SLOT_BLOCKED_TEXT,
    )


@router.callback_query(F.data.startswith("admin_schedule:unblock:"))
async def schedule_unblock_slot(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Unblock a slot."""
    await callback.answer()
    if callback.message is None:
        return

    parts = callback.data.split(":")
    slot_id = int(parts[2])
    origin_view, origin_value = parse_schedule_origin(parts, start_index=3)
    result = await admin_schedule_service.unblock_schedule_slot(
        db_session,
        slot_id=slot_id,
    )
    if not result.ok and result.reason == "missing":
        await show_schedule_origin_page(
            callback.message,
            db_session=db_session,
            settings=settings,
            origin_view=origin_view,
            origin_value=origin_value,
            state=state,
            edit=True,
            notice_text="Слот уже не существует.",
        )
        return
    await show_schedule_slot_detail(
        callback.message,
        db_session=db_session,
        settings=settings,
        slot_id=slot_id,
        origin_view=origin_view,
        origin_value=origin_value,
        state=state,
        edit=True,
        notice_text=texts.ADMIN_SCHEDULE_SLOT_UNBLOCKED_TEXT,
    )
