from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import (
    clear_state_preserving_admin_panel,
    remember_admin_panel,
    send_admin_panel,
)
from src.bot.handlers.admin.rescue_slots import send_rescue_slot_prompt_to_admins
from src.bot.keyboards.admin import (
    build_admin_booking_card_action_callback,
    build_admin_booking_card_callback,
    build_admin_booking_card_keyboard,
)
from src.bot.states import AdminBookingCardReschedule, AdminClientMessage
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.models import Booking, BookingCreatedVia, BookingStatus, Service, SlotStatus
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.slots import SlotRepository
from src.services.anti_abuse import get_anti_abuse_settings, record_rate_event
from src.services.booking import (
    apply_booking_no_show,
    booking_needs_manual_resolution,
    build_booking_service_label,
    build_no_show_client_notice,
    cancel_booking_by_master,
    format_booking_price,
    format_local_datetime,
    format_payment_method_label,
    format_time_until_visit,
    get_booking_status_label,
    get_cancel_reason_label,
    reschedule_booking,
)
from src.services.calendar_sync import (
    CalendarBookingInfo,
    CalendarClientInfo,
    delete_booking_event,
    update_booking_event,
)
from src.services.morning_summary import refresh_live_morning_summary_for_today
from src.services.notifications import send_text_to_user
from src.services.rescue_slots import slot_is_rescuable
from src.services.runtime_settings import get_int_setting, get_runtime_tz
from src.services.schedule_parser import parse_schedule

router = Router(name="admin_booking_cards")
WEEKDAY_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
logger = logging.getLogger(__name__)


def build_booking_card_return_callback(back_parts: list[str]) -> str:
    """Restore the parent callback encoded inside one booking-card action."""
    if not back_parts:
        return "admin_menu:home"

    kind = back_parts[0]
    if kind == "all" and len(back_parts) >= 3:
        return f"admin_bookings:page:{back_parts[1]}:{back_parts[2]}"
    if kind == "client" and len(back_parts) >= 3:
        client_id = back_parts[1]
        origin = back_parts[2]
        if origin == "list" and len(back_parts) >= 4:
            return f"admin_clients:bookings:{client_id}:list:{back_parts[3]}"
        if origin == "approval" and len(back_parts) >= 4:
            return f"admin_clients:bookings:{client_id}:approval:{back_parts[3]}"
        if origin == "late_notice" and len(back_parts) >= 4:
            return f"admin_clients:bookings:{client_id}:late_notice:{back_parts[3]}"
        if origin == "schedule" and len(back_parts) >= 5:
            if back_parts[3] == "week":
                return f"admin_clients:bookings:{client_id}:schedule:week:{back_parts[4]}"
            if back_parts[3] == "month":
                return f"admin_clients:bookings:{client_id}:schedule:month:{back_parts[4]}"
        return f"admin_clients:bookings:{client_id}:home"
    return "admin_menu:home"


def build_booking_card_back_keyboard(
    *,
    booking_id: int,
    back_callback: str,
    label: str = "⬅️ К записи",
) -> InlineKeyboardMarkup:
    """Build a one-button keyboard that returns to the booking card."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=build_admin_booking_card_callback(
                        booking_id,
                        back_callback=back_callback,
                    ),
                )
            ]
        ]
    )


def build_booking_card_confirm_keyboard(
    *,
    action: str,
    booking_id: int,
    back_callback: str,
    confirm_label: str,
) -> InlineKeyboardMarkup:
    """Build confirmation controls for one risky booking-card action."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=confirm_label,
                    callback_data=build_admin_booking_card_action_callback(
                        f"{action}_confirm",
                        booking_id=booking_id,
                        back_callback=back_callback,
                    ),
                )
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Не менять",
                    callback_data=build_admin_booking_card_callback(
                        booking_id,
                        back_callback=back_callback,
                    ),
                )
            ],
        ]
    )


