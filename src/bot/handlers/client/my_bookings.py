from __future__ import annotations

import logging
from datetime import date

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.fsm_utils import clear_state_preserving_admin_mode
from src.bot.keyboards.client import (
    build_back_to_booking_keyboard,
    build_booking_action_result_keyboard,
    build_booking_card_keyboard,
    build_cancel_pre_confirm_keyboard,
    build_cancel_reason_keyboard,
    build_cancel_warning_keyboard,
    build_my_bookings_empty_keyboard,
    build_my_bookings_history_keyboard,
    build_my_bookings_overview_keyboard,
    build_reschedule_days_keyboard,
    build_reschedule_schedule_days_keyboard,
    build_reschedule_times_keyboard,
)
from src.bot.keyboards.admin import build_admin_rescue_slot_keyboard, build_open_client_card_keyboard
from src.bot.slot_picker import (
    order_day_options_by_preference,
    order_slots_by_time_preference,
    render_day_picker,
    render_time_picker,
)
from src.bot.states import AwaitCustomTime
from src.bot.states import MyBookings as MyBookingsStates
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.models import Booking, BookingStatus, Service, User
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.services import ServiceRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.slots import PUBLIC_BOOKING_HORIZON_DAYS, SlotRepository
from src.services.aftercare import can_report_late_arrival, can_request_repair, days_since_booking
from src.services.anti_abuse import (
    attempt_reschedule_with_anti_abuse,
    get_anti_abuse_settings,
    hours_before_booking,
    record_rate_event,
)
from src.services.booking import (
    build_admin_cancellation_text,
    build_admin_reschedule_text,
    build_booking_list_item_label,
    build_booking_service_label,
    build_client_booking_card_text,
    build_my_bookings_list_text,
    build_my_bookings_overview_text,
    can_cancel_booking,
    can_reschedule_booking,
    cancel_booking,
    format_local_datetime,
    group_slots_by_local_day,
    needs_late_cancellation_notice,
)
from src.services.button_configs import ClientMenuButtonConfig, load_all_button_configs
from src.services.calendar_sync import (
    CalendarBookingInfo,
    CalendarClientInfo,
    delete_booking_event,
    update_booking_event,
)
from src.services.notifications import send_text_to_admins
from src.services.rescue_slots import slot_is_rescuable
from src.services.runtime_settings import get_int_setting

router = Router(name="client_my_bookings")

logger = logging.getLogger(__name__)

RESCHEDULE_SCHEDULE_PAGE_STATE_KEY = "slot_picker_reschedule_page"


async def load_runtime_button_configs(
    db_session: AsyncSession,
) -> dict[str, ClientMenuButtonConfig]:
    """Load editable runtime button configs for the `Мои записи` surfaces."""
    return await load_all_button_configs(SettingRepository(db_session))


async def load_booking_and_addons(
    db_session: AsyncSession,
    *,
    client_id: int,
    booking_id: int,
) -> tuple[Booking | None, list[Service]]:
    """Load a client booking together with add-on services."""
    booking_repository = BookingRepository(db_session)
    service_repository = ServiceRepository(db_session)

    booking = await booking_repository.get_client_booking(booking_id, client_id)
    if booking is None:
        return None, []

    addons = await service_repository.list_by_ids(list(booking.addons))
    return booking, addons


