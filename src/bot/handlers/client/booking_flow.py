from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.enums import ParseMode
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message, ReplyKeyboardRemove
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.fsm_utils import clear_state_preserving_admin_mode
from src.bot.handlers.admin.approvals import send_approval_card_to_admins
from src.bot.handlers.client.address import (
    build_address_copy_text,
    build_address_map_url,
    build_address_text,
)
from src.bot.handlers.client.booking_confirmation import send_booking_confirmation_message
from src.bot.handlers.client.brand import send_brand_message, send_template_message
from src.bot.handlers.client.menu import show_client_menu
from src.bot.handlers.client.my_bookings import show_my_bookings_entry
from src.bot.keyboards.admin import build_open_client_card_keyboard
from src.bot.keyboards.client import (
    PHONE_MANUAL_BUTTON_TEXT,
    build_addons_keyboard,
    build_back_to_menu_keyboard,
    build_base_services_keyboard,
    build_booking_action_result_keyboard,
    build_confirm_keyboard,
    build_contact_request_keyboard,
    build_days_keyboard,
    build_name_confirmation_keyboard,
    build_no_slots_keyboard,
    build_payment_method_keyboard,
    build_post_booking_cta_keyboard,
    build_reference_actions_keyboard,
    build_reference_prompt_keyboard,
    build_schedule_days_keyboard,
    build_times_keyboard,
)
from src.bot.states import AwaitCustomTime, Onboarding, PostBookingReference
from src.bot.states import Booking as BookingStates
from src.bot.ui_utils import (
    replace_inline_message_panel,
    replace_inline_message_text,
    safe_delete_message,
)
from src.bot.slot_picker import (
    order_day_options_by_preference as shared_order_day_options_by_preference,
    order_slots_by_time_preference as shared_order_slots_by_time_preference,
    render_day_picker,
    render_time_picker,
)
from src.config import Settings
from src.db.models import ApprovalRequestKind, ServiceKind, User, utcnow
from src.db.repositories.approvals import ApprovalRequestRepository
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.rate_limit_events import RateLimitEventRepository
from src.db.repositories.services import ServiceRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.slots import PUBLIC_BOOKING_HORIZON_DAYS, SlotRepository
from src.db.repositories.templates import TemplateRepository
from src.db.repositories.users import UserRepository
from src.services.admin_defaults import required_template_defaults
from src.services.anti_abuse import (
    get_anti_abuse_settings,
    record_rate_event,
    remaining_cooldown_minutes,
    resolve_cancel_cooldown,
)
from src.services.booking import (
    PAYMENT_METHOD_CASH,
    PAYMENT_METHOD_TRANSFER,
    build_addons_prompt_text,
    build_admin_booking_text,
    build_booking_summary_text,
    build_reference_progress_text,
    format_local_datetime,
    format_local_day_label,
    format_payment_method_label,
    group_slots_by_local_day,
    needs_onboarding,
    normalize_payment_method,
    normalize_phone,
    remember_client_preference_hints,
    should_confirm_name,
)
from src.services.booking_completion import BookingClientConfirmationPayload
from src.services.button_configs import (
    ClientMenuButtonConfig,
    load_all_button_configs,
    load_master_contact_url,
)
from src.services.notifications import (
    send_photo_to_admins,
    send_text_to_admins,
    send_voice_to_admins,
)
from src.services.direct_booking import finalize_direct_booking_attempt
from src.services.rescue_slots import slot_is_rescuable
from src.services.runtime_settings import get_bool_setting
from src.services.schedule_image import (
    build_schedule_image_pages_data,
    is_schedule_image_enabled,
    render_schedule_image_bytes,
)
from src.services.template_media import has_template_media
from src.services.template_texts import render_template_text

router = Router(name="client_booking_flow")

logger = logging.getLogger(__name__)

BOOKING_SCHEDULE_PAGE_STATE_KEY = "slot_picker_booking_page"
CUSTOM_TIME_BACK_TARGET_DAY = "day"
CUSTOM_TIME_BACK_TARGET_TIME = "time"

async def send_phone_prompt(message: Message) -> None:
    """Prompt the client to share or type a phone number."""
    await message.answer(
        texts.ONBOARDING_PHONE_TEXT,
        reply_markup=build_contact_request_keyboard(),
    )


def custom_time_prompt_text(request_kind: ApprovalRequestKind) -> str:
    """Return a contextual custom-time prompt."""
    if request_kind == ApprovalRequestKind.RESCHEDULE:
        return texts.BOOKING_CUSTOM_TIME_RESCHEDULE_PROMPT_TEXT
    return texts.BOOKING_CUSTOM_TIME_NEW_BOOKING_PROMPT_TEXT


def approval_sent_text(request_kind: ApprovalRequestKind) -> str:
    """Return a contextual success text for approval-like pending states."""
    if request_kind == ApprovalRequestKind.RESCHEDULE:
        return texts.APPROVAL_RESCHEDULE_SENT_TEXT
    if request_kind in (
        ApprovalRequestKind.NEW_BOOKING,
        ApprovalRequestKind.FREQUENT_BOOKING,
        ApprovalRequestKind.LATE_RESCHEDULE,
        ApprovalRequestKind.MANUAL_APPROVAL_REQUIRED,
    ):
        return texts.APPROVAL_NEW_BOOKING_SENT_TEXT
    return texts.APPROVAL_CUSTOM_TIME_SENT_TEXT


def order_day_options_by_preference(day_options: list, preferred_days_note: str | None) -> list:
    """Move days matching the client's saved preference to the top."""
    return shared_order_day_options_by_preference(day_options, preferred_days_note)


def order_slots_by_time_preference(
    slots: list[object],
    preferred_time_note: str | None,
    *,
    tz_name: str,
) -> list[object]:
    """Prioritize slots that better match the client's saved time preference."""
    return shared_order_slots_by_time_preference(slots, preferred_time_note, tz_name=tz_name)


async def continue_after_onboarding(
    message: Message,
    *,
    db_session: AsyncSession,
    state: FSMContext,
    settings: Settings,
    user: User,
) -> None:
    """Resume the appropriate flow after onboarding fields are collected."""
    state_data = await state.get_data()
    if state_data.get("onboarding_resume_target") == "confirm":
        await state.update_data(onboarding_resume_target=None)
        await show_confirm_step(
            message,
            db_session=db_session,
            state=state,
            settings=settings,
            user=user,
        )
        return
    if state_data.get("locked_slot_offer"):
        await show_base_service_step(message, db_session=db_session, state=state)
        return
    if state_data.get("repeat_source_booking_id") is not None:
        await show_day_step(
            message,
            db_session=db_session,
            state=state,
            settings=settings,
        )
        return
    if state_data.get("browse_mode"):
        await show_day_step(
            message,
            db_session=db_session,
            state=state,
            settings=settings,
        )
        return
    await show_base_service_step(message, db_session=db_session, state=state)


async def start_repeat_booking_entry(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    source_booking_id: int | None = None,
    first_name: str | None = None,
    replace_current: bool = False,
) -> None:
    """Start a faster repeat-booking flow with prefilled service data."""
    repository = BookingRepository(db_session)
    source_booking = (
        await repository.get_completed_booking_for_client(source_booking_id, user.id)
        if source_booking_id is not None
        else await repository.get_latest_completed_for_client(user.id)
    )
    if source_booking is None or source_booking.base_service is None:
        await start_booking_entry(
            message,
            state,
            db_session=db_session,
            user=user,
            first_name=first_name,
            replace_current=replace_current,
        )
        return

    await clear_state_preserving_admin_mode(state)
    await state.update_data(
        browse_mode=False,
        repeat_source_booking_id=source_booking.id,
        preferred_days_note=user.preferred_days_note,
        preferred_time_note=user.preferred_time_note,
        base_service_id=source_booking.base_service_id,
        selected_addons=list(source_booking.addons),
        payment_method=normalize_payment_method(source_booking.payment_method),
        selected_day=None,
        slot_id=None,
        design_photos=list(source_booking.design_photos),
        design_comment=source_booking.design_comment,
        reference_comment_requested=False,
    )
    if needs_onboarding(user) or should_confirm_name(user, first_name):
        if replace_current:
            await safe_delete_message(message)
        await state.set_state(Onboarding.confirm_name)
        await message.answer(
            texts.ONBOARDING_NAME_CONFIRM_TEXT.format(first_name=(first_name or "Клиент")),
            reply_markup=build_name_confirmation_keyboard(),
        )
        return

    if not user.phone:
        await state.set_state(Onboarding.input_phone)
        if replace_current:
            await safe_delete_message(message)
        await send_phone_prompt(message)
        return

    await show_day_step(
        message,
        db_session=db_session,
        state=state,
        settings=settings,
        replace=replace_current,
    )


