from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import (
    clear_state_preserving_admin_panel,
    send_admin_panel,
)
from src.bot.handlers.admin.booking_cards import show_booking_card
from src.bot.keyboards.admin import (
    build_admin_all_bookings_delete_period_keyboard,
    build_admin_all_bookings_keyboard,
    build_admin_all_bookings_summary_keyboard,
)
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.models import Booking, BookingStatus
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.settings import SettingRepository
from src.services.booking import (
    format_local_datetime,
    format_service_price,
)
from src.services.calendar_sync import delete_booking_event
from src.services.runtime_settings import get_runtime_tz

router = Router(name="admin_all_bookings")
PAGE_DAYS = 14
WEEKDAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
logger = logging.getLogger(__name__)

PAYMENT_ICONS = {
    "cash": "💵",
    "transfer": "💳",
}

STATUS_ICONS = {
    BookingStatus.PENDING_MASTER: "⏳",
    BookingStatus.CONFIRMED: "✅",
    BookingStatus.COMPLETED: "✅",
    BookingStatus.CANCELLED_BY_CLIENT: "✖️",
    BookingStatus.CANCELLED_BY_MASTER: "✖️",
    BookingStatus.NO_SHOW: "⚠️",
}


def local_range_to_utc(
    *,
    start_local_date: date,
    end_local_date: date,
    tz_name: str,
) -> tuple[datetime, datetime]:
    """Convert an inclusive local-date range into UTC datetimes."""
    tz = ZoneInfo(tz_name)
    start_utc = datetime.combine(start_local_date, time.min, tzinfo=tz).astimezone(UTC)
    end_utc = datetime.combine(end_local_date, time.max, tzinfo=tz).astimezone(UTC)
    return start_utc, end_utc


def page_dates(
    *,
    offset_days: int,
    tz_name: str,
    now: datetime | None = None,
) -> tuple[date, date]:
    """Return local start/end dates for one all-bookings page."""
    current = now or datetime.now(ZoneInfo(tz_name))
    start_local_date = current.date() + timedelta(days=max(0, offset_days))
    return start_local_date, start_local_date + timedelta(days=PAGE_DAYS - 1)


def format_period_label(start_local_date: date, end_local_date: date) -> str:
    return f"{start_local_date:%d.%m} – {end_local_date:%d.%m}"


def _booking_client_label(booking: Booking) -> str:
    if booking.client is None:
        return "Клиентка"
    return booking.client.display_name.strip() or "Клиентка"


def _booking_status_icon(booking: Booking) -> str:
    return STATUS_ICONS.get(booking.status, "•")


def _booking_payment_icon(booking: Booking) -> str:
    return PAYMENT_ICONS.get(booking.payment_method or "transfer", "💳")


def render_booking_line(booking: Booking, *, tz_name: str) -> str:
    """Render one booking row inside the admin all-bookings text."""
    if booking.slot is None or booking.base_service is None:
        return ""
    local_dt = format_local_datetime(booking.slot.start_at, tz_name)
    price = "уточнить" if booking.has_variable_price else format_service_price(booking.base_service)
    if not booking.has_variable_price:
        price = f"{booking.fixed_price}₽"
    return (
        f"{local_dt:%H:%M} · "
        f"{_booking_client_label(booking)} · "
        f"{booking.base_service.name} · "
        f"{price} · "
        f"{_booking_payment_icon(booking)} · "
        f"{_booking_status_icon(booking)}"
    )