def parse_booking_action_parts(
    callback_data: str,
    *,
    has_client_id: bool = False,
) -> tuple[int, int | None, str]:
    """Parse one booking-card action callback into ids + back target."""
    parts = callback_data.split(":")
    booking_id = int(parts[2])
    if has_client_id:
        client_id = int(parts[3])
        back_callback = build_booking_card_return_callback(parts[4:])
        return booking_id, client_id, back_callback
    back_callback = build_booking_card_return_callback(parts[3:])
    return booking_id, None, back_callback


def build_calendar_booking_info_from_booking(
    booking: Booking,
    *,
    addons: list[Service],
) -> CalendarBookingInfo:
    """Build the calendar payload for one already confirmed booking."""
    if booking.slot is None or booking.base_service is None or booking.client is None:
        raise ValueError("Booking card is missing relationships required for calendar sync")

    return CalendarBookingInfo(
        booking_id=booking.id,
        start_at=booking.slot.start_at,
        duration_min=booking.base_service.duration_min
        + sum(addon.duration_min for addon in addons),
        base_service_name=booking.base_service.name,
        addon_names=[addon.name for addon in addons],
        client=CalendarClientInfo(
            display_name=booking.client.display_name,
            tg_id=booking.client.tg_id,
            tg_username=booking.client.tg_username,
            phone=booking.client.phone,
            note=booking.client.note,
        ),
        design_comment=booking.design_comment,
    )


async def load_booking_addons(db_session: AsyncSession, booking: Booking) -> list[Service]:
    """Load add-on services referenced by one booking."""
    addon_ids: list[int] = []
    raw_addons = booking.addons or []
    addon_items = raw_addons if isinstance(raw_addons, (list, tuple)) else [raw_addons]
    for item in addon_items:
        if not isinstance(item, (int, str)):
            continue
        try:
            addon_ids.append(int(item))
        except (TypeError, ValueError):
            continue
    if not addon_ids:
        return []
    result = await db_session.execute(select(Service).where(Service.id.in_(addon_ids)))
    services_by_id = {service.id: service for service in result.scalars().all()}
    return [services_by_id[addon_id] for addon_id in addon_ids if addon_id in services_by_id]


def render_admin_booking_card_text(
    booking: Booking,
    *,
    addons: list[Service],
    tz_name: str,
) -> str:
    """Render one dedicated admin booking card."""
    client_name = (
        booking.client.display_name.strip()
        if booking.client is not None and booking.client.display_name
        else "Клиентка"
    )
    username = (
        f"@{booking.client.tg_username}"
        if booking.client is not None and booking.client.tg_username
        else "без username"
    )
    if booking.base_service is None:
        service_label = "Услуга удалена"
    else:
        service_label = build_booking_service_label(booking.base_service, addons)

    lines = ["📅 Запись", ""]
    if booking.slot is None or booking.slot.start_at is None:
        lines.extend(["Дата и время уточняются", ""])
    else:
        local_dt = format_local_datetime(booking.slot.start_at, tz_name)
        lines.extend(
            [
                f"{WEEKDAY_SHORT[local_dt.weekday()]}, {local_dt:%d.%m} · {local_dt:%H:%M}",
                "",
            ]
        )

    lines.extend(
        [
            f"👤 {client_name} · {username}",
            f"💅 {service_label}",
            f"💳 {format_payment_method_label(booking.payment_method)}",
            f"💰 {format_booking_price(booking)}",
            f"✨ {get_booking_status_label(booking.status)}",
        ]
    )

    if booking.created_at is not None:
        created_local = format_local_datetime(booking.created_at, tz_name)
        lines.extend(["", f"Создана: {created_local:%d.%m · %H:%M}"])
    if booking.created_via == BookingCreatedVia.BOT:
        lines.append("Источник: через бот")
    elif booking.created_via == BookingCreatedVia.ADMIN_MANUAL:
        lines.append("Источник: вручную")
    if booking.slot is not None and booking.slot.start_at is not None:
        start_at = (
            booking.slot.start_at
            if booking.slot.start_at.tzinfo is not None
            else booking.slot.start_at.replace(tzinfo=UTC)
        )
        if start_at > datetime.now(UTC):
            lines.append(f"До записи: {format_time_until_visit(start_at)}")
        elif booking_needs_manual_resolution(booking):
            lines.extend(
                [
                    "⚠️ Клиентка не подтвердила 2ч-напоминание.",
                    "Нужна ручная развязка: no-show, отмена или подтверждение визита.",
                ]
            )

    design_photos = booking.design_photos or []
    if isinstance(design_photos, str):
        design_photo_count = 1 if design_photos.strip() else 0
    else:
        design_photo_count = len(design_photos)
    if design_photo_count:
        lines.extend(["", f"📎 Референсы: {design_photo_count} фото"])
    if booking.design_comment:
        lines.extend(["", f"📝 Комментарий: {booking.design_comment}"])
    if booking.status in {BookingStatus.CANCELLED_BY_CLIENT, BookingStatus.CANCELLED_BY_MASTER}:
        reason = get_cancel_reason_label(
            booking.cancel_reason_code or "",
            booking.cancel_reason_text,
        )
        lines.extend(["", f"Причина отмены: {reason}"])
    return "\n".join(lines)