async def start_locked_slot_offer_entry(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    slot_id: int,
    first_name: str | None = None,
    replace_current: bool = False,
) -> None:
    """Start a booking flow with a concrete rescue-offer slot already selected."""
    slot = await SlotRepository(db_session).get_by_id(slot_id)
    button_configs = await load_runtime_button_configs(db_session)
    if slot is None or not slot_is_rescuable(slot):
        await clear_state_preserving_admin_mode(state)
        if replace_current:
            await replace_inline_message_text(
                message,
                texts.CLIENT_RESCUE_SLOT_EXPIRED_TEXT,
                reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
            )
        else:
            await message.answer(
                texts.CLIENT_RESCUE_SLOT_EXPIRED_TEXT,
                reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
            )
        return

    await clear_state_preserving_admin_mode(state)
    await state.update_data(
        browse_mode=True,
        locked_slot_offer=True,
        preferred_days_note=user.preferred_days_note,
        preferred_time_note=user.preferred_time_note,
        slot_id=slot.id,
        selected_day=format_local_datetime(slot.start_at, settings.tz).date().isoformat(),
        base_service_id=None,
        selected_addons=[],
        payment_method=None,
        design_photos=[],
        design_comment=None,
        reference_comment_requested=False,
    )
    if needs_onboarding(user) or should_confirm_name(user, first_name):
        if replace_current:
            await safe_delete_message(message)
        await state.set_state(Onboarding.confirm_name)
        await message.answer(
            texts.ONBOARDING_NAME_CONFIRM_TEXT.format(first_name=(first_name or "Клиент")),
            reply_markup=build_name_confirmation_keyboard(),
        )
        return

    if not user.phone:
        await state.set_state(Onboarding.input_phone)
        if replace_current:
            await safe_delete_message(message)
        await send_phone_prompt(message)
        return

    await show_base_service_step(
        message,
        db_session=db_session,
        state=state,
        replace=replace_current,
    )


async def load_runtime_button_configs(
    db_session: AsyncSession,
) -> dict[str, ClientMenuButtonConfig]:
    """Load editable runtime button configs for client booking-related screens."""
    return await load_all_button_configs(SettingRepository(db_session))


async def load_runtime_contact_url(
    db_session: AsyncSession,
) -> str:
    """Load the current direct-chat URL for «Написать Ангеле» client CTAs."""
    return await load_master_contact_url(SettingRepository(db_session))


async def show_base_service_step(
    message: Message,
    *,
    db_session: AsyncSession,
    state: FSMContext,
    replace: bool = False,
) -> None:
    """Show the base-service selection step."""
    repository = ServiceRepository(db_session)
    button_configs = await load_runtime_button_configs(db_session)
    base_services = await repository.list_active(kind=ServiceKind.BASE)
    if not base_services:
        await clear_state_preserving_admin_mode(state)
        if replace:
            await replace_inline_message_text(
                message,
                texts.NO_ACTIVE_SERVICES_TEXT,
                reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
            )
        else:
            await message.answer(
                texts.NO_ACTIVE_SERVICES_TEXT,
                reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
            )
        return

    current_data = await state.get_data()
    preserve_browse_slot = bool(current_data.get("browse_mode")) and current_data.get("slot_id")
    await state.set_state(BookingStates.choose_base_service)
    await state.update_data(
        base_service_id=None,
        selected_addons=[],
        payment_method=None,
        selected_day=current_data.get("selected_day") if preserve_browse_slot else None,
        slot_id=current_data.get("slot_id") if preserve_browse_slot else None,
        design_photos=current_data.get("design_photos", []),
        design_comment=current_data.get("design_comment"),
        reference_comment_requested=False,
    )
    defaults = required_template_defaults()
    template_repository = TemplateRepository(db_session)
    price_text = await template_repository.get_content_or_default(
        "price",
        defaults["price"],
    )
    await send_template_message(
        message,
        template_key="price",
        caption=price_text.strip() or defaults["price"],
        reply_markup=build_base_services_keyboard(
            base_services,
            button_configs=button_configs,
        ),
        replace_current=replace,
    )


async def show_addons_step(
    message: Message,
    *,
    db_session: AsyncSession,
    state: FSMContext,
    replace: bool = False,
) -> None:
    """Show the add-on selection step."""
    repository = ServiceRepository(db_session)
    button_configs = await load_runtime_button_configs(db_session)
    addons = await repository.list_active(kind=ServiceKind.ADDON)
    data = await state.get_data()
    selected_addons = list(data.get("selected_addons", []))
    await state.set_state(BookingStates.choose_addons)
    prompt_text = build_addons_prompt_text(addons, selected_addons)
    reply_markup = build_addons_keyboard(
        addons,
        selected_addons,
        button_configs=button_configs,
    )
    defaults = required_template_defaults()
    template_repository = TemplateRepository(db_session)
    price_text = await template_repository.get_content_or_default(
        "price",
        defaults["price"],
    )
    caption = prompt_text
    if not has_template_media("price"):
        rendered_price_text = price_text.strip() or defaults["price"]
        caption = f"{rendered_price_text}\n\n{prompt_text}"
    await send_template_message(
        message,
        template_key="price",
        caption=caption,
        reply_markup=reply_markup,
        replace_current=replace,
    )


async def show_payment_step(
    message: Message,
    *,
    db_session: AsyncSession,
    state: FSMContext,
    replace: bool = False,
) -> None:
    """Show the payment-method selection step."""
    button_configs = await load_runtime_button_configs(db_session)
    await state.set_state(BookingStates.choose_payment)
    if replace:
        await send_brand_message(
            message,
            caption=texts.BOOKING_CHOOSE_PAYMENT_TEXT,
            reply_markup=build_payment_method_keyboard(button_configs=button_configs),
            replace_current=True,
        )
        return
    await send_brand_message(
        message,
        caption=texts.BOOKING_CHOOSE_PAYMENT_TEXT,
        reply_markup=build_payment_method_keyboard(button_configs=button_configs),
    )


async def show_day_step(
    message: Message,
    *,
    db_session: AsyncSession,
    state: FSMContext,
    prefix_text: str | None = None,
    settings: Settings,
    replace: bool = False,
    image_page: int | None = None,
) -> None:
    """Show the day selection step."""
    settings_repository = SettingRepository(db_session)
    button_configs = await load_all_button_configs(settings_repository)
    vacation_mode = await get_bool_setting(
        settings_repository,
        key="vacation_mode",
        default=False,
    )
    if vacation_mode:
        template_repository = TemplateRepository(db_session)
        template_defaults = required_template_defaults()
        await clear_state_preserving_admin_mode(state)
        vacation_text = await template_repository.get_content_or_default(
            "vacation_notice",
            template_defaults["vacation_notice"],
        )
        if replace:
            await replace_inline_message_text(
                message,
                vacation_text,
                reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
            )
        else:
            await message.answer(
                vacation_text,
                reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
            )
        return

    repository = SlotRepository(db_session)
    slots = await repository.list_free_future(horizon_days=PUBLIC_BOOKING_HORIZON_DAYS)
    state_data = await state.get_data()
    day_options = order_day_options_by_preference(
        group_slots_by_local_day(slots, settings.tz),
        state_data.get("preferred_days_note"),
    )
    await state.set_state(BookingStates.choose_day)
    day_prompt = (
        f"{prefix_text}\n\n{texts.BOOKING_CHOOSE_DAY_TEXT}"
        if prefix_text
        else texts.BOOKING_CHOOSE_DAY_TEXT
    )
    await render_day_picker(
        message,
        db_session=db_session,
        settings=settings,
        slots=slots,
        day_options=day_options,
        prompt_text=day_prompt,
        no_slots_text=texts.BOOKING_NO_SLOTS_TEXT,
        replace=replace,
        no_slots_reply_markup=build_no_slots_keyboard(
            button_configs=button_configs,
            contact_url=await load_runtime_contact_url(db_session),
        ),
        text_reply_markup_builder=(
            lambda current_day_options: build_days_keyboard(
                current_day_options,
                button_configs=button_configs,
            )
        ),
        image_reply_markup_builder=(
            lambda current_day_options, current_page, total_pages: build_schedule_days_keyboard(
                current_day_options,
                current_page=current_page,
                total_pages=total_pages,
                button_configs=button_configs,
            )
        ),
        schedule_caption_text=texts.BOOKING_SCHEDULE_IMAGE_CAPTION_TEXT,
        image_caption_text=(
            f"{prefix_text}\n\n{texts.BOOKING_SCHEDULE_IMAGE_CAPTION_TEXT}"
            if prefix_text
            else texts.BOOKING_SCHEDULE_IMAGE_CAPTION_TEXT
        ),
        state=state,
        page_state_key=BOOKING_SCHEDULE_PAGE_STATE_KEY,
        image_page=image_page,
    )
    state_data = await state.get_data()
    stored_page = state_data.get(BOOKING_SCHEDULE_PAGE_STATE_KEY)
    if stored_page is not None:
        await state.update_data(booking_schedule_page=stored_page)