def build_all_bookings_text(
    bookings: list[Booking],
    *,
    start_local_date: date,
    end_local_date: date,
    tz_name: str,
    offset_days: int,
    has_next: bool,
    show_cancelled: bool,
) -> str:
    """Render the admin all-bookings page."""
    page_number = offset_days // PAGE_DAYS + 1
    total_pages = page_number + (1 if has_next else 0)
    shown_label = "активные + отменённые" if show_cancelled else "активные"
    lines = [
        f"📋 Все записи · стр. {page_number}/{total_pages}",
        "",
        f"Период: {format_period_label(start_local_date, end_local_date)}",
        f"Показано: {shown_label}",
        "",
    ]
    if not bookings:
        lines.append(texts.ADMIN_ALL_BOOKINGS_EMPTY_TEXT)
        return "\n".join(lines)

    bookings_by_day: dict[date, list[Booking]] = defaultdict(list)
    for booking in bookings:
        if booking.slot is None:
            continue
        local_day = format_local_datetime(booking.slot.start_at, tz_name).date()
        bookings_by_day[local_day].append(booking)

    for local_day in sorted(bookings_by_day):
        lines.append(f"🗓 {WEEKDAY_SHORT[local_day.weekday()]}, {local_day:%d.%m}")
        lines.append("─────────────────")
        lines.append("")
        for booking in bookings_by_day[local_day]:
            line = render_booking_line(booking, tz_name=tz_name)
            if line:
                lines.append(line)
        lines.append("")

    return "\n".join(lines).rstrip()


def build_all_bookings_summary_text(
    bookings: list[Booking],
    *,
    start_local_date: date,
    end_local_date: date,
) -> str:
    """Render a compact summary for the current all-bookings period."""
    active_count = sum(
        1
        for booking in bookings
        if booking.status in {BookingStatus.PENDING_MASTER, BookingStatus.CONFIRMED}
    )
    pending_count = sum(1 for booking in bookings if booking.status == BookingStatus.PENDING_MASTER)
    confirmed_count = sum(1 for booking in bookings if booking.status == BookingStatus.CONFIRMED)
    completed_count = sum(1 for booking in bookings if booking.status == BookingStatus.COMPLETED)
    cancelled_count = sum(
        1
        for booking in bookings
        if booking.status in {BookingStatus.CANCELLED_BY_CLIENT, BookingStatus.CANCELLED_BY_MASTER}
    )
    no_show_count = sum(1 for booking in bookings if booking.status == BookingStatus.NO_SHOW)
    known_revenue = sum(
        booking.fixed_price
        for booking in bookings
        if booking.status
        not in {BookingStatus.CANCELLED_BY_CLIENT, BookingStatus.CANCELLED_BY_MASTER}
        and booking.status != BookingStatus.NO_SHOW
        and not booking.has_variable_price
    )
    cash_count = sum(
        1
        for booking in bookings
        if booking.status
        not in {BookingStatus.CANCELLED_BY_CLIENT, BookingStatus.CANCELLED_BY_MASTER}
        and booking.status != BookingStatus.NO_SHOW
        and booking.payment_method == "cash"
    )
    transfer_count = sum(
        1
        for booking in bookings
        if booking.status
        not in {BookingStatus.CANCELLED_BY_CLIENT, BookingStatus.CANCELLED_BY_MASTER}
        and booking.status != BookingStatus.NO_SHOW
        and booking.payment_method != "cash"
    )
    variable_count = sum(
        1
        for booking in bookings
        if booking.status
        not in {BookingStatus.CANCELLED_BY_CLIENT, BookingStatus.CANCELLED_BY_MASTER}
        and booking.status != BookingStatus.NO_SHOW
        and booking.has_variable_price
    )
    lines = [
        "📊 Сводка периода",
        f"{format_period_label(start_local_date, end_local_date)}",
        "",
        f"Активных записей: {active_count}",
        f"Подтверждены: {confirmed_count}",
        f"Ждут ответа: {pending_count}",
        f"Отменены: {cancelled_count}",
        f"No-show: {no_show_count}",
    ]
    if completed_count:
        lines.append(f"Завершены: {completed_count}")
    lines.extend(
        [
            "",
            f"Ожидаемая выручка: {known_revenue}₽",
            f"Наличными: {cash_count}",
            f"Переводом: {transfer_count}",
        ]
    )
    if variable_count:
        lines.append(f"С плавающей ценой: {variable_count}")
    return "\n".join(lines)