async def show_bookings_list_message(
    message: Message,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    edit: bool,
    prefix_text: str | None = None,
) -> None:
    """Render the warm summary-first `Мои записи` overview."""
    repository = BookingRepository(db_session)
    button_configs = await load_runtime_button_configs(db_session)
    active_bookings = await repository.list_active_for_client(user.id)
    completed_bookings = await repository.list_recent_completed_for_client(user.id, limit=10)
    completed_visits = await repository.count_completed_for_client(user.id)
    last_completed_at = await repository.get_last_completed_slot_at(user.id)

    if not active_bookings and not completed_bookings:
        text = texts.NO_BOOKINGS_YET_TEXT
        if prefix_text:
            text = f"{prefix_text}\n\n{text}"
        reply_markup = build_my_bookings_empty_keyboard(button_configs=button_configs)
    else:
        service_repository = ServiceRepository(db_session)
        summary_bookings = active_bookings[:2]
        service_labels: dict[int, str] = {}
        for booking in summary_bookings:
            addons = await service_repository.list_by_ids(list(booking.addons))
            service_labels[booking.id] = build_booking_service_label(booking.base_service, addons)
        text = build_my_bookings_overview_text(
            user=user,
            active_bookings=active_bookings,
            service_labels=service_labels,
            completed_visits=completed_visits,
            last_completed_at=last_completed_at,
            tz_name=settings.tz,
            address_text=None,
        )
        if prefix_text:
            text = f"{prefix_text}\n\n{text}"
        reply_markup = build_my_bookings_overview_keyboard(
            nearest_booking_id=active_bookings[0].id if active_bookings else None,
            next_booking_id=active_bookings[1].id if len(active_bookings) > 1 else None,
            repeat_booking_id=completed_bookings[0].id if completed_bookings else None,
            history_count=completed_visits,
            has_active_bookings=bool(active_bookings),
            button_configs=button_configs,
        )

    if edit:
        await replace_inline_message_text(message, text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


async def show_bookings_history_message(
    message: Message,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    edit: bool,
    prefix_text: str | None = None,
) -> None:
    """Render the detailed history/list view for `Мои записи`."""
    repository = BookingRepository(db_session)
    button_configs = await load_runtime_button_configs(db_session)
    active_bookings = await repository.list_active_for_client(user.id)
    completed_bookings = await repository.list_recent_completed_for_client(user.id, limit=10)

    if not active_bookings and not completed_bookings:
        await show_bookings_list_message(
            message,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=edit,
            prefix_text=prefix_text,
        )
        return

    text = build_my_bookings_list_text(
        active_bookings=active_bookings,
        completed_bookings=completed_bookings,
        tz_name=settings.tz,
    )
    if prefix_text:
        text = f"{prefix_text}\n\n{text}"
    items = [
        (booking.id, build_booking_list_item_label(booking, tz_name=settings.tz))
        for booking in [*active_bookings, *completed_bookings]
    ]
    reply_markup = build_my_bookings_history_keyboard(items, button_configs=button_configs)
    if edit:
        await replace_inline_message_text(message, text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


async def show_booking_card_message(
    message: Message,
    *,
    booking_id: int,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    edit: bool,
    prefix_text: str | None = None,
) -> None:
    """Render one booking card."""
    button_configs = await load_runtime_button_configs(db_session)
    booking, addons = await load_booking_and_addons(
        db_session,
        client_id=user.id,
        booking_id=booking_id,
    )
    if booking is None:
        await show_bookings_list_message(
            message,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=edit,
            prefix_text=texts.MY_BOOKINGS_CARD_MISSING_TEXT,
        )
        return

    text = build_client_booking_card_text(
        booking=booking,
        addons=addons,
        tz_name=settings.tz,
    )
    repair_settings_repository = SettingRepository(db_session)
    repair_request_window_days = await get_int_setting(
        repair_settings_repository,
        key="repair_request_window_days",
        default=30,
    )
    repair_warranty_days = await get_int_setting(
        repair_settings_repository,
        key="repair_warranty_days",
        default=14,
    )
    if booking.status == BookingStatus.COMPLETED:
        days_since = days_since_booking(booking)
        if days_since is not None and days_since <= repair_warranty_days:
            remaining_days = max(repair_warranty_days - days_since, 0)
            text = (
                f"🛠 Гарантия ещё {remaining_days} дн. "
                "Если что-то случилось, можно сразу открыть заявку ниже 🌸\n\n"
                f"{text}"
            )
    if prefix_text:
        text = f"{prefix_text}\n\n{text}"

    reply_markup = build_booking_card_keyboard(
        booking.id,
        can_reschedule=can_reschedule_booking(booking),
        can_cancel=can_cancel_booking(booking),
        cancel_label=(
            "❌ Отменить запрос"
            if booking.status == BookingStatus.PENDING_MASTER
            else "❌ Отменить"
        ),
        show_late_button=can_report_late_arrival(booking),
        show_repair_button=can_request_repair(
            booking,
            request_window_days=repair_request_window_days,
        ),
        button_configs=button_configs,
    )

    if edit:
        await replace_inline_message_text(message, text, reply_markup=reply_markup)
        return

    await message.answer(text, reply_markup=reply_markup)


async def show_reschedule_days_message(
    message: Message,
    *,
    booking_id: int,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    state: FSMContext | None = None,
    prefix_text: str | None = None,
    image_page: int | None = None,
    focus_day: date | None = None,
) -> None:
    """Render the day picker for rescheduling."""
    button_configs = await load_runtime_button_configs(db_session)
    booking, _ = await load_booking_and_addons(
        db_session,
        client_id=user.id,
        booking_id=booking_id,
    )
    if booking is None:
        await show_bookings_list_message(
            message,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.MY_BOOKINGS_CARD_MISSING_TEXT,
        )
        return

    if not can_reschedule_booking(booking):
        await show_booking_card_message(
            message,
            booking_id=booking.id,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    slot_repository = SlotRepository(db_session)
    slots = await slot_repository.list_free_future(horizon_days=PUBLIC_BOOKING_HORIZON_DAYS)
    day_options = order_day_options_by_preference(
        group_slots_by_local_day(slots, settings.tz),
        user.preferred_days_note,
    )

    text = texts.MY_BOOKINGS_RESCHEDULE_DAY_TEXT
    if prefix_text:
        text = f"{prefix_text}\n\n{text}"
    no_slots_text = texts.MY_BOOKINGS_RESCHEDULE_NO_SLOTS_TEXT
    if prefix_text:
        no_slots_text = f"{prefix_text}\n\n{no_slots_text}"
    await render_day_picker(
        message,
        db_session=db_session,
        settings=settings,
        slots=slots,
        day_options=day_options,
        prompt_text=text,
        no_slots_text=no_slots_text,
        replace=True,
        no_slots_reply_markup=build_back_to_booking_keyboard(
            booking.id,
            button_configs=button_configs,
        ),
        text_reply_markup_builder=(
            lambda current_day_options: build_reschedule_days_keyboard(
                booking.id,
                current_day_options,
                button_configs=button_configs,
            )
        ),
        image_reply_markup_builder=(
            lambda current_day_options, current_page, total_pages: (
                build_reschedule_schedule_days_keyboard(
                    booking.id,
                    current_day_options,
                    current_page=current_page,
                    total_pages=total_pages,
                    button_configs=button_configs,
                )
            )
        ),
        schedule_caption_text=texts.BOOKING_SCHEDULE_IMAGE_CAPTION_TEXT,
        state=state,
        page_state_key=RESCHEDULE_SCHEDULE_PAGE_STATE_KEY,
        image_page=image_page,
        focus_day=focus_day,
    )
    if state is not None:
        state_data = await state.get_data()
        stored_page = state_data.get(RESCHEDULE_SCHEDULE_PAGE_STATE_KEY)
        if stored_page is not None:
            await state.update_data(reschedule_schedule_page=stored_page)


async def show_reschedule_times_message(
    message: Message,
    *,
    booking_id: int,
    local_day: date,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    state: FSMContext | None = None,
    prefix_text: str | None = None,
) -> None:
    """Render the time picker for rescheduling."""
    button_configs = await load_runtime_button_configs(db_session)
    booking, _ = await load_booking_and_addons(
        db_session,
        client_id=user.id,
        booking_id=booking_id,
    )
    if booking is None:
        await show_bookings_list_message(
            message,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.MY_BOOKINGS_CARD_MISSING_TEXT,
        )
        return

    if not can_reschedule_booking(booking):
        await show_booking_card_message(
            message,
            booking_id=booking.id,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    slot_repository = SlotRepository(db_session)
    slots = await slot_repository.list_free_for_local_day(local_day=local_day, tz_name=settings.tz)
    slots = order_slots_by_time_preference(
        slots,
        user.preferred_time_note,
        tz_name=settings.tz,
    )

    if not slots:
        await show_reschedule_days_message(
            message,
            booking_id=booking.id,
            db_session=db_session,
            user=user,
            settings=settings,
            state=state,
            prefix_text=texts.BOOKING_CONFIRM_SLOT_TAKEN_TEXT,
            focus_day=local_day,
        )
        return

    text = texts.MY_BOOKINGS_RESCHEDULE_TIME_TEXT
    if prefix_text:
        text = f"{prefix_text}\n\n{text}"
    await render_time_picker(
        message,
        prompt_text=text,
        replace=True,
        reply_markup=build_reschedule_times_keyboard(
            booking.id,
            slots,
            settings.tz,
            local_day=local_day,
            button_configs=button_configs,
        ),
    )


def build_calendar_booking_info(
    *,
    booking: Booking,
    addons: list[Service],
    user: User,
) -> CalendarBookingInfo:
    """Build the calendar payload for an updated booking."""
    if booking.slot is None:
        raise ValueError("Booking slot is required for calendar sync")

    return CalendarBookingInfo(
        booking_id=booking.id,
        start_at=booking.slot.start_at,
        duration_min=booking.base_service.duration_min
        + sum(addon.duration_min for addon in addons),
        base_service_name=booking.base_service.name,
        addon_names=[addon.name for addon in addons],
        client=CalendarClientInfo(
            display_name=user.display_name,
            tg_id=user.tg_id,
            tg_username=user.tg_username,
            phone=user.phone,
            note=user.note,
        ),
        design_comment=booking.design_comment,
    )


async def finish_cancellation(
    *,
    message: Message,
    state: FSMContext,
    booking_id: int,
    reason_code: str,
    reason_text: str | None,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    edit: bool,
    bot,
) -> None:
    """Cancel the booking, sync calendars, and notify admins."""
    anti_abuse_settings = await get_anti_abuse_settings(db_session)
    button_configs = await load_runtime_button_configs(db_session)
    booking, addons = await load_booking_and_addons(
        db_session,
        client_id=user.id,
        booking_id=booking_id,
    )
    if booking is None or not can_cancel_booking(booking):
        await clear_state_preserving_admin_mode(state)
        if edit:
            await show_bookings_list_message(
                message,
                db_session=db_session,
                user=user,
                settings=settings,
                edit=True,
                prefix_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
            )
            return

        await message.answer(
            texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
            reply_markup=build_booking_action_result_keyboard(
                button_configs=button_configs
            ),
        )
        return

    show_late_notice = needs_late_cancellation_notice(booking)
    hours_before = hours_before_booking(booking)
    event_id = booking.gcal_event_id
    released_slot = await cancel_booking(
        db_session,
        booking=booking,
        reason_code=reason_code,
        reason_text=reason_text,
    )

    if event_id:
        try:
            delete_booking_event(settings, event_id=event_id)
            booking.gcal_event_id = None
            await db_session.commit()
        except Exception:
            logger.exception("Failed to delete Google Calendar event for booking %s", booking.id)

    await record_rate_event(
        db_session,
        user_id=user.id,
        kind="cancel",
        metadata={"hours_before": hours_before},
    )
    if hours_before is not None and hours_before < anti_abuse_settings["late_cancel_hours"]:
        user.strikes += 1
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="late_cancel",
            metadata={"booking_id": booking.id, "hours_before": hours_before},
        )
        if user.strikes >= anti_abuse_settings["late_cancel_strike_limit"]:
            user.requires_manual_approval = True
    await db_session.commit()

    admin_text = build_admin_cancellation_text(
        booking=booking,
        client=user,
        addons=addons,
        tz_name=settings.tz,
    )
    admin_reply_markup = build_open_client_card_keyboard(user.id)
    if released_slot is not None and show_late_notice and slot_is_rescuable(released_slot):
        admin_reply_markup = build_admin_rescue_slot_keyboard(
            released_slot.id,
            exclude_user_id=user.id,
            user_id=user.id,
        )
    await send_text_to_admins(
        bot,
        admin_tg_ids=settings.admin_tg_id_set,
        text=admin_text,
        reply_markup=admin_reply_markup,
    )

    await clear_state_preserving_admin_mode(state)
    success_text = (
        texts.MY_BOOKINGS_CANCEL_LT24H_TEXT
        if show_late_notice
        else texts.MY_BOOKINGS_CANCEL_DONE_TEXT
    )
    if edit:
        await replace_inline_message_text(
            message,
            success_text,
            reply_markup=build_booking_action_result_keyboard(
                button_configs=button_configs
            ),
        )
        return

    await message.answer(
        success_text,
        reply_markup=build_booking_action_result_keyboard(
            button_configs=button_configs
        ),
    )


async def show_my_bookings_entry(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    replace_current: bool = False,
) -> None:
    """Enter the `Мои записи` section from a callback or a bot command."""
    await clear_state_preserving_admin_mode(state)
    await show_bookings_list_message(
        message,
        db_session=db_session,
        user=user,
        settings=settings,
        edit=replace_current,
    )


@router.callback_query(F.data == "client_menu:my_bookings")
async def show_my_bookings(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Open the `Мои записи` overview from the main menu."""
    await callback.answer()
    if callback.message is None:
        return

    await show_my_bookings_entry(
        callback.message,
        state,
        db_session=db_session,
        user=user,
        settings=settings,
        replace_current=True,
    )


@router.callback_query(F.data == "my_bookings:overview")
@router.callback_query(F.data == "my_bookings:list")
async def show_my_bookings_again(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Return to the canonical `Мои записи` overview via internal aliases."""
    await callback.answer()
    if callback.message is None:
        return

    await show_my_bookings_entry(
        callback.message,
        state,
        db_session=db_session,
        user=user,
        settings=settings,
        replace_current=True,
    )


@router.callback_query(F.data == "my_bookings:history")
async def show_my_bookings_history(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Open the detailed list/history view from the summary screen."""
    await callback.answer()
    if callback.message is None:
        return

    await clear_state_preserving_admin_mode(state)
    await show_bookings_history_message(
        callback.message,
        db_session=db_session,
        user=user,
        settings=settings,
        edit=True,
    )


@router.callback_query(F.data.startswith("my_bookings:open:"))
async def open_booking_card(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Open a specific booking card."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    await clear_state_preserving_admin_mode(state)
    booking_id = int(callback.data.rsplit(":", 1)[1])
    await show_booking_card_message(
        callback.message,
        booking_id=booking_id,
        db_session=db_session,
        user=user,
        settings=settings,
        edit=True,
    )


@router.callback_query(F.data.startswith("my_bookings:reschedule:"))
async def start_reschedule(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Open the reschedule day picker."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    await clear_state_preserving_admin_mode(state)
    booking_id = int(callback.data.rsplit(":", 1)[1])
    await show_reschedule_days_message(
        callback.message,
        booking_id=booking_id,
        db_session=db_session,
        user=user,
        settings=settings,
        state=state,
    )


@router.callback_query(F.data.startswith("my_bookings:reschedule_day:"))
async def choose_reschedule_day(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Open available times for the selected reschedule day."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    _, _, booking_id_str, local_day_str = callback.data.split(":", 3)
    await show_reschedule_times_message(
        callback.message,
        booking_id=int(booking_id_str),
        local_day=date.fromisoformat(local_day_str),
        db_session=db_session,
        user=user,
        settings=settings,
        state=state,
    )


@router.callback_query(F.data.startswith("my_bookings:reschedule_slot:"))
async def choose_reschedule_slot(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Move the booking to the chosen free slot."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    _, _, booking_id_str, slot_id_str = callback.data.split(":", 3)
    booking_id = int(booking_id_str)
    slot_id = int(slot_id_str)

    booking, addons = await load_booking_and_addons(
        db_session,
        client_id=user.id,
        booking_id=booking_id,
    )
    if booking is None or not can_reschedule_booking(booking):
        await show_bookings_list_message(
            callback.message,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    attempt = await attempt_reschedule_with_anti_abuse(
        db_session,
        user=user,
        booking=booking,
        new_slot_id=slot_id,
        tz_name=settings.tz,
    )
    if attempt.outcome == "shadow_banned":
        await show_booking_card_message(
            callback.message,
            booking_id=booking_id,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.MY_BOOKINGS_RESCHEDULED_TEXT,
        )
        return

    if attempt.approval is not None:
        from src.bot.handlers.admin.approvals import send_approval_card_to_admins

        if attempt.outcome != "approval_existing":
            await send_approval_card_to_admins(
                bot=callback.bot,
                settings=settings,
                db_session=db_session,
                approval=attempt.approval,
            )
        await show_booking_card_message(
            callback.message,
            booking_id=booking_id,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.APPROVAL_RESCHEDULE_SENT_TEXT,
        )
        return

    result = attempt.reschedule_result
    if result is None:
        await show_booking_card_message(
            callback.message,
            booking_id=booking_id,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    if not result.ok:
        if result.reason == "slot_unavailable" and result.new_slot is not None:
            await show_reschedule_times_message(
                callback.message,
                booking_id=booking_id,
                local_day=format_local_datetime(result.new_slot.start_at, settings.tz).date(),
                db_session=db_session,
                user=user,
                settings=settings,
                state=state,
                prefix_text=texts.BOOKING_CONFIRM_SLOT_TAKEN_TEXT,
            )
            return

        await show_booking_card_message(
            callback.message,
            booking_id=booking_id,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    if booking.gcal_event_id and booking.slot is not None:
        try:
            update_booking_event(
                settings,
                event_id=booking.gcal_event_id,
                booking=build_calendar_booking_info(
                    booking=booking,
                    addons=addons,
                    user=user,
                ),
            )
        except Exception:
            logger.exception("Failed to update Google Calendar event for booking %s", booking.id)

    try:
        await send_text_to_admins(
            callback.bot,
            admin_tg_ids=settings.admin_tg_id_set,
            text=build_admin_reschedule_text(
                booking=booking,
                client=user,
                addons=addons,
                old_slot=result.old_slot,
                new_slot=result.new_slot,
                tz_name=settings.tz,
            ),
            reply_markup=build_open_client_card_keyboard(user.id),
        )
    except Exception:
        logger.exception("Failed to notify admins about client reschedule for booking %s", booking.id)

    await show_booking_card_message(
        callback.message,
        booking_id=booking_id,
        db_session=db_session,
        user=user,
        settings=settings,
        edit=True,
        prefix_text=texts.MY_BOOKINGS_RESCHEDULED_TEXT,
    )


@router.callback_query(F.data.startswith("my_bookings:reschedule_page:"))
async def change_reschedule_schedule_page(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Flip one page inside the reschedule day viewer."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    _, _, booking_id_str, page_str = callback.data.split(":", 3)
    await show_reschedule_days_message(
        callback.message,
        booking_id=int(booking_id_str),
        db_session=db_session,
        user=user,
        settings=settings,
        state=state,
        image_page=int(page_str),
    )


@router.callback_query(F.data == "my_bookings:reschedule_noop")
async def reschedule_schedule_noop(callback: CallbackQuery) -> None:
    """Acknowledge the inert page number button in the reschedule viewer."""
    await callback.answer()


@router.callback_query(F.data.startswith("my_bookings:reschedule_days_back:"))
async def back_to_reschedule_days(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Return from reschedule time selection to the last day page."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    booking_id = int(callback.data.rsplit(":", 1)[1])
    await show_reschedule_days_message(
        callback.message,
        booking_id=booking_id,
        db_session=db_session,
        user=user,
        settings=settings,
        state=state,
    )


@router.callback_query(F.data.startswith("my_bookings:reschedule_other_day:"))
async def request_reschedule_other_day(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Switch a reschedule into the custom-date request flow."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    button_configs = await load_runtime_button_configs(db_session)
    booking_id = int(callback.data.rsplit(":", 1)[1])
    await state.set_state(AwaitCustomTime.input_text)
    await state.update_data(
        custom_request_kind="reschedule",
        custom_request_preferred_day=None,
        related_booking_id=booking_id,
    )
    await replace_inline_message_text(
        callback.message,
        texts.BOOKING_CUSTOM_TIME_RESCHEDULE_PROMPT_TEXT,
        reply_markup=build_back_to_booking_keyboard(
            booking_id,
            button_configs=button_configs,
        ),
    )


@router.callback_query(F.data.startswith("my_bookings:reschedule_other_time:"))
async def request_reschedule_other_time(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Switch a reschedule into the custom-time request flow for the selected day."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    button_configs = await load_runtime_button_configs(db_session)
    _, _, booking_id_str, local_day_str = callback.data.split(":", 3)
    await state.set_state(AwaitCustomTime.input_text)
    await state.update_data(
        custom_request_kind="reschedule",
        custom_request_preferred_day=local_day_str,
        related_booking_id=int(booking_id_str),
    )
    await replace_inline_message_text(
        callback.message,
        texts.BOOKING_CUSTOM_TIME_RESCHEDULE_PROMPT_TEXT,
        reply_markup=build_back_to_booking_keyboard(
            int(booking_id_str),
            button_configs=button_configs,
        ),
    )


@router.callback_query(F.data.startswith("my_bookings:cancel:"))
async def start_cancellation(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Open the cancellation reason picker."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    await clear_state_preserving_admin_mode(state)
    button_configs = await load_runtime_button_configs(db_session)
    booking_id = int(callback.data.rsplit(":", 1)[1])
    booking, _ = await load_booking_and_addons(
        db_session,
        client_id=user.id,
        booking_id=booking_id,
    )
    if booking is None or not can_cancel_booking(booking):
        await show_booking_card_message(
            callback.message,
            booking_id=booking_id,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    anti_abuse_settings = await get_anti_abuse_settings(db_session)
    hours_before = hours_before_booking(booking)
    if (
        booking.status == BookingStatus.CONFIRMED
        and hours_before is not None
        and hours_before < anti_abuse_settings["late_cancel_hours"]
    ):
        await replace_inline_message_text(
            callback.message,
            texts.MY_BOOKINGS_CANCEL_WARNING_TEXT.format(
                hours=anti_abuse_settings["late_cancel_hours"]
            ),
            reply_markup=build_cancel_warning_keyboard(
                booking_id,
                button_configs=button_configs,
            ),
        )
        return

    await replace_inline_message_text(
        callback.message,
        texts.MY_BOOKINGS_CANCEL_PRE_CONFIRM_TEXT,
        reply_markup=build_cancel_pre_confirm_keyboard(
            booking_id,
            button_configs=button_configs,
        ),
    )


@router.callback_query(F.data.startswith("my_bookings:cancel_pre_confirm:"))
async def show_cancellation_reason_picker(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
) -> None:
    """Move from the pre-confirm screen to the reason picker."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    button_configs = await load_runtime_button_configs(db_session)
    booking_id = int(callback.data.rsplit(":", 1)[1])
    await replace_inline_message_text(
        callback.message,
        texts.MY_BOOKINGS_CANCEL_REASON_TEXT,
        reply_markup=build_cancel_reason_keyboard(
            booking_id,
            button_configs=button_configs,
        ),
    )


@router.callback_query(F.data.startswith("my_bookings:cancel_confirm:"))
async def confirm_cancellation_prompt(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
) -> None:
    """Move from the late-cancel warning to the reason picker."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    button_configs = await load_runtime_button_configs(db_session)
    booking_id = int(callback.data.rsplit(":", 1)[1])
    await replace_inline_message_text(
        callback.message,
        texts.MY_BOOKINGS_CANCEL_REASON_TEXT,
        reply_markup=build_cancel_reason_keyboard(
            booking_id,
            button_configs=button_configs,
        ),
    )


@router.callback_query(F.data.startswith("my_bookings:cancel_reason:"))
async def select_cancellation_reason(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Handle a predefined cancellation reason."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    button_configs = await load_runtime_button_configs(db_session)
    _, _, booking_id_str, reason_code = callback.data.split(":", 3)
    booking_id = int(booking_id_str)
    if reason_code == "other":
        await state.set_state(MyBookingsStates.input_cancel_other_reason)
        await state.update_data(cancel_booking_id=booking_id)
        await replace_inline_message_text(
            callback.message,
            texts.MY_BOOKINGS_CANCEL_OTHER_REASON_TEXT,
            reply_markup=build_back_to_booking_keyboard(
                booking_id,
                button_configs=button_configs,
            ),
        )
        return

    await finish_cancellation(
        message=callback.message,
        state=state,
        booking_id=booking_id,
        reason_code=reason_code,
        reason_text=None,
        db_session=db_session,
        user=user,
        settings=settings,
        edit=True,
        bot=callback.bot,
    )


@router.message(StateFilter(MyBookingsStates.input_cancel_other_reason))
async def input_cancellation_other_reason(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Handle the free-text cancellation reason."""
    reason_text = (message.text or "").strip()
    if not reason_text:
        await message.answer(texts.MY_BOOKINGS_CANCEL_OTHER_REASON_INVALID_TEXT)
        return

    data = await state.get_data()
    booking_id = data.get("cancel_booking_id")
    if booking_id is None:
        await clear_state_preserving_admin_mode(state)
        button_configs = await load_runtime_button_configs(db_session)
        await message.answer(
            texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
            reply_markup=build_booking_action_result_keyboard(
                button_configs=button_configs
            ),
        )
        return

    await finish_cancellation(
        message=message,
        state=state,
        booking_id=int(booking_id),
        reason_code="other",
        reason_text=reason_text,
        db_session=db_session,
        user=user,
        settings=settings,
        edit=False,
        bot=message.bot,
    )