async def show_time_step(
    message: Message,
    *,
    db_session: AsyncSession,
    state: FSMContext,
    local_day: date,
    settings: Settings,
    prefix_text: str | None = None,
    replace: bool = False,
) -> None:
    """Show the time selection step for a chosen local day."""
    repository = SlotRepository(db_session)
    button_configs = await load_runtime_button_configs(db_session)
    slots = await repository.list_free_for_local_day(local_day=local_day, tz_name=settings.tz)
    state_data = await state.get_data()
    slots = order_slots_by_time_preference(
        slots,
        state_data.get("preferred_time_note"),
        tz_name=settings.tz,
    )
    await state.set_state(BookingStates.choose_time)
    await state.update_data(selected_day=local_day.isoformat())

    if not slots:
        await show_day_step(
            message,
            db_session=db_session,
            state=state,
            prefix_text=texts.BOOKING_CONFIRM_SLOT_TAKEN_TEXT,
            settings=settings,
            replace=replace,
        )
        return

    time_prompt = (
        f"{prefix_text}\n\n{texts.BOOKING_CHOOSE_TIME_TEXT}"
        if prefix_text
        else texts.BOOKING_CHOOSE_TIME_TEXT
    )
    await render_time_picker(
        message,
        prompt_text=time_prompt,
        replace=replace,
        reply_markup=build_times_keyboard(
            slots,
            settings.tz,
            button_configs=button_configs,
        ),
    )


async def show_reference_prompt(
    message: Message,
    *,
    state: FSMContext,
    replace: bool = False,
) -> None:
    """Show the optional reference-photo prompt."""
    await state.set_state(BookingStates.attach_reference)
    if replace:
        await replace_inline_message_text(
            message,
            texts.BOOKING_REFERENCE_PROMPT_TEXT,
            reply_markup=build_reference_prompt_keyboard(),
        )
    else:
        await message.answer(
            texts.BOOKING_REFERENCE_PROMPT_TEXT,
            reply_markup=build_reference_prompt_keyboard(),
        )


async def send_booking_success_message(
    message: Message,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    start_at,
    base_service_name: str,
    payment_method: str | None = None,
    booking_id: int | None = None,
    replace_current: bool = False,
) -> None:
    """Send the unified booking confirmation into the current chat."""
    await send_booking_confirmation_message(
        message,
        db_session=db_session,
        settings=settings,
        payload=BookingClientConfirmationPayload(
            chat_id=user.tg_id,
            booking_id=booking_id,
            display_name=user.display_name,
            start_at=start_at,
            base_service_name=base_service_name,
            payment_method=payment_method,
        ),
        replace_current=replace_current,
    )


async def show_reference_progress(
    message: Message,
    *,
    db_session: AsyncSession,
    state: FSMContext,
    replace: bool = False,
) -> None:
    """Show the current reference-photo progress."""
    button_configs = await load_runtime_button_configs(db_session)
    data = await state.get_data()
    design_photos = list(data.get("design_photos", []))
    design_comment = data.get("design_comment")
    await state.set_state(BookingStates.reference_input)
    progress_text = build_reference_progress_text(len(design_photos), design_comment)
    reply_markup = build_reference_actions_keyboard(
        can_finish=bool(design_photos or design_comment),
        has_photos=bool(design_photos),
        can_add_more=len(design_photos) < 5,
        button_configs=button_configs,
    )
    if replace:
        await replace_inline_message_text(
            message,
            progress_text,
            reply_markup=reply_markup,
        )
    else:
        await message.answer(
            progress_text,
            reply_markup=reply_markup,
        )


async def start_custom_time_request_prompt(
    message: Message,
    *,
    db_session: AsyncSession,
    state: FSMContext,
    preferred_day: date | None,
    request_kind: ApprovalRequestKind,
    related_booking_id: int | None = None,
    back_target: str = CUSTOM_TIME_BACK_TARGET_DAY,
    replace: bool = False,
) -> None:
    """Switch the flow into a free-form custom-time request."""
    button_configs = await load_runtime_button_configs(db_session)
    await state.set_state(AwaitCustomTime.input_text)
    await state.update_data(
        custom_request_kind=request_kind.value,
        custom_request_preferred_day=preferred_day.isoformat()
        if preferred_day is not None
        else None,
        related_booking_id=related_booking_id,
        custom_request_back_target=back_target,
    )
    prompt_text = custom_time_prompt_text(request_kind)
    if replace:
        await replace_inline_message_text(
            message,
            prompt_text,
            reply_markup=build_back_to_menu_keyboard(
                callback_data="booking:custom_time_back",
                button_configs=button_configs,
            ),
        )
    else:
        await message.answer(
            prompt_text,
            reply_markup=build_back_to_menu_keyboard(
                callback_data="booking:custom_time_back",
                button_configs=button_configs,
            ),
        )


def _preferred_day_probe_start(preferred_day: date, *, tz_name: str) -> datetime:
    """Use noon of the preferred day as a stable anti-abuse proximity probe."""
    local_noon = datetime.combine(preferred_day, time(hour=12), tzinfo=ZoneInfo(tz_name))
    return local_noon.astimezone(UTC)


def resolve_confirm_return_target(state_data: dict[str, object]) -> str:
    """Remember where the confirm screen should return on «Назад»."""
    if state_data.get("browse_mode") and state_data.get("slot_id"):
        return "browse_service"
    if state_data.get("selected_day"):
        return "time"
    return "day"


def render_booking_cooldown_text(minutes: int | None) -> str:
    """Render the cooldown copy with a safe minute fallback."""
    return texts.BOOKING_RETRY_LATER_TEXT.format(minutes=max(1, minutes or 1))


async def guard_custom_time_request(
    *,
    db_session: AsyncSession,
    user: User,
    request_kind: ApprovalRequestKind,
    preferred_day: date | None,
    settings: Settings,
) -> tuple[str, ApprovalRequestKind, int | None]:
    """Apply the same client-safety gates before creating a free-form request."""
    anti_settings = await get_anti_abuse_settings(db_session)
    now = utcnow()
    approvals = ApprovalRequestRepository(db_session)
    bookings = BookingRepository(db_session)
    events = RateLimitEventRepository(db_session)

    if user.is_blocked:
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "blocked", "path": "custom_time"},
            created_at=now,
        )
        await db_session.commit()
        return "blocked", request_kind, None

    if user.is_shadow_banned:
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "shadow_banned", "path": "custom_time"},
            created_at=now,
        )
        await db_session.commit()
        return "shadow_banned", request_kind, None

    pause_since = now - timedelta(minutes=anti_settings["booking_attempt_pause_minutes"])
    if await events.has_since(user_id=user.id, kind="booking_attempt_pause", since=pause_since):
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "attempt_limit", "path": "custom_time"},
            created_at=now,
        )
        await db_session.commit()
        return "attempt_limit", request_kind, None

    attempt_window_since = now - timedelta(
        minutes=anti_settings["booking_attempt_limit_window_minutes"]
    )
    recent_attempt_count = await events.count_since(
        user_id=user.id,
        kind="booking_attempt",
        since=attempt_window_since,
    )
    if recent_attempt_count >= anti_settings["booking_attempt_limit_count"]:
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt_pause",
            metadata={
                "recent_attempts": recent_attempt_count,
                "window_minutes": anti_settings["booking_attempt_limit_window_minutes"],
                "path": "custom_time",
            },
            created_at=now,
        )
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "attempt_limit", "path": "custom_time"},
            created_at=now,
        )
        await db_session.commit()
        return "attempt_limit", request_kind, None

    if request_kind != ApprovalRequestKind.RESCHEDULE:
        latest_cancel, effective_cooldown_minutes = await resolve_cancel_cooldown(
            bookings=bookings,
            events=events,
            user_id=user.id,
            now=now,
            base_cooldown_minutes=anti_settings["cancel_cooldown_minutes"],
        )
        if latest_cancel is not None:
            cooldown_minutes = remaining_cooldown_minutes(
                event_created_at=latest_cancel.created_at,
                now=now,
                cooldown_minutes=effective_cooldown_minutes,
            )
            await record_rate_event(
                db_session,
                user_id=user.id,
                kind="booking_attempt",
                metadata={
                    "outcome": "cooldown",
                    "path": "custom_time",
                    "minutes_left": cooldown_minutes,
                },
                created_at=now,
            )
            await db_session.commit()
            return "cooldown", request_kind, cooldown_minutes

        active_booking_count = await bookings.count_upcoming_active_for_client(user.id, now_utc=now)
        if active_booking_count >= anti_settings["max_active_bookings_per_user"]:
            await record_rate_event(
                db_session,
                user_id=user.id,
                kind="booking_attempt",
                metadata={
                    "outcome": "active_limit",
                    "active_booking_count": active_booking_count,
                    "path": "custom_time",
                },
                created_at=now,
            )
            await db_session.commit()
            return "active_limit", request_kind, None

    effective_kind = request_kind
    if request_kind == ApprovalRequestKind.NEW_BOOKING:
        if user.requires_manual_approval:
            effective_kind = ApprovalRequestKind.MANUAL_APPROVAL_REQUIRED
        elif preferred_day is not None and await bookings.has_relevant_booking_within_window(
            user.id,
            target_start_at=_preferred_day_probe_start(preferred_day, tz_name=settings.tz),
            window_days=anti_settings["min_days_between_bookings"],
        ):
            completed_visits = await bookings.count_completed_for_client(user.id)
            if completed_visits < anti_settings["frequent_booking_bypass_visits"]:
                effective_kind = ApprovalRequestKind.FREQUENT_BOOKING

    if (
        await approvals.count_pending_for_client(user.id)
        >= anti_settings["max_pending_approvals_per_user"]
    ):
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "pending_limit", "path": "custom_time"},
            created_at=now,
        )
        await db_session.commit()
        return "pending_limit", effective_kind, None

    return "ok", effective_kind, None