async def load_all_bookings_page(
    db_session: AsyncSession,
    *,
    settings: Settings,
    offset_days: int,
    show_cancelled: bool,
) -> tuple[list[Booking], bool, date, date, str]:
    """Load bookings and pagination metadata for one admin page."""
    settings_repository = SettingRepository(db_session)
    tz_name = await get_runtime_tz(settings_repository, settings=settings)
    start_local_date, end_local_date = page_dates(offset_days=offset_days, tz_name=tz_name)
    start_utc, end_utc = local_range_to_utc(
        start_local_date=start_local_date,
        end_local_date=end_local_date,
        tz_name=tz_name,
    )
    repository = BookingRepository(db_session)
    bookings = await repository.list_for_range(
        start_utc,
        end_utc,
        include_cancelled=show_cancelled,
    )

    next_start = end_local_date + timedelta(days=1)
    next_end = next_start + timedelta(days=PAGE_DAYS - 1)
    next_start_utc, next_end_utc = local_range_to_utc(
        start_local_date=next_start,
        end_local_date=next_end,
        tz_name=tz_name,
    )
    has_next = bool(
        await repository.list_for_range(
            next_start_utc,
            next_end_utc,
            include_cancelled=show_cancelled,
        )
    )
    return bookings, has_next, start_local_date, end_local_date, tz_name