async def build_booking_card_panel(
    *,
    db_session: AsyncSession,
    settings: Settings,
    booking_id: int,
    back_callback: str,
    notice_text: str | None = None,
) -> tuple[str, object] | None:
    """Build one admin booking-card text and keyboard."""
    repository = BookingRepository(db_session)
    booking = await repository.get_by_id(booking_id)
    if booking is None:
        return None

    settings_repository = SettingRepository(db_session)
    tz_name = await get_runtime_tz(settings_repository, settings=settings)
    addons = await load_booking_addons(db_session, booking)
    text = render_admin_booking_card_text(booking, addons=addons, tz_name=tz_name)
    if notice_text:
        text = f"{notice_text}\n\n{text}"
    markup = build_admin_booking_card_keyboard(
        booking_id=booking.id,
        client_id=booking.client_id,
        back_callback=back_callback,
        status=booking.status,
        has_slot=booking.slot_id is not None,
    )
    return text, markup


async def restore_booking_card_panel(
    target: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
    booking_id: int,
    back_callback: str,
    notice_text: str | None = None,
) -> None:
    """Render one booking card back into the remembered admin panel."""
    panel = await build_booking_card_panel(
        db_session=db_session,
        settings=settings,
        booking_id=booking_id,
        back_callback=back_callback,
        notice_text=notice_text,
    )
    if panel is None:
        await send_admin_panel(
            target,
            state,
            text=texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT,
            reply_markup=build_booking_card_back_keyboard(
                booking_id=booking_id,
                back_callback=back_callback,
                label="⬅️ Назад",
            ),
        )
        return
    text, markup = panel
    await send_admin_panel(target, state, text=text, reply_markup=markup)


def parse_one_reschedule_target(
    raw_text: str, *, tz_name: str
) -> tuple[datetime | None, str | None]:
    """Parse exactly one admin-provided reschedule datetime."""
    local_today = datetime.now(ZoneInfo(tz_name)).date()
    parsed_slots, errors = parse_schedule(raw_text, tz_name, local_today)
    if errors or len(parsed_slots) != 1:
        return None, texts.ADMIN_BOOKING_CARD_RESCHEDULE_INVALID_TEXT
    parsed = parsed_slots[0]
    local_dt = datetime.combine(parsed.date, parsed.time, tzinfo=ZoneInfo(tz_name))
    start_at = local_dt.astimezone(UTC)
    if start_at <= datetime.now(UTC):
        return None, texts.ADMIN_BOOKING_CARD_RESCHEDULE_PAST_TEXT
    return start_at, None