async def show_confirm_step(
    message: Message,
    *,
    db_session: AsyncSession,
    state: FSMContext,
    settings: Settings,
    user: User,
    replace: bool = False,
) -> None:
    """Show the final booking confirmation step."""
    if not user.phone:
        await state.update_data(onboarding_resume_target="confirm")
        await state.set_state(Onboarding.input_phone)
        await send_phone_prompt(message)
        return

    data = await state.get_data()
    button_configs = await load_runtime_button_configs(db_session)
    repository = ServiceRepository(db_session)
    slot_repository = SlotRepository(db_session)

    base_service = await repository.get_by_id(int(data["base_service_id"]))
    slot = await slot_repository.get_by_id(int(data["slot_id"]))
    addons = await repository.list_by_ids(list(data.get("selected_addons", [])))
    if base_service is None or slot is None:
        await clear_state_preserving_admin_mode(state)
        if replace:
            await replace_inline_message_text(
                message,
                texts.BOOKING_STALE_DATA_TEXT,
                reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
            )
        else:
            await message.answer(
                texts.BOOKING_STALE_DATA_TEXT,
                reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
            )
        return

    await state.set_state(BookingStates.confirm)
    await state.update_data(confirm_return_target=resolve_confirm_return_target(data))
    summary_text = build_booking_summary_text(
        base_service=base_service,
        addons=addons,
        slot=slot,
        tz_name=settings.tz,
        design_photo_count=len(data.get("design_photos", [])),
        design_comment=data.get("design_comment"),
        payment_method=data.get("payment_method"),
    )
    if replace:
        await replace_inline_message_text(
            message,
            summary_text,
            reply_markup=build_confirm_keyboard(button_configs=button_configs),
        )
    else:
        await message.answer(
            summary_text,
            reply_markup=build_confirm_keyboard(button_configs=button_configs),
        )


async def start_booking_entry(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    first_name: str | None = None,
    replace_current: bool = False,
) -> None:
    """Enter the booking flow from either a callback or a bot command."""
    await clear_state_preserving_admin_mode(state)
    await state.update_data(
        browse_mode=False,
        preferred_days_note=user.preferred_days_note,
        preferred_time_note=user.preferred_time_note,
    )
    if needs_onboarding(user) or should_confirm_name(user, first_name):
        if replace_current:
            await safe_delete_message(message)
        await state.set_state(Onboarding.confirm_name)
        await message.answer(
            texts.ONBOARDING_NAME_CONFIRM_TEXT.format(first_name=(first_name or "Клиент")),
            reply_markup=build_name_confirmation_keyboard(),
        )
        return

    if not user.phone:
        await state.set_state(Onboarding.input_phone)
        if replace_current:
            await safe_delete_message(message)
        await send_phone_prompt(message)
        return

    await show_base_service_step(
        message,
        db_session=db_session,
        state=state,
        replace=replace_current,
    )


async def start_browse_entry(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    first_name: str | None = None,
    replace_current: bool = False,
) -> None:
    """Enter the browse-only free-slots flow before service selection."""
    await clear_state_preserving_admin_mode(state)
    await state.update_data(
        browse_mode=True,
        preferred_days_note=user.preferred_days_note,
        preferred_time_note=user.preferred_time_note,
    )
    if needs_onboarding(user) or should_confirm_name(user, first_name):
        if replace_current:
            await safe_delete_message(message)
        await state.set_state(Onboarding.confirm_name)
        await message.answer(
            texts.ONBOARDING_NAME_CONFIRM_TEXT.format(first_name=(first_name or "Клиент")),
            reply_markup=build_name_confirmation_keyboard(),
        )
        return

    if not user.phone:
        await state.set_state(Onboarding.input_phone)
        if replace_current:
            await safe_delete_message(message)
        await send_phone_prompt(message)
        return

    await show_day_step(
        message,
        db_session=db_session,
        state=state,
        settings=settings,
        replace=replace_current,
    )