async def show_all_bookings_page(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
    offset_days: int = 0,
    show_cancelled: bool = False,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Show the all-bookings admin page."""
    bookings, has_next, start_local_date, end_local_date, tz_name = await load_all_bookings_page(
        db_session,
        settings=settings,
        offset_days=offset_days,
        show_cancelled=show_cancelled,
    )
    await state.update_data(
        admin_bookings_offset_days=offset_days,
        admin_bookings_show_cancelled=show_cancelled,
    )
    text = build_all_bookings_text(
        bookings,
        start_local_date=start_local_date,
        end_local_date=end_local_date,
        tz_name=tz_name,
        offset_days=offset_days,
        has_next=has_next,
        show_cancelled=show_cancelled,
    )
    if notice_text:
        text = f"{notice_text}\n\n{text}"
    markup = build_admin_all_bookings_keyboard(
        bookings,
        offset_days=offset_days,
        show_cancelled=show_cancelled,
        has_prev=offset_days > 0,
        has_next=has_next,
        tz_name=tz_name,
    )
    if edit:
        await replace_inline_message_text(message, text, reply_markup=markup)
        return
    await send_admin_panel(message, state, text=text, reply_markup=markup)


@router.message(lambda message: message.text == "📋 Все записи")
async def open_all_bookings_section(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the upcoming bookings admin section."""
    if not is_admin:
        return
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await show_all_bookings_page(
        message,
        state,
        db_session=db_session,
        settings=settings,
    )


@router.callback_query(F.data.startswith("admin_bookings:page:"))
async def open_all_bookings_page(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open one paginated all-bookings page."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    _, _, offset_raw, show_cancelled_raw = callback.data.split(":")
    await show_all_bookings_page(
        callback.message,
        state,
        db_session=db_session,
        settings=settings,
        offset_days=max(0, int(offset_raw)),
        show_cancelled=show_cancelled_raw == "1",
        edit=True,
    )


@router.callback_query(F.data.startswith("admin_bookings:toggle_cancelled:"))
async def toggle_cancelled_bookings(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Toggle cancelled bookings visibility for the current admin page."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    offset_days = int(callback.data.rsplit(":", 1)[-1])
    data = await state.get_data()
    show_cancelled = not bool(data.get("admin_bookings_show_cancelled", False))
    await show_all_bookings_page(
        callback.message,
        state,
        db_session=db_session,
        settings=settings,
        offset_days=offset_days,
        show_cancelled=show_cancelled,
        edit=True,
    )


@router.callback_query(F.data.startswith("admin_bookings:open:"))
async def open_booking_client_card(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the dedicated booking card for a selected booking (legacy callback)."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    parts = callback.data.split(":")
    booking_id = int(parts[2])
    booking = await BookingRepository(db_session).get_by_id(booking_id)
    if booking is None:
        await callback.answer(texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT, show_alert=True)
        return

    data = await state.get_data()
    offset_days = int(data.get("admin_bookings_offset_days", 0))
    show_cancelled = bool(data.get("admin_bookings_show_cancelled", False))
    back_callback = f"admin_bookings:page:{offset_days}:{int(show_cancelled)}"
    await show_booking_card(
        callback.message,
        db_session=db_session,
        settings=settings,
        booking_id=booking.id,
        back_callback=back_callback,
        edit=True,
    )


@router.callback_query(F.data.startswith("admin_bookings:summary:"))
async def open_all_bookings_summary(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open a compact summary for the visible all-bookings period."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    _, _, offset_raw, show_cancelled_raw = callback.data.split(":")
    offset_days = max(0, int(offset_raw))
    show_cancelled = show_cancelled_raw == "1"
    bookings, _, start_local_date, end_local_date, _ = await load_all_bookings_page(
        db_session,
        settings=settings,
        offset_days=offset_days,
        show_cancelled=show_cancelled,
    )
    await state.update_data(
        admin_bookings_offset_days=offset_days,
        admin_bookings_show_cancelled=show_cancelled,
    )
    await replace_inline_message_text(
        callback.message,
        build_all_bookings_summary_text(
            bookings,
            start_local_date=start_local_date,
            end_local_date=end_local_date,
        ),
        reply_markup=build_admin_all_bookings_summary_keyboard(
            offset_days=offset_days,
            show_cancelled=show_cancelled,
        ),
    )


@router.callback_query(F.data.startswith("admin_bookings:delete_period:"))
async def ask_delete_bookings_period(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Ask for confirmation before deleting bookings for the current page period."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    _, _, offset_raw, show_cancelled_raw = callback.data.split(":")
    offset_days = max(0, int(offset_raw))
    show_cancelled = show_cancelled_raw == "1"
    bookings, _, start_local_date, end_local_date, _ = await load_all_bookings_page(
        db_session,
        settings=settings,
        offset_days=offset_days,
        show_cancelled=show_cancelled,
    )
    if not bookings:
        await show_all_bookings_page(
            callback.message,
            state,
            db_session=db_session,
            settings=settings,
            offset_days=offset_days,
            show_cancelled=show_cancelled,
            edit=True,
            notice_text=texts.ADMIN_ALL_BOOKINGS_DELETE_PERIOD_EMPTY_TEXT,
        )
        return

    await replace_inline_message_text(
        callback.message,
        texts.ADMIN_ALL_BOOKINGS_DELETE_PERIOD_CONFIRM_TEXT.format(
            period=format_period_label(start_local_date, end_local_date),
            count=len(bookings),
        ),
        reply_markup=build_admin_all_bookings_delete_period_keyboard(
            offset_days=offset_days,
            show_cancelled=show_cancelled,
        ),
    )


@router.callback_query(F.data.startswith("admin_bookings:delete_period_confirm:"))
async def delete_bookings_period(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Delete all bookings currently visible for one paginated period."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    _, _, offset_raw, show_cancelled_raw = callback.data.split(":")
    offset_days = max(0, int(offset_raw))
    show_cancelled = show_cancelled_raw == "1"
    bookings, _, start_local_date, end_local_date, _ = await load_all_bookings_page(
        db_session,
        settings=settings,
        offset_days=offset_days,
        show_cancelled=show_cancelled,
    )
    if not bookings:
        await show_all_bookings_page(
            callback.message,
            state,
            db_session=db_session,
            settings=settings,
            offset_days=offset_days,
            show_cancelled=show_cancelled,
            edit=True,
            notice_text=texts.ADMIN_ALL_BOOKINGS_DELETE_PERIOD_EMPTY_TEXT,
        )
        return

    for booking in bookings:
        if not booking.gcal_event_id:
            continue
        try:
            delete_booking_event(settings, event_id=booking.gcal_event_id)
        except Exception:
            logger.exception(
                "Failed to delete Google Calendar event for bulk-removed booking %s",
                booking.id,
            )

    deleted_count = await BookingRepository(db_session).delete_bookings(bookings)
    await db_session.commit()
    await show_all_bookings_page(
        callback.message,
        state,
        db_session=db_session,
        settings=settings,
        offset_days=offset_days,
        show_cancelled=show_cancelled,
        edit=True,
        notice_text=texts.ADMIN_ALL_BOOKINGS_DELETE_PERIOD_DONE_TEXT.format(
            count=deleted_count,
            period=format_period_label(start_local_date, end_local_date),
        ),
    )