async def show_booking_card(
    target: Message,
    *,
    db_session: AsyncSession,
    settings: Settings,
    booking_id: int,
    back_callback: str,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Show one dedicated admin booking card."""
    panel = await build_booking_card_panel(
        db_session=db_session,
        settings=settings,
        booking_id=booking_id,
        back_callback=back_callback,
        notice_text=notice_text,
    )
    if panel is None:
        if edit:
            await replace_inline_message_text(target, texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT)
            return
        await target.answer(texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT)
        return
    text, markup = panel
    if edit:
        await replace_inline_message_text(target, text, reply_markup=markup)
        return
    await target.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("admin_booking_card:open:"))
async def open_booking_card(
    callback: CallbackQuery,
    state: FSMContext | None = None,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open a dedicated booking card from one admin list."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    if callback.message is None or callback.data is None:
        return
    try:
        try:
            await callback.answer()
        except Exception:
            # Toast acknowledgement is optional; don't block the whole card on it.
            pass
        parts = callback.data.split(":")
        booking_id = int(parts[2])
        back_callback = build_booking_card_return_callback(parts[3:])
        if state is not None:
            await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await show_booking_card(
            callback.message,
            db_session=db_session,
            settings=settings,
            booking_id=booking_id,
            back_callback=back_callback,
            edit=True,
        )
        if state is not None:
            await remember_admin_panel(state, callback.message)
    except Exception:
        logger.exception("Failed to open admin booking card: %s", callback.data)
        await replace_inline_message_text(
            callback.message,
            "Не смогла открыть карточку записи — попробуй ещё раз 🤍",
        )


@router.callback_query(F.data.startswith("admin_booking_card:message:"))
async def prompt_booking_card_message(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Prompt for one message from inside the booking card."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    booking_id, client_id, back_callback = parse_booking_action_parts(
        callback.data,
        has_client_id=True,
    )
    booking = await BookingRepository(db_session).get_by_id(booking_id)
    if booking is None or booking.client is None or client_id is None:
        await replace_inline_message_text(callback.message, texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT)
        return

    await state.set_state(AdminClientMessage.input_message)
    await state.update_data(
        admin_client_message_id=booking.client.id,
        admin_client_message_tg_id=booking.client.tg_id,
        admin_client_return_callback=back_callback,
        admin_client_return_view="main",
        admin_booking_card_id=booking.id,
        admin_booking_card_back_callback=back_callback,
    )
    await remember_admin_panel(state, callback.message)
    await replace_inline_message_text(
        callback.message,
        texts.ADMIN_CLIENT_MESSAGE_PROMPT_TEXT,
        reply_markup=build_booking_card_back_keyboard(
            booking_id=booking.id,
            back_callback=back_callback,
        ),
    )


@router.callback_query(F.data.startswith("admin_booking_card:reschedule:"))
async def prompt_booking_card_reschedule(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Prompt for a manual reschedule target from the booking card."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    booking_id, _, back_callback = parse_booking_action_parts(callback.data)
    booking = await BookingRepository(db_session).get_by_id(booking_id)
    if booking is None or booking.slot is None or booking.status != BookingStatus.CONFIRMED:
        await replace_inline_message_text(callback.message, texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT)
        return

    await state.set_state(AdminBookingCardReschedule.input_text)
    await state.update_data(
        admin_booking_card_reschedule_id=booking.id,
        admin_booking_card_reschedule_back_callback=back_callback,
    )
    await remember_admin_panel(state, callback.message)
    await replace_inline_message_text(
        callback.message,
        texts.ADMIN_BOOKING_CARD_RESCHEDULE_PROMPT_TEXT,
        reply_markup=build_booking_card_back_keyboard(
            booking_id=booking.id,
            back_callback=back_callback,
        ),
    )


@router.message(StateFilter(AdminBookingCardReschedule.input_text))
async def submit_booking_card_reschedule(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Apply one booking-card reschedule request from raw admin text."""
    data = await state.get_data()
    booking_id = int(data.get("admin_booking_card_reschedule_id", 0) or 0)
    back_callback = str(
        data.get("admin_booking_card_reschedule_back_callback") or "admin_menu:home"
    )
    if booking_id <= 0:
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await message.answer(texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT)
        return

    booking = await BookingRepository(db_session).get_by_id(booking_id)
    if booking is None or booking.client is None or booking.slot is None:
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await message.answer(texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT)
        return

    new_start_at, error_text = parse_one_reschedule_target(
        message.text or "",
        tz_name=settings.tz,
    )
    if error_text is not None or new_start_at is None:
        await send_admin_panel(
            message,
            state,
            text="\n\n".join(
                [
                    texts.ADMIN_BOOKING_CARD_RESCHEDULE_PROMPT_TEXT,
                    error_text or texts.GENERIC_ERROR_TEXT,
                ]
            ),
            reply_markup=build_booking_card_back_keyboard(
                booking_id=booking.id,
                back_callback=back_callback,
            ),
        )
        return

    slots = SlotRepository(db_session)
    slot, _ = await slots.create_if_missing(new_start_at)
    if slot.status != SlotStatus.FREE and slot.id != booking.slot_id:
        await db_session.rollback()
        await send_admin_panel(
            message,
            state,
            text="\n\n".join(
                [
                    texts.ADMIN_BOOKING_CARD_RESCHEDULE_PROMPT_TEXT,
                    texts.ADMIN_BOOKING_CARD_RESCHEDULE_COLLISION_TEXT,
                ]
            ),
            reply_markup=build_booking_card_back_keyboard(
                booking_id=booking.id,
                back_callback=back_callback,
            ),
        )
        return

    result = await reschedule_booking(
        db_session,
        booking=booking,
        new_slot_id=slot.id,
    )
    if not result.ok:
        notice = texts.ADMIN_BOOKING_CARD_RESCHEDULE_COLLISION_TEXT
        if result.reason == "same_slot":
            notice = "Это уже текущее время записи 🤍"
        elif result.reason == "slot_missing":
            notice = texts.ADMIN_BOOKING_CARD_RESCHEDULE_INVALID_TEXT
        await send_admin_panel(
            message,
            state,
            text="\n\n".join([texts.ADMIN_BOOKING_CARD_RESCHEDULE_PROMPT_TEXT, notice]),
            reply_markup=build_booking_card_back_keyboard(
                booking_id=booking.id,
                back_callback=back_callback,
            ),
        )
        return

    if booking.gcal_event_id:
        try:
            addons = await load_booking_addons(db_session, booking)
            update_booking_event(
                settings,
                event_id=booking.gcal_event_id,
                booking=build_calendar_booking_info_from_booking(booking, addons=addons),
            )
        except Exception:
            logger.exception("Failed to update calendar event for booking %s", booking.id)

    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await restore_booking_card_panel(
        message,
        state,
        db_session=db_session,
        settings=settings,
        booking_id=booking.id,
        back_callback=back_callback,
        notice_text=texts.ADMIN_BOOKING_CARD_RESCHEDULE_DONE_TEXT,
    )


@router.callback_query(F.data.startswith("admin_booking_card:cancel:"))
async def prompt_booking_card_cancel(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Ask for confirmation before cancelling a booking from its card."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    booking_id, _, back_callback = parse_booking_action_parts(callback.data)
    panel = await build_booking_card_panel(
        db_session=db_session,
        settings=settings,
        booking_id=booking_id,
        back_callback=back_callback,
    )
    if panel is None:
        await replace_inline_message_text(callback.message, texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT)
        return
    text, _ = panel
    await replace_inline_message_text(
        callback.message,
        f"❓ Отменить запись?\n\n{text}",
        reply_markup=build_booking_card_confirm_keyboard(
            action="cancel",
            booking_id=booking_id,
            back_callback=back_callback,
            confirm_label="❌ Да, отменить",
        ),
    )


@router.callback_query(F.data.startswith("admin_booking_card:cancel_confirm:"))
async def confirm_booking_card_cancel(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Cancel one booking from the admin booking card."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    booking_id, _, back_callback = parse_booking_action_parts(callback.data)
    booking = await BookingRepository(db_session).get_by_id(booking_id)
    if booking is None:
        await replace_inline_message_text(callback.message, texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT)
        return

    released_slot = await cancel_booking_by_master(db_session, booking=booking)
    if booking.gcal_event_id:
        try:
            delete_booking_event(settings, event_id=booking.gcal_event_id)
        except Exception:
            logger.exception("Failed to delete calendar event for booking %s", booking.id)

    await show_booking_card(
        callback.message,
        db_session=db_session,
        settings=settings,
        booking_id=booking.id,
        back_callback=back_callback,
        edit=True,
        notice_text=texts.ADMIN_BOOKING_CARD_CANCELLED_TEXT,
    )
    if released_slot is not None and slot_is_rescuable(released_slot):
        await send_rescue_slot_prompt_to_admins(
            callback.bot,
            db_session=db_session,
            settings=settings,
            slot_id=released_slot.id,
            exclude_user_id=booking.client_id,
            client_id=booking.client_id,
        )


@router.callback_query(F.data.startswith("admin_booking_card:no_show:"))
async def prompt_booking_card_no_show(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Ask for confirmation before marking a booking as no-show."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    booking_id, _, back_callback = parse_booking_action_parts(callback.data)
    panel = await build_booking_card_panel(
        db_session=db_session,
        settings=settings,
        booking_id=booking_id,
        back_callback=back_callback,
    )
    if panel is None:
        await replace_inline_message_text(callback.message, texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT)
        return
    text, _ = panel
    await replace_inline_message_text(
        callback.message,
        f"⚠️ Отметить no-show?\n\n{text}",
        reply_markup=build_booking_card_confirm_keyboard(
            action="no_show",
            booking_id=booking_id,
            back_callback=back_callback,
            confirm_label="⚠️ Да, отметить no-show",
        ),
    )


@router.callback_query(F.data.startswith("admin_booking_card:no_show_confirm:"))
async def confirm_booking_card_no_show(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Mark one booking as no-show from the dedicated booking card."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    booking_id, _, back_callback = parse_booking_action_parts(callback.data)
    booking = await BookingRepository(db_session).get_by_id(booking_id)
    if booking is None or booking.client is None:
        await replace_inline_message_text(callback.message, texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT)
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
        metadata={"booking_id": booking.id, "slot_id": booking.slot_id},
    )
    await db_session.commit()
    if callback.bot is not None:
        await refresh_live_morning_summary_for_today(
            callback.bot,
            db_session=db_session,
            settings=settings,
            now_utc=datetime.now(UTC),
        )

    await show_booking_card(
        callback.message,
        db_session=db_session,
        settings=settings,
        booking_id=booking.id,
        back_callback=back_callback,
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


@router.callback_query(F.data.startswith("admin_booking_card:repair:"))
async def show_booking_card_repair_info(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Show a compact repair/warranty info screen for one completed booking."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    booking_id, _, back_callback = parse_booking_action_parts(callback.data)
    booking = await BookingRepository(db_session).get_by_id(booking_id)
    if booking is None:
        await replace_inline_message_text(callback.message, texts.ADMIN_ALL_BOOKINGS_NOT_FOUND_TEXT)
        return

    settings_repository = SettingRepository(db_session)
    warranty_days = await get_int_setting(
        settings_repository,
        key="repair_warranty_days",
        default=14,
    )
    warranty_nails_limit = await get_int_setting(
        settings_repository,
        key="repair_warranty_nails_limit",
        default=2,
    )
    request_window_days = await get_int_setting(
        settings_repository,
        key="repair_request_window_days",
        default=30,
    )
    await replace_inline_message_text(
        callback.message,
        texts.ADMIN_BOOKING_CARD_REPAIR_INFO_TEXT.format(
            days=warranty_days,
            nails=warranty_nails_limit,
            request_days=request_window_days,
        ),
        reply_markup=build_booking_card_back_keyboard(
            booking_id=booking.id,
            back_callback=back_callback,
        ),
    )