@router.callback_query(F.data == "client_menu:book")
async def start_booking(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Start the booking flow or onboarding."""
    await callback.answer()
    if callback.message is None:
        return

    await start_booking_entry(
        callback.message,
        state,
        db_session=db_session,
        user=user,
        first_name=(callback.from_user.first_name if callback.from_user else None),
        replace_current=True,
    )


@router.callback_query(F.data == "client_menu:browse")
async def start_browse(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Start the browse-only free-slots flow."""
    await callback.answer()
    if callback.message is None:
        return

    await start_browse_entry(
        callback.message,
        state,
        db_session=db_session,
        user=user,
        settings=settings,
        first_name=(callback.from_user.first_name if callback.from_user else None),
        replace_current=True,
    )


@router.callback_query(F.data.startswith("rescue_offer:claim:"))
async def claim_rescue_offer(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Start booking from a last-minute free-slot offer."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    slot_id = int(callback.data.rsplit(":", 1)[-1])
    await start_locked_slot_offer_entry(
        callback.message,
        state,
        db_session=db_session,
        user=user,
        settings=settings,
        slot_id=slot_id,
        first_name=(callback.from_user.first_name if callback.from_user else None),
        replace_current=True,
    )


@router.callback_query(F.data.startswith("rescue_offer:dismiss:"))
async def dismiss_rescue_offer(callback: CallbackQuery) -> None:
    """Dismiss a proactive free-slot offer."""
    await callback.answer(texts.REMINDER_ACK_NOTICE_TEXT)
    if callback.message is not None:
        await replace_inline_message_text(callback.message, texts.CLIENT_RESCUE_SLOT_DISMISSED_TEXT)


@router.callback_query(StateFilter(Onboarding.confirm_name), F.data == "onboarding:name_yes")
async def onboarding_name_confirmed(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Accept the Telegram first name as the client's display name."""
    await callback.answer()
    if callback.message is None:
        return

    repository = UserRepository(db_session)
    display_name = (callback.from_user.first_name if callback.from_user else "Клиент").strip()[
        :40
    ] or "Клиент"
    await repository.update_profile(user, display_name=display_name)
    await db_session.commit()

    await safe_delete_message(callback.message)
    if not user.phone:
        await state.set_state(Onboarding.input_phone)
        await send_phone_prompt(callback.message)
        return
    await continue_after_onboarding(
        callback.message,
        db_session=db_session,
        state=state,
        settings=settings,
        user=user,
    )


@router.callback_query(StateFilter(Onboarding.confirm_name), F.data == "onboarding:name_other")
async def onboarding_request_custom_name(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask the client to type a custom display name."""
    await callback.answer()
    if callback.message is None:
        return

    await state.set_state(Onboarding.input_name)
    await replace_inline_message_text(callback.message, texts.ONBOARDING_NAME_INPUT_TEXT)


@router.message(StateFilter(Onboarding.confirm_name), F.text)
async def onboarding_custom_name_from_confirm(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Accept a typed name even if the client skipped the inline buttons."""
    await save_custom_name_and_continue(
        message,
        state=state,
        db_session=db_session,
        user=user,
        settings=settings,
    )


async def save_custom_name_and_continue(
    message: Message,
    *,
    state: FSMContext,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Persist a custom display name once and continue the onboarding flow."""
    display_name = (message.text or "").strip()
    if not 1 <= len(display_name) <= 40:
        await message.answer(texts.ONBOARDING_NAME_INVALID_TEXT)
        return

    repository = UserRepository(db_session)
    await repository.update_profile(user, display_name=display_name)
    await db_session.commit()

    if not user.phone:
        await state.set_state(Onboarding.input_phone)
        await send_phone_prompt(message)
        return
    await continue_after_onboarding(
        message,
        db_session=db_session,
        state=state,
        settings=settings,
        user=user,
    )


@router.message(StateFilter(Onboarding.input_name))
async def onboarding_custom_name_input(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Store a custom display name and continue into the booking flow."""
    await save_custom_name_and_continue(
        message,
        state=state,
        db_session=db_session,
        user=user,
        settings=settings,
    )


async def finish_phone_step(
    message: Message,
    *,
    state: FSMContext,
    db_session: AsyncSession,
    settings: Settings,
    user: User,
) -> None:
    """Close the phone step consistently for both contact and manual input."""
    await message.answer(
        texts.ONBOARDING_PHONE_SAVED_TEXT,
        reply_markup=ReplyKeyboardRemove(),
    )
    await continue_after_onboarding(
        message,
        db_session=db_session,
        state=state,
        settings=settings,
        user=user,
    )


@router.callback_query(StateFilter(Onboarding.input_phone), F.data == "onboarding:phone_manual")
async def onboarding_phone_manual(callback: CallbackQuery) -> None:
    """Switch the phone step to manual input."""
    await callback.answer()
    if callback.message is not None:
        await replace_inline_message_text(
            callback.message, texts.ONBOARDING_PHONE_MANUAL_INPUT_TEXT
        )


@router.message(StateFilter(Onboarding.input_phone), F.contact)
async def onboarding_phone_contact(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Store the phone number shared via Telegram contact."""
    if message.contact is None:
        return

    if (
        message.from_user is not None
        and message.contact.user_id is not None
        and message.contact.user_id != message.from_user.id
    ):
        await message.answer(texts.ONBOARDING_CONTACT_FOREIGN_TEXT)
        return

    repository = UserRepository(db_session)
    normalized_phone = normalize_phone(message.contact.phone_number) or message.contact.phone_number
    duplicate_user = await repository.find_by_phone(normalized_phone, exclude_user_id=user.id)
    if duplicate_user is not None:
        await message.answer(texts.ONBOARDING_PHONE_DUPLICATE_TEXT)
        return

    await repository.update_profile(user, phone=normalized_phone)
    user.duplicate_phone_flag = False
    await db_session.commit()
    await finish_phone_step(
        message,
        state=state,
        db_session=db_session,
        settings=settings,
        user=user,
    )


@router.message(StateFilter(Onboarding.input_phone))
async def onboarding_phone_text(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Store a manually typed phone number."""
    raw_text = (message.text or "").strip()
    if raw_text == PHONE_MANUAL_BUTTON_TEXT:
        await message.answer(texts.ONBOARDING_PHONE_MANUAL_INPUT_TEXT)
        return

    normalized_phone = normalize_phone(raw_text)
    if normalized_phone is None:
        await message.answer(texts.ONBOARDING_PHONE_INVALID_TEXT)
        return

    repository = UserRepository(db_session)
    duplicate_user = await repository.find_by_phone(normalized_phone, exclude_user_id=user.id)
    if duplicate_user is not None:
        await message.answer(texts.ONBOARDING_PHONE_DUPLICATE_TEXT)
        return

    await repository.update_profile(user, phone=normalized_phone)
    user.duplicate_phone_flag = False
    await db_session.commit()
    await finish_phone_step(
        message,
        state=state,
        db_session=db_session,
        settings=settings,
        user=user,
    )


@router.callback_query(
    StateFilter(BookingStates.choose_base_service), F.data.startswith("booking:base:")
)
async def choose_base_service(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Store the selected base service and move to add-ons."""
    await callback.answer()
    if callback.message is None:
        return

    base_service_id = int(callback.data.rsplit(":", 1)[-1])
    await state.update_data(base_service_id=base_service_id, selected_addons=[])
    await show_addons_step(callback.message, db_session=db_session, state=state, replace=True)


@router.callback_query(
    StateFilter(BookingStates.choose_addons), F.data.startswith("booking:addon_toggle:")
)
async def toggle_addon(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Toggle an add-on selection in place."""
    await callback.answer()
    if callback.message is None:
        return

    addon_id = int(callback.data.rsplit(":", 1)[-1])
    data = await state.get_data()
    selected_addons = list(data.get("selected_addons", []))
    if addon_id in selected_addons:
        selected_addons.remove(addon_id)
    else:
        selected_addons.append(addon_id)
    await state.update_data(selected_addons=selected_addons)
    await show_addons_step(
        callback.message,
        db_session=db_session,
        state=state,
        replace=True,
    )


@router.callback_query(StateFilter(BookingStates.choose_addons), F.data == "booking:addons_done")
async def finish_addons(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Finish add-on selection and move to the payment step."""
    await callback.answer()
    if callback.message is None:
        return

    await show_payment_step(
        callback.message,
        db_session=db_session,
        state=state,
        replace=True,
    )


@router.message(StateFilter(BookingStates.choose_base_service), F.text)
async def choose_base_service_text_fallback(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Repeat the service step when the client types text instead of tapping."""
    await message.answer(texts.BUTTON_CHOICE_HINT_TEXT)
    await show_base_service_step(message, db_session=db_session, state=state)


@router.message(StateFilter(BookingStates.choose_addons), F.text)
async def choose_addons_text_fallback(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Repeat the addons step when the client types text instead of tapping."""
    await message.answer(texts.BUTTON_CHOICE_HINT_TEXT)
    await show_addons_step(message, db_session=db_session, state=state)


@router.callback_query(StateFilter(BookingStates.choose_addons), F.data == "booking:addons_back")
async def addons_back(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Return from add-ons to the base-service step."""
    await callback.answer()
    if callback.message is not None:
        await show_base_service_step(
            callback.message,
            db_session=db_session,
            state=state,
            replace=True,
        )


@router.callback_query(
    StateFilter(BookingStates.choose_payment), F.data.startswith("booking:payment:")
)
async def choose_payment_method(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
    user: User,
) -> None:
    """Store the selected payment method and move to day selection."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    raw_payment_method = callback.data.rsplit(":", 1)[-1]
    if raw_payment_method not in {PAYMENT_METHOD_CASH, PAYMENT_METHOD_TRANSFER}:
        raw_payment_method = PAYMENT_METHOD_TRANSFER
    await state.update_data(payment_method=normalize_payment_method(raw_payment_method))
    state_data = await state.get_data()
    if state_data.get("browse_mode") and state_data.get("slot_id"):
        await show_confirm_step(
            callback.message,
            db_session=db_session,
            state=state,
            settings=settings,
            user=user,
            replace=True,
        )
        return
    await show_day_step(
        callback.message,
        db_session=db_session,
        state=state,
        settings=settings,
        replace=True,
    )


@router.callback_query(StateFilter(BookingStates.choose_payment), F.data == "booking:payment_back")
async def payment_back(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Return from payment selection to add-ons."""
    await callback.answer()
    if callback.message is not None:
        await show_addons_step(
            callback.message,
            db_session=db_session,
            state=state,
            replace=True,
        )


@router.message(StateFilter(BookingStates.choose_payment), F.text)
async def choose_payment_text_fallback(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Repeat the payment step when the client types text instead of tapping."""
    await message.answer(texts.BUTTON_CHOICE_HINT_TEXT)
    await show_payment_step(message, db_session=db_session, state=state)


@router.callback_query(StateFilter(BookingStates.choose_day), F.data.startswith("booking:day:"))
async def choose_day(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Store the selected day and show available times."""
    await callback.answer()
    if callback.message is None:
        return

    selected_day = date.fromisoformat(callback.data.rsplit(":", 1)[-1])
    await show_time_step(
        callback.message,
        db_session=db_session,
        state=state,
        local_day=selected_day,
        settings=settings,
        replace=True,
    )


@router.callback_query(StateFilter(BookingStates.choose_day), F.data == "booking:day_back")
async def day_back(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Return from day selection to payment choice."""
    await callback.answer()
    if callback.message is None:
        return
    data = await state.get_data()
    if data.get("browse_mode") and not data.get("payment_method"):
        await clear_state_preserving_admin_mode(state)
        await show_client_menu(
            callback.message,
            db_session=db_session,
            user=user,
            replace_current=True,
        )
        return
    await show_payment_step(
        callback.message,
        db_session=db_session,
        state=state,
        replace=True,
    )


@router.message(StateFilter(BookingStates.choose_day), F.text)
async def choose_day_text_fallback(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Repeat the day step when the client types text instead of tapping."""
    await message.answer(texts.BUTTON_CHOICE_HINT_TEXT)
    await show_day_step(message, db_session=db_session, state=state, settings=settings)


@router.callback_query(StateFilter(BookingStates.choose_day), F.data == "booking:other_day")
async def request_other_day(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Route the client into the custom-date request flow."""
    await callback.answer()
    if callback.message is None:
        return

    await start_custom_time_request_prompt(
        callback.message,
        db_session=db_session,
        state=state,
        preferred_day=None,
        request_kind=ApprovalRequestKind.NEW_BOOKING,
        back_target=CUSTOM_TIME_BACK_TARGET_DAY,
        replace=True,
    )


@router.callback_query(
    StateFilter(BookingStates.choose_day),
    F.data.startswith("booking:schedule_page:"),
)
async def change_schedule_image_page(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Flip one page inside the client schedule image viewer."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    page = int(callback.data.rsplit(":", 1)[-1])
    await show_day_step(
        callback.message,
        db_session=db_session,
        state=state,
        settings=settings,
        replace=True,
        image_page=page,
    )


@router.callback_query(StateFilter(BookingStates.choose_day), F.data == "booking:schedule_noop")
async def booking_schedule_noop(callback: CallbackQuery) -> None:
    """Acknowledge the inert page number button in the client schedule viewer."""
    await callback.answer()


@router.callback_query(StateFilter(BookingStates.choose_time), F.data.startswith("booking:time:"))
async def choose_time(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
    user: User,
) -> None:
    """Store the selected slot and move to the reference step."""
    await callback.answer()
    if callback.message is None:
        return

    slot_id = int(callback.data.rsplit(":", 1)[-1])
    slot_repository = SlotRepository(db_session)
    slot = await slot_repository.get_by_id(slot_id)
    if slot is None:
        data = await state.get_data()
        selected_day_value = data.get("selected_day")
        if selected_day_value:
            await show_time_step(
                callback.message,
                db_session=db_session,
                state=state,
                local_day=date.fromisoformat(selected_day_value),
                settings=settings,
                prefix_text=texts.BOOKING_CONFIRM_SLOT_TAKEN_TEXT,
                replace=True,
            )
            return
        await show_day_step(
            callback.message,
            db_session=db_session,
            state=state,
            prefix_text=texts.BOOKING_CONFIRM_SLOT_TAKEN_TEXT,
            settings=settings,
            replace=True,
        )
        return

    await state.update_data(slot_id=slot_id)
    state_data = await state.get_data()
    if state_data.get("browse_mode"):
        await show_base_service_step(
            callback.message,
            db_session=db_session,
            state=state,
            replace=True,
        )
        return

    await show_confirm_step(
        callback.message,
        db_session=db_session,
        state=state,
        settings=settings,
        user=user,
        replace=True,
    )


@router.callback_query(StateFilter(BookingStates.choose_time), F.data == "booking:time_back")
async def time_back(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Return from time selection to day selection."""
    await callback.answer()
    if callback.message is not None:
        data = await state.get_data()
        stored_page = data.get(
            BOOKING_SCHEDULE_PAGE_STATE_KEY,
            data.get("booking_schedule_page"),
        )
        await show_day_step(
            callback.message,
            db_session=db_session,
            state=state,
            settings=settings,
            replace=True,
            image_page=int(stored_page) if stored_page is not None else None,
        )


@router.callback_query(StateFilter(BookingStates.choose_time), F.data == "booking:other_time")
async def request_other_time(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Route the client into the custom-time request flow for the chosen day."""
    await callback.answer()
    if callback.message is None:
        return

    data = await state.get_data()
    preferred_day_value = data.get("selected_day")
    preferred_day = date.fromisoformat(preferred_day_value) if preferred_day_value else None
    await start_custom_time_request_prompt(
        callback.message,
        db_session=db_session,
        state=state,
        preferred_day=preferred_day,
        request_kind=ApprovalRequestKind.NEW_BOOKING,
        back_target=CUSTOM_TIME_BACK_TARGET_TIME,
        replace=True,
    )


@router.callback_query(
    StateFilter(AwaitCustomTime.input_text),
    F.data == "booking:custom_time_back",
)
async def custom_time_back(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Return from the custom-time prompt to the most recent booking step."""
    await callback.answer()
    if callback.message is None:
        return

    data = await state.get_data()
    back_target = data.get("custom_request_back_target", CUSTOM_TIME_BACK_TARGET_DAY)
    if back_target == CUSTOM_TIME_BACK_TARGET_TIME:
        selected_day_value = data.get("selected_day") or data.get("custom_request_preferred_day")
        if selected_day_value:
            await show_time_step(
                callback.message,
                db_session=db_session,
                state=state,
                local_day=date.fromisoformat(selected_day_value),
                settings=settings,
                replace=True,
            )
            return

    await show_day_step(
        callback.message,
        db_session=db_session,
        state=state,
        settings=settings,
        replace=True,
    )


@router.message(StateFilter(BookingStates.choose_time), F.text)
async def choose_time_text_fallback(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Repeat the time step when the client types text instead of tapping."""
    await message.answer(texts.BUTTON_CHOICE_HINT_TEXT)
    data = await state.get_data()
    selected_day_value = data.get("selected_day")
    if selected_day_value:
        await show_time_step(
            message,
            db_session=db_session,
            state=state,
            local_day=date.fromisoformat(selected_day_value),
            settings=settings,
        )
        return
    await show_day_step(message, db_session=db_session, state=state, settings=settings)


@router.message(StateFilter(AwaitCustomTime.input_text), F.text)
@router.message(StateFilter(AwaitCustomTime.input_text), F.voice)
async def submit_custom_time_request(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Create an approval request for a free-form date/time preference."""
    data = await state.get_data()
    request_kind = ApprovalRequestKind(
        data.get("custom_request_kind", ApprovalRequestKind.NEW_BOOKING.value)
    )
    preferred_day_value = data.get("custom_request_preferred_day")
    preferred_day = date.fromisoformat(preferred_day_value) if preferred_day_value else None
    if message.text:
        requested_text = message.text.strip()
    elif message.voice:
        requested_text = f"(голосовое, file_id={message.voice.file_id})"
    else:
        requested_text = "(голосовое)"

    guard_outcome, request_kind, cooldown_minutes = await guard_custom_time_request(
        db_session=db_session,
        user=user,
        request_kind=request_kind,
        preferred_day=preferred_day,
        settings=settings,
    )
    if guard_outcome == "blocked":
        await clear_state_preserving_admin_mode(state)
        button_configs = await load_runtime_button_configs(db_session)
        await message.answer(
            texts.BOOKING_BLOCKED_TEXT,
            reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
        )
        return
    if guard_outcome == "shadow_banned":
        await clear_state_preserving_admin_mode(state)
        button_configs = await load_runtime_button_configs(db_session)
        await message.answer(
            approval_sent_text(request_kind),
            reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
        )
        return
    if guard_outcome == "pending_limit":
        await clear_state_preserving_admin_mode(state)
        button_configs = await load_runtime_button_configs(db_session)
        await message.answer(
            texts.BOOKING_PENDING_APPROVALS_LIMIT_TEXT,
            reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
        )
        return
    if guard_outcome == "active_limit":
        await clear_state_preserving_admin_mode(state)
        button_configs = await load_runtime_button_configs(db_session)
        await message.answer(
            texts.BOOKING_ACTIVE_LIMIT_TEXT,
            reply_markup=build_booking_action_result_keyboard(button_configs=button_configs),
        )
        return
    if guard_outcome == "attempt_limit":
        await clear_state_preserving_admin_mode(state)
        button_configs = await load_runtime_button_configs(db_session)
        await message.answer(
            texts.BOOKING_ATTEMPT_LIMIT_TEXT,
            reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
        )
        return
    if guard_outcome == "cooldown":
        await clear_state_preserving_admin_mode(state)
        button_configs = await load_runtime_button_configs(db_session)
        await message.answer(
            render_booking_cooldown_text(cooldown_minutes),
            reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
        )
        return

    if request_kind == ApprovalRequestKind.RESCHEDULE:
        related_booking_id = int(data["related_booking_id"])
        booking = await BookingRepository(db_session).get_client_booking(
            related_booking_id, user.id
        )
        if booking is None:
            await clear_state_preserving_admin_mode(state)
            button_configs = await load_runtime_button_configs(db_session)
            await message.answer(
                texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
                reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
            )
            return

        base_service_id = booking.base_service_id
        addons = list(booking.addons)
        design_photos = list(booking.design_photos)
        design_comment = booking.design_comment
        payment_method = booking.payment_method
    else:
        base_service_id = int(data["base_service_id"])
        related_booking_id = None
        addons = list(data.get("selected_addons", []))
        design_photos = list(data.get("design_photos", []))
        design_comment = data.get("design_comment")
        payment_method = data.get("payment_method")

    repository = ApprovalRequestRepository(db_session)
    approval, approval_created = await repository.create_or_reuse_pending(
        client_id=user.id,
        base_service_id=base_service_id,
        addons=addons,
        design_photos=design_photos,
        design_comment=design_comment,
        requested_text=requested_text,
        preferred_day=preferred_day,
        payment_method=payment_method,
        kind=request_kind,
        related_booking_id=related_booking_id,
    )
    remember_client_preference_hints(
        user,
        preferred_day=preferred_day,
        preferred_time_text=requested_text if message.text else None,
        design_comment=design_comment,
    )
    user.repeat_prompt_snoozed_until = None
    await record_rate_event(
        db_session,
        user_id=user.id,
        kind="booking_attempt",
        metadata={
            "outcome": "custom_time_request",
            "approval_id": approval.id,
            "kind": request_kind.value,
        },
    )
    await db_session.commit()
    loaded_approval = await repository.get_by_id(approval.id)
    if loaded_approval is not None and approval_created:
        await send_approval_card_to_admins(
            bot=message.bot,
            settings=settings,
            db_session=db_session,
            approval=loaded_approval,
        )
    if message.voice and approval_created:
        await send_voice_to_admins(
            message.bot,
            admin_tg_ids=settings.admin_tg_id_set,
            voice=message.voice.file_id,
        )

    await clear_state_preserving_admin_mode(state)
    button_configs = await load_runtime_button_configs(db_session)
    await message.answer(
        approval_sent_text(request_kind),
        reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
    )


@router.callback_query(
    StateFilter(BookingStates.attach_reference), F.data == "booking:attach_photo"
)
@router.callback_query(StateFilter(BookingStates.reference_input), F.data == "booking:attach_photo")
async def attach_reference_photo(callback: CallbackQuery, state: FSMContext) -> None:
    """Switch the reference step into photo-upload mode."""
    await callback.answer()
    if callback.message is None:
        return

    await state.set_state(BookingStates.reference_input)
    await replace_inline_message_text(callback.message, texts.BOOKING_REFERENCE_WAITING_TEXT)


@router.callback_query(
    StateFilter(BookingStates.attach_reference), F.data == "booking:skip_reference"
)
async def skip_reference(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
    user: User,
) -> None:
    """Skip the optional reference step and show confirmation."""
    await callback.answer()
    if callback.message is not None:
        await show_confirm_step(
            callback.message,
            db_session=db_session,
            state=state,
            settings=settings,
            user=user,
            replace=True,
        )


@router.message(StateFilter(BookingStates.attach_reference), F.text)
async def attach_reference_text_fallback(message: Message, state: FSMContext) -> None:
    """Repeat the reference choice when the client types text instead of tapping."""
    await message.answer(texts.BUTTON_CHOICE_HINT_TEXT)
    await show_reference_prompt(message, state=state)


@router.message(StateFilter(BookingStates.reference_input), F.photo)
async def receive_reference_photo(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Save a reference photo and show the current progress."""
    data = await state.get_data()
    design_photos = list(data.get("design_photos", []))
    if len(design_photos) >= 5:
        await message.answer(texts.BOOKING_REFERENCE_LIMIT_TEXT)
        return

    photo = message.photo[-1]
    design_photos.append(photo.file_id)
    await state.update_data(
        design_photos=design_photos,
        reference_comment_requested=False,
    )
    await show_reference_progress(message, db_session=db_session, state=state)


@router.callback_query(
    StateFilter(BookingStates.reference_input), F.data == "booking:reference_comment"
)
async def request_reference_comment(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask for a text comment describing the references."""
    await callback.answer()
    await state.update_data(reference_comment_requested=True)
    if callback.message is not None:
        await replace_inline_message_text(
            callback.message, texts.BOOKING_REFERENCE_COMMENT_INPUT_TEXT
        )


@router.message(StateFilter(BookingStates.reference_input))
async def receive_reference_comment(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Save a reference comment when the flow expects one."""
    data = await state.get_data()
    if not data.get("reference_comment_requested"):
        await message.answer(texts.BOOKING_REFERENCE_WAITING_TEXT)
        return

    await state.update_data(
        design_comment=(message.text or "").strip() or None,
        reference_comment_requested=False,
    )
    await message.answer(texts.BOOKING_REFERENCE_COMMENT_SAVED_TEXT)
    await show_reference_progress(message, db_session=db_session, state=state)


@router.callback_query(
    StateFilter(BookingStates.reference_input), F.data == "booking:reference_remove_last"
)
async def remove_last_reference(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Remove the last uploaded reference photo."""
    await callback.answer()
    if callback.message is None:
        return

    data = await state.get_data()
    design_photos = list(data.get("design_photos", []))
    if design_photos:
        design_photos.pop()
    await state.update_data(design_photos=design_photos)

    if not design_photos and not data.get("design_comment"):
        await show_reference_prompt(callback.message, state=state, replace=True)
        return

    await show_reference_progress(
        callback.message,
        db_session=db_session,
        state=state,
        replace=True,
    )


@router.callback_query(
    StateFilter(BookingStates.reference_input), F.data == "booking:reference_done"
)
async def finish_reference_input(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
    user: User,
) -> None:
    """Finish the reference step and show booking confirmation."""
    await callback.answer()
    if callback.message is not None:
        await show_confirm_step(
            callback.message,
            db_session=db_session,
            state=state,
            settings=settings,
            user=user,
            replace=True,
        )


@router.callback_query(StateFilter(BookingStates.confirm), F.data == "booking:confirm_back")
async def confirm_back(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Return from confirmation to the time-selection step."""
    await callback.answer()
    if callback.message is None:
        return

    data = await state.get_data()
    confirm_return_target = str(data.get("confirm_return_target") or "")
    selected_day_value = data.get("selected_day")
    if (
        confirm_return_target == "browse_service"
        and data.get("browse_mode")
        and data.get("slot_id")
    ):
        await show_base_service_step(
            callback.message,
            db_session=db_session,
            state=state,
            replace=True,
        )
        return
    if confirm_return_target == "time" and selected_day_value:
        await show_time_step(
            callback.message,
            db_session=db_session,
            state=state,
            local_day=date.fromisoformat(selected_day_value),
            settings=settings,
            replace=True,
        )
        return
    await show_day_step(
        callback.message,
        db_session=db_session,
        state=state,
        settings=settings,
        replace=True,
    )


@router.message(StateFilter(BookingStates.confirm), F.text)
async def confirm_text_fallback(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
    user: User,
) -> None:
    """Repeat the final confirmation step when the client types text instead of tapping."""
    await message.answer(texts.BUTTON_CHOICE_HINT_TEXT)
    await show_confirm_step(
        message,
        db_session=db_session,
        state=state,
        settings=settings,
        user=user,
    )


@router.callback_query(F.data == "booking:cancel")
async def cancel_booking_flow(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Cancel the current booking flow and return to the menu."""
    await callback.answer(texts.BOOKING_CANCELLED_TEXT)
    await clear_state_preserving_admin_mode(state)
    if callback.message is not None:
        await show_client_menu(
            callback.message,
            db_session=db_session,
            user=user,
            replace_current=True,
        )


@router.callback_query(F.data == "client:to_menu")
async def post_booking_to_menu(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Return to the client menu from the post-booking CTA."""
    await callback.answer()
    await clear_state_preserving_admin_mode(state)
    if callback.message is not None:
        await show_client_menu(
            callback.message,
            db_session=db_session,
            user=user,
            replace_current=True,
        )


@router.callback_query(F.data == "client:to_my_bookings")
async def post_booking_to_my_bookings(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Legacy alias for older post-booking messages that still target `Мои записи`."""
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


@router.callback_query(StateFilter(BookingStates.confirm), F.data == "booking:confirm")
async def finalize_booking(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Atomically confirm the booking and notify the client and admins."""
    await callback.answer()
    if callback.message is None:
        return

    data = await state.get_data()
    button_configs = await load_runtime_button_configs(db_session)
    finalize_result = await finalize_direct_booking_attempt(
        db_session,
        slot_id=int(data["slot_id"]),
        base_service_id=int(data["base_service_id"]),
        user=user,
        addon_ids=list(data.get("selected_addons", [])),
        design_photos=list(data.get("design_photos", [])),
        design_comment=data.get("design_comment"),
        payment_method=data.get("payment_method"),
        settings=settings,
    )
    attempt = finalize_result.attempt
    if attempt.outcome == "blocked":
        await replace_inline_message_panel(
            callback.message,
            text=texts.BOOKING_BLOCKED_TEXT,
            reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
        )
        await clear_state_preserving_admin_mode(state)
        return

    if attempt.outcome == "shadow_banned":
        slot = await SlotRepository(db_session).get_by_id(int(data["slot_id"]))
        service = await ServiceRepository(db_session).get_by_id(int(data["base_service_id"]))
        if slot is None or service is None:
            await show_day_step(
                callback.message,
                db_session=db_session,
                state=state,
                prefix_text=texts.BOOKING_CONFIRM_SLOT_TAKEN_TEXT,
                settings=settings,
                replace=True,
            )
            return
        await send_booking_success_message(
            callback.message,
            db_session=db_session,
            user=user,
            settings=settings,
            start_at=slot.start_at,
            base_service_name=service.name,
            payment_method=data.get("payment_method"),
            replace_current=True,
        )
        await clear_state_preserving_admin_mode(state)
        return

    if attempt.outcome == "cooldown":
        cooldown_text = render_booking_cooldown_text(attempt.cooldown_minutes)
        selected_day_value = data.get("selected_day")
        if selected_day_value:
            await show_time_step(
                callback.message,
                db_session=db_session,
                state=state,
                local_day=date.fromisoformat(selected_day_value),
                settings=settings,
                prefix_text=cooldown_text,
                replace=True,
            )
            return
        await show_day_step(
            callback.message,
            db_session=db_session,
            state=state,
            prefix_text=cooldown_text,
            settings=settings,
            replace=True,
        )
        return

    if attempt.outcome == "attempt_limit":
        selected_day_value = data.get("selected_day")
        if selected_day_value:
            await show_time_step(
                callback.message,
                db_session=db_session,
                state=state,
                local_day=date.fromisoformat(selected_day_value),
                settings=settings,
                prefix_text=texts.BOOKING_ATTEMPT_LIMIT_TEXT,
                replace=True,
            )
            return
        await show_day_step(
            callback.message,
            db_session=db_session,
            state=state,
            prefix_text=texts.BOOKING_ATTEMPT_LIMIT_TEXT,
            settings=settings,
            replace=True,
        )
        return

    if attempt.outcome == "active_limit":
        await replace_inline_message_panel(
            callback.message,
            text=texts.BOOKING_ACTIVE_LIMIT_TEXT,
            reply_markup=build_booking_action_result_keyboard(button_configs=button_configs),
        )
        await clear_state_preserving_admin_mode(state)
        return

    if attempt.outcome == "pending_limit":
        await replace_inline_message_panel(
            callback.message,
            text=texts.BOOKING_PENDING_APPROVALS_LIMIT_TEXT,
            reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
        )
        await clear_state_preserving_admin_mode(state)
        return

    if attempt.approval is not None:
        user.repeat_prompt_snoozed_until = None
        await db_session.commit()
        if attempt.outcome != "approval_existing":
            await send_approval_card_to_admins(
                bot=callback.bot,
                settings=settings,
                db_session=db_session,
                approval=attempt.approval,
            )
        await replace_inline_message_panel(
            callback.message,
            text=approval_sent_text(attempt.approval.kind),
            reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
        )
        await clear_state_preserving_admin_mode(state)
        return

    result = attempt.confirm_result
    if result is None:
        await show_day_step(
            callback.message,
            db_session=db_session,
            state=state,
            prefix_text=texts.BOOKING_CONFIRM_SLOT_TAKEN_TEXT,
            settings=settings,
            replace=True,
        )
        return

    if not result.ok:
        selected_day_value = data.get("selected_day")
        if selected_day_value:
            await show_time_step(
                callback.message,
                db_session=db_session,
                state=state,
                local_day=date.fromisoformat(selected_day_value),
                settings=settings,
                prefix_text=f"{texts.BOOKING_CONFIRM_SLOT_TAKEN_TEXT}\n\n{texts.BOOKING_CONFIRM_SLOT_TAKEN_FOLLOWUP_TEXT}",
                replace=True,
            )
            return

        await show_day_step(
            callback.message,
            db_session=db_session,
            state=state,
            prefix_text=texts.BOOKING_CONFIRM_SLOT_TAKEN_TEXT,
            settings=settings,
            replace=True,
        )
        return

    completion = finalize_result.completion
    if completion is None:
        await show_day_step(
            callback.message,
            db_session=db_session,
            state=state,
            prefix_text=texts.BOOKING_CONFIRM_SLOT_TAKEN_TEXT,
            settings=settings,
            replace=True,
        )
        return
    if completion.client_confirmation is not None:
        await send_booking_confirmation_message(
            callback.message,
            db_session=db_session,
            settings=settings,
            payload=completion.client_confirmation,
            replace_current=True,
        )

    admin_text = build_admin_booking_text(
        client=user,
        base_service=result.base_service,
        addons=result.addons,
        slot=result.slot,
        tz_name=settings.tz,
        design_photo_count=len(result.booking.design_photos),
        design_comment=result.booking.design_comment,
        fixed_price=result.fixed_price,
        has_variable_price=result.has_variable_price,
        payment_method=result.booking.payment_method,
    )
    if result.booking.design_photos:
        await send_photo_to_admins(
            callback.bot,
            admin_tg_ids=settings.admin_tg_id_set,
            photo=result.booking.design_photos[0],
            caption=admin_text,
            reply_markup=build_open_client_card_keyboard(user.id),
        )
        for extra_photo in result.booking.design_photos[1:3]:
            await send_photo_to_admins(
                callback.bot,
                admin_tg_ids=settings.admin_tg_id_set,
                photo=extra_photo,
            )
    else:
        await send_text_to_admins(
            callback.bot,
            admin_tg_ids=settings.admin_tg_id_set,
            text=admin_text,
            reply_markup=build_open_client_card_keyboard(user.id),
        )

    await clear_state_preserving_admin_mode(state)


# ---------------------------------------------------------------------------
# Post-booking reference upload flow
# ---------------------------------------------------------------------------


async def _show_post_reference_progress(
    message: Message,
    *,
    db_session: AsyncSession,
    state: FSMContext,
    replace: bool = False,
) -> None:
    """Show reference-upload progress while staying in PostBookingReference.upload state."""
    data = await state.get_data()
    button_configs = await load_runtime_button_configs(db_session)
    design_photos = list(data.get("design_photos", []))
    design_comment = data.get("design_comment")
    progress_text = build_reference_progress_text(len(design_photos), design_comment)
    reply_markup = build_reference_actions_keyboard(
        can_finish=bool(design_photos or design_comment),
        has_photos=bool(design_photos),
        can_add_more=len(design_photos) < 5,
        button_configs=button_configs,
    )
    if replace:
        await replace_inline_message_text(message, progress_text, reply_markup=reply_markup)
    else:
        await message.answer(progress_text, reply_markup=reply_markup)


@router.callback_query(F.data.startswith("client:post_reference:"))
async def post_reference_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Enter the post-booking reference upload mode."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    booking_id = int(callback.data.rsplit(":", 1)[-1])
    await state.set_state(PostBookingReference.upload)
    await state.update_data(
        post_booking_id=booking_id,
        design_photos=[],
        design_comment=None,
        reference_comment_requested=False,
    )
    await replace_inline_message_text(
        callback.message,
        texts.BOOKING_REFERENCE_PROMPT_TEXT,
        reply_markup=build_reference_prompt_keyboard(),
    )


@router.callback_query(StateFilter(PostBookingReference.upload), F.data == "booking:attach_photo")
async def post_reference_attach_photo(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Switch to photo-receiving mode inside the post-booking reference flow."""
    await callback.answer()
    if callback.message is None:
        return
    await _show_post_reference_progress(
        callback.message,
        db_session=db_session,
        state=state,
        replace=True,
    )


@router.callback_query(StateFilter(PostBookingReference.upload), F.data == "booking:skip_reference")
async def post_reference_skip(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Skip reference upload and close the post-booking flow."""
    await callback.answer()
    await clear_state_preserving_admin_mode(state)
    if callback.message is not None:
        await replace_inline_message_text(callback.message, texts.POST_BOOKING_MENU_BUTTON_TEXT)


@router.message(StateFilter(PostBookingReference.upload), F.photo)
async def post_reference_receive_photo(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Accept a reference photo in the post-booking flow."""
    data = await state.get_data()
    photos = list(data.get("design_photos", []))
    if len(photos) >= 5:
        button_configs = await load_runtime_button_configs(db_session)
        await message.answer(
            texts.BOOKING_REFERENCE_LIMIT_TEXT,
            reply_markup=build_reference_actions_keyboard(
                can_finish=True,
                has_photos=True,
                can_add_more=False,
                button_configs=button_configs,
            ),
        )
        return
    photos.append(message.photo[-1].file_id)
    await state.update_data(design_photos=photos)
    await _show_post_reference_progress(message, db_session=db_session, state=state)


@router.callback_query(StateFilter(PostBookingReference.upload), F.data == "booking:add_comment")
async def post_reference_request_comment(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Prompt for a text comment in the post-booking reference flow."""
    await callback.answer()
    await state.update_data(reference_comment_requested=True)
    if callback.message is not None:
        await callback.message.answer(texts.BOOKING_REFERENCE_COMMENT_INPUT_TEXT)


@router.message(StateFilter(PostBookingReference.upload), F.text)
async def post_reference_receive_comment(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Save the text comment in the post-booking reference flow."""
    data = await state.get_data()
    if not data.get("reference_comment_requested"):
        return
    await state.update_data(design_comment=message.text, reference_comment_requested=False)
    await message.answer(texts.BOOKING_REFERENCE_COMMENT_SAVED_TEXT)
    await _show_post_reference_progress(message, db_session=db_session, state=state)


@router.callback_query(
    StateFilter(PostBookingReference.upload), F.data == "booking:reference_remove_last"
)
async def post_reference_remove_last(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Remove the last reference photo in the post-booking flow."""
    await callback.answer()
    if callback.message is None:
        return
    data = await state.get_data()
    photos = list(data.get("design_photos", []))
    if photos:
        photos.pop()
    await state.update_data(design_photos=photos)
    if not photos and not data.get("design_comment"):
        await replace_inline_message_text(
            callback.message,
            texts.BOOKING_REFERENCE_PROMPT_TEXT,
            reply_markup=build_reference_prompt_keyboard(),
        )
        return
    await _show_post_reference_progress(
        callback.message,
        db_session=db_session,
        state=state,
        replace=True,
    )


@router.callback_query(StateFilter(PostBookingReference.upload), F.data == "booking:reference_done")
async def post_reference_done(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Save reference photos to the existing booking and finish the flow."""
    await callback.answer()
    if callback.message is None:
        return
    data = await state.get_data()
    booking_id = int(data.get("post_booking_id", 0))
    photos = list(data.get("design_photos", []))
    comment = data.get("design_comment")
    if booking_id:
        await BookingRepository(db_session).attach_design_photos(
            booking_id, user.id, photos, comment
        )
        await db_session.commit()
    await clear_state_preserving_admin_mode(state)
    button_configs = await load_runtime_button_configs(db_session)
    await replace_inline_message_text(
        callback.message,
        texts.BOOKING_POST_REFERENCE_DONE_TEXT,
        reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
    )
