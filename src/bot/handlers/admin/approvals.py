from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import (
    clear_state_preserving_admin_panel,
    remember_admin_panel,
    send_admin_panel,
)
from src.bot.handlers.admin.clients import show_client_card
from src.bot.handlers.client.address import build_address_text  # noqa: F401
from src.bot.handlers.client.booking_confirmation import send_booking_confirmation_bot_message
from src.bot.keyboards.admin import (
    build_admin_approval_actions_keyboard,
    build_admin_approval_slot_keyboard,
    build_admin_approvals_list_keyboard,
    build_admin_decline_confirm_keyboard,
    build_admin_decline_reason_keyboard,
    build_admin_proxy_reply_prompt_keyboard,
    build_admin_repair_decline_confirm_keyboard,
    build_admin_repair_warranty_force_keyboard,
)
from src.bot.keyboards.client import build_offered_time_keyboard
from src.bot.slot_picker import (
    order_day_options_by_preference,
    order_slots_by_time_preference,
)
from src.bot.states import AdminRepairOfferCustom, AdminReplying
from src.bot.ui_utils import replace_inline_message_text, upsert_inline_panel
from src.config import Settings
from src.db.models import (
    ApprovalRequest,
    ApprovalRequestKind,
    ApprovalRequestStatus,
    Booking,
    Service,
    User,
    utcnow,
)
from src.db.repositories.approvals import ApprovalRequestRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.slots import SlotRepository
from src.services import admin_approvals as admin_approvals_service
from src.services.aftercare import (
    REPAIR_PAID_SENTINEL,
    REPAIR_WARRANTY_SENTINEL,
    is_repair_mode_selected,
    is_repair_paid_marked,
    is_repair_warranty_marked,
)
from src.services.approvals import (
    build_admin_approval_card_text,
)
from src.services.booking import (
    format_local_datetime,
    format_local_day_label,
    group_slots_by_local_day,
)
from src.services.booking_completion import (
    BookingClientConfirmationPayload,
)
from src.services.calendar_sync import (
    CalendarBookingInfo,
    update_booking_event,
)
from src.services.notifications import send_photo_to_admins, send_text_to_admins
from src.services.runtime_settings import get_int_setting
from src.services.schedule_image import (
    build_schedule_image_pages_data,
    is_schedule_image_enabled,
    render_schedule_image_bytes,
)

router = Router(name="admin_approvals")

logger = logging.getLogger(__name__)

DECLINE_REASON_LABELS = {
    "busy": "Уже занято",
    "physical": "Не успею физически",
    "offday": "Это нерабочий день",
}

_APPROVAL_SLOT_PICKER_PAGE_STATE_KEY = "slot_picker_admin_approval_page"


async def _replace_approval_callback_notice(callback: CallbackQuery, text: str) -> None:
    """Replace the current approval card with a short final notice."""
    if callback.message is None:
        return
    await replace_inline_message_text(callback.message, text)


async def _show_pending_approvals_or_notice(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    state: FSMContext | None,
    settings: Settings | None,
    notice_text: str,
) -> None:
    """Prefer refreshing the queue; fall back to updating the current callback card."""
    if callback.message is None:
        return
    if state is not None and settings is not None:
        await show_pending_approvals(
            callback.message,
            db_session=db_session,
            is_admin=True,
            settings=settings,
            state=state,
            edit=True,
            notice_text=notice_text,
        )
        return
    await replace_inline_message_text(callback.message, notice_text)


@dataclass(slots=True)
class ApprovalSlotResolutionResult:
    """Domain result of resolving one approval against a concrete slot."""

    ok: bool
    reason: str | None = None
    start_at: datetime | None = None
    base_service_name: str | None = None
    client_confirmation: BookingClientConfirmationPayload | None = None


def render_approval_queue_label(approval: ApprovalRequest) -> str:
    """Render one compact approval label for the queue list."""
    kind_label = {
        ApprovalRequestKind.NEW_BOOKING: "новая запись",
        ApprovalRequestKind.RESCHEDULE: "перенос",
        ApprovalRequestKind.QUESTION: "вопрос",
        ApprovalRequestKind.FREQUENT_BOOKING: "частая запись",
        ApprovalRequestKind.LATE_RESCHEDULE: "поздний перенос",
        ApprovalRequestKind.MANUAL_APPROVAL_REQUIRED: "ручное подтверждение",
        ApprovalRequestKind.REPAIR_REQUEST: "ремонт",
    }[approval.kind]
    name = approval.client.display_name if approval.client else f"#{approval.client_id}"
    return f"{name} · {kind_label}"


def _approval_mode_token(*, offer_mode: bool) -> str:
    """Return the compact callback token for one approval slot-picker mode."""
    return "offer" if offer_mode else "book"


def _approval_offer_mode_from_token(mode_token: str) -> bool:
    """Return whether the admin slot-picker is in offer mode."""
    return mode_token == "offer"


def _build_approval_back_keyboard(approval_id: int) -> InlineKeyboardMarkup:
    """Build the smallest back-to-request keyboard for approval slot pickers."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ К запросу",
                    callback_data=f"admin_approvals:open:{approval_id}",
                )
            ]
        ]
    )


def _build_approval_day_keyboard(
    approval_id: int,
    *,
    day_options,
    mode_token: str,
) -> InlineKeyboardMarkup:
    """Build the plain day keyboard for one approval slot picker."""
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(day_options), 2):
        current_row = [
            InlineKeyboardButton(
                text=day_option.label,
                callback_data=(
                    f"approval:pick_day:{approval_id}:{mode_token}:{day_option.local_date.isoformat()}"
                ),
            )
            for day_option in day_options[index : index + 2]
        ]
        rows.append(current_row)
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ К запросу",
                callback_data=f"admin_approvals:open:{approval_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_approval_schedule_day_keyboard(
    approval_id: int,
    *,
    day_options,
    mode_token: str,
    current_page: int,
    total_pages: int,
) -> InlineKeyboardMarkup:
    """Build the paginated day keyboard for the approval schedule-image picker."""
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(day_options), 2):
        current_row = [
            InlineKeyboardButton(
                text=day_option.label,
                callback_data=(
                    f"approval:pick_day:{approval_id}:{mode_token}:{day_option.local_date.isoformat()}"
                ),
            )
            for day_option in day_options[index : index + 2]
        ]
        rows.append(current_row)

    if total_pages > 1:
        nav_row: list[InlineKeyboardButton] = []
        if current_page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="⬅️",
                    callback_data=(
                        f"approval:pick_page:{approval_id}:{mode_token}:{current_page - 1}"
                    ),
                )
            )
        nav_row.append(
            InlineKeyboardButton(
                text=f"Стр. {current_page + 1}/{total_pages}",
                callback_data="approval:pick_page_noop",
            )
        )
        if current_page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="➡️",
                    callback_data=(
                        f"approval:pick_page:{approval_id}:{mode_token}:{current_page + 1}"
                    ),
                )
            )
        rows.append(nav_row)

    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ К запросу",
                callback_data=f"admin_approvals:open:{approval_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_approval_time_keyboard(
    approval_id: int,
    *,
    slots,
    tz_name: str,
    local_day: date,
    mode_token: str,
    custom_offer_callback: str | None = None,
) -> InlineKeyboardMarkup:
    """Build the concrete time picker for one selected approval day."""
    slot_callback_prefix = "approval:offer_slot" if mode_token == "offer" else "approval:book_slot"
    rows: list[list[InlineKeyboardButton]] = []
    time_buttons = [
        InlineKeyboardButton(
            text=format_local_datetime(slot.start_at, tz_name).strftime("%H:%M"),
            callback_data=f"{slot_callback_prefix}:{approval_id}:{slot.id}",
        )
        for slot in slots
    ]
    for index in range(0, len(time_buttons), 3):
        rows.append(time_buttons[index : index + 3])

    if custom_offer_callback:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🕰 Предложить своё время",
                    callback_data=custom_offer_callback,
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ К дням",
                callback_data=(
                    f"approval:pick_days_back:{approval_id}:{mode_token}:{local_day.isoformat()}"
                ),
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️ К запросу",
                callback_data=f"admin_approvals:open:{approval_id}",
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _approval_day_prompt(*, offer_mode: bool) -> str:
    """Return the approval day-picker prompt."""
    return (
        texts.ADMIN_APPROVAL_OFFER_DAY_TEXT
        if offer_mode
        else texts.ADMIN_APPROVAL_CONFIRM_DAY_TEXT
    )


def _approval_time_prompt(local_day: date) -> str:
    """Return the approval time-picker prompt for one local day."""
    return texts.ADMIN_APPROVAL_CHOOSE_TIME_TEXT.format(
        date=format_local_day_label(local_day),
    )


async def _show_approval_day_picker(
    message: Message,
    *,
    bot,
    state: FSMContext | None,
    approval: ApprovalRequest,
    db_session: AsyncSession,
    settings: Settings,
    offer_mode: bool,
    image_page: int | None = None,
    focus_day: date | None = None,
    prefix_text: str | None = None,
) -> None:
    """Render the shared day picker for admin approval confirm/offer flows."""
    slot_repository = SlotRepository(db_session)
    slots = await slot_repository.list_free_future()
    day_options = order_day_options_by_preference(
        group_slots_by_local_day(slots, settings.tz),
        approval.client.preferred_days_note if approval.client is not None else None,
    )

    prompt_text = _approval_day_prompt(offer_mode=offer_mode)
    if prefix_text:
        prompt_text = f"{prefix_text}\n\n{prompt_text}"

    if not day_options:
        panel = await upsert_inline_panel(
            bot,
            chat_id=message.chat.id,
            message_id=message.message_id,
            text="Свободных окошек сейчас нет 🤍",
            reply_markup=_build_approval_back_keyboard(approval.id),
        )
        if state is not None:
            await remember_admin_panel(state, panel)
        return

    if await is_schedule_image_enabled(db_session):
        try:
            send_chat_action = getattr(bot, "send_chat_action", None)
            if send_chat_action is not None:
                await send_chat_action(chat_id=message.chat.id, action="upload_photo")
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
            elif state is not None:
                state_data = await state.get_data()
                stored_page = state_data.get(_APPROVAL_SLOT_PICKER_PAGE_STATE_KEY)
                if isinstance(stored_page, int):
                    current_index = max(0, min(stored_page, len(image_pages) - 1))
                elif isinstance(stored_page, str) and stored_page.isdigit():
                    current_index = max(0, min(int(stored_page), len(image_pages) - 1))
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
            if state is not None:
                await state.update_data(
                    **{_APPROVAL_SLOT_PICKER_PAGE_STATE_KEY: current_index}
                )
            photo_bytes = render_schedule_image_bytes(
                current_page.entries,
                period=current_page.period,
                caption=current_page.caption,
                page_number=current_page.page_number,
                total_pages=current_page.total_pages,
            )
            panel = await upsert_inline_panel(
                bot,
                chat_id=message.chat.id,
                message_id=message.message_id,
                text=prompt_text,
                photo_bytes=photo_bytes,
                filename="approval-schedule.png",
                caption=prompt_text,
                reply_markup=_build_approval_schedule_day_keyboard(
                    approval.id,
                    day_options=visible_day_options,
                    mode_token=_approval_mode_token(offer_mode=offer_mode),
                    current_page=current_index,
                    total_pages=current_page.total_pages,
                ),
            )
            if state is not None:
                await remember_admin_panel(state, panel)
            return

    panel = await upsert_inline_panel(
        bot,
        chat_id=message.chat.id,
        message_id=message.message_id,
        text=prompt_text,
        reply_markup=_build_approval_day_keyboard(
            approval.id,
            day_options=day_options,
            mode_token=_approval_mode_token(offer_mode=offer_mode),
        ),
    )
    if state is not None:
        await remember_admin_panel(state, panel)


async def _show_approval_time_picker(
    message: Message,
    *,
    bot,
    state: FSMContext | None,
    approval: ApprovalRequest,
    local_day: date,
    db_session: AsyncSession,
    settings: Settings,
    offer_mode: bool,
) -> None:
    """Render the concrete time-picker after the admin chooses one day."""
    slot_repository = SlotRepository(db_session)
    slots = await slot_repository.list_free_for_local_day(local_day=local_day, tz_name=settings.tz)
    slots = order_slots_by_time_preference(
        slots,
        approval.client.preferred_time_note if approval.client is not None else None,
        tz_name=settings.tz,
    )
    if not slots:
        await _show_approval_day_picker(
            message,
            bot=bot,
            state=state,
            approval=approval,
            db_session=db_session,
            settings=settings,
            offer_mode=offer_mode,
            focus_day=local_day,
            prefix_text="На этот день свободных окошек уже нет 🤍",
        )
        return

    custom_offer_callback = (
        f"approval:repair_offer_custom:{approval.id}"
        if offer_mode and approval.kind == ApprovalRequestKind.REPAIR_REQUEST
        else None
    )
    panel = await upsert_inline_panel(
        bot,
        chat_id=message.chat.id,
        message_id=message.message_id,
        text=_approval_time_prompt(local_day),
        reply_markup=_build_approval_time_keyboard(
            approval.id,
            slots=slots,
            tz_name=settings.tz,
            local_day=local_day,
            mode_token=_approval_mode_token(offer_mode=offer_mode),
            custom_offer_callback=custom_offer_callback,
        ),
    )
    if state is not None:
        await remember_admin_panel(state, panel)


async def render_approval_detail_text(
    approval: ApprovalRequest,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> str:
    """Render one approval detail card."""
    base_service, addons = await load_approval_service_context(db_session, approval)
    settings_repository = SettingRepository(db_session)
    return build_admin_approval_card_text(
        approval=approval,
        client=approval.client,
        base_service=base_service,
        addons=addons,
        tz_name=settings.tz,
        warranty_days=await get_int_setting(
            settings_repository,
            key="repair_warranty_days",
            default=14,
        ),
        warranty_nails_limit=await get_int_setting(
            settings_repository,
            key="repair_warranty_nails_limit",
            default=2,
        ),
    )


async def load_approval_service_context(
    db_session: AsyncSession,
    approval: ApprovalRequest,
) -> tuple[Service | None, list[Service]]:
    """Load the base service and add-ons used in an approval card."""
    return await admin_approvals_service.load_approval_service_context(
        db_session,
        approval,
    )


def extract_direct_confirmation_start_at(
    approval: ApprovalRequest,
    *,
    tz_name: str,
) -> datetime | None:
    """Return the exact requested datetime when it can be confirmed directly."""
    return admin_approvals_service.extract_direct_confirmation_start_at(
        approval,
        tz_name=tz_name,
    )


async def resolve_decline_reason_text(
    *,
    db_session: AsyncSession,
    reason_code: str,
) -> str:
    """Resolve a canned decline code into the final client-facing reason."""
    return await admin_approvals_service.resolve_decline_reason_text(
        db_session=db_session,
        reason_code=reason_code,
    )


async def commit_decline_request(
    *,
    approval: ApprovalRequest,
    reason: str,
    db_session: AsyncSession,
    bot,
) -> None:
    """Persist one standard decline and notify the client."""
    await admin_approvals_service.commit_decline_request(
        approval=approval,
        reason=reason,
        db_session=db_session,
        bot=bot,
    )


async def commit_repair_decline_request(
    *,
    approval: ApprovalRequest,
    db_session: AsyncSession,
    bot,
) -> None:
    """Persist a repair decline and notify the client with the template copy."""
    await admin_approvals_service.commit_repair_decline_request(
        approval=approval,
        db_session=db_session,
        bot=bot,
    )


async def create_or_get_exact_slot_id(
    *,
    approval: ApprovalRequest,
    db_session: AsyncSession,
    settings: Settings,
) -> int | None:
    """Create or reuse the exact requested slot and return its id."""
    return await admin_approvals_service.create_or_get_exact_slot_id(
        approval=approval,
        db_session=db_session,
        tz_name=settings.tz,
    )


async def send_approval_card_to_admins(
    *,
    bot,
    settings: Settings,
    db_session: AsyncSession,
    approval: ApprovalRequest,
) -> None:
    """Send a pending approval card to every configured admin."""
    approval_text = await render_approval_detail_text(
        approval,
        db_session=db_session,
        settings=settings,
    )
    reply_markup = build_admin_approval_actions_keyboard(
        approval_id=approval.id,
        kind=approval.kind,
        can_direct_confirm=extract_direct_confirmation_start_at(approval, tz_name=settings.tz)
        is not None,
        repair_warranty_marked=is_repair_warranty_marked(approval),
        repair_paid_marked=is_repair_paid_marked(approval),
    )

    if approval.design_photos:
        await send_photo_to_admins(
            bot,
            admin_tg_ids=settings.admin_tg_id_set,
            photo=approval.design_photos[0],
            caption=approval_text,
            reply_markup=reply_markup,
        )
        for extra_photo in approval.design_photos[1:]:
            await send_photo_to_admins(
                bot,
                admin_tg_ids=settings.admin_tg_id_set,
                photo=extra_photo,
            )
        return

    await send_text_to_admins(
        bot,
        admin_tg_ids=settings.admin_tg_id_set,
        text=approval_text,
        reply_markup=reply_markup,
    )


def build_calendar_booking_info_from_request(
    *,
    booking: Booking,
    client: User,
    addons: list[Service],
) -> CalendarBookingInfo:
    """Build the calendar payload after manual approval."""
    return admin_approvals_service.build_calendar_booking_info_from_request(
        booking=booking,
        client=client,
        addons=addons,
    )


async def show_pending_approvals(
    message: Message,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
    state: FSMContext | None = None,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Render the admin pending-requests queue."""
    if not is_admin:
        return

    repository = ApprovalRequestRepository(db_session)
    approvals = await repository.list_pending()
    if not approvals:
        text = texts.ADMIN_APPROVALS_EMPTY_TEXT
        reply_markup = None
        if notice_text:
            text = f"{notice_text}\n\n{text}"
        if state is not None:
            await send_admin_panel(message, state, text=text, reply_markup=reply_markup)
            return
        if edit:
            await replace_inline_message_text(message, text, reply_markup=reply_markup)
            return
        await message.answer(text)
        return

    text = texts.ADMIN_APPROVALS_HEADER_TEXT
    if notice_text:
        text = f"{notice_text}\n\n{text}"
    reply_markup = build_admin_approvals_list_keyboard(
        [(approval.id, render_approval_queue_label(approval)) for approval in approvals]
    )
    if state is not None:
        await send_admin_panel(message, state, text=text, reply_markup=reply_markup)
        return
    if edit:
        await replace_inline_message_text(message, text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


async def show_approval_detail(
    message: Message,
    *,
    approval_id: int,
    db_session: AsyncSession,
    settings: Settings,
    state: FSMContext | None = None,
    edit: bool = False,
    notice_text: str | None = None,
) -> None:
    """Open one pending approval in the shared panel."""
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await show_pending_approvals(
            message,
            db_session=db_session,
            is_admin=True,
            settings=settings,
            state=state,
            edit=edit,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    text = await render_approval_detail_text(approval, db_session=db_session, settings=settings)
    if notice_text:
        text = f"{notice_text}\n\n{text}"
    reply_markup = build_admin_approval_actions_keyboard(
        approval_id=approval.id,
        kind=approval.kind,
        can_direct_confirm=extract_direct_confirmation_start_at(approval, tz_name=settings.tz)
        is not None,
        include_back=True,
        repair_warranty_marked=is_repair_warranty_marked(approval),
        repair_paid_marked=is_repair_paid_marked(approval),
    )
    if state is not None:
        await send_admin_panel(message, state, text=text, reply_markup=reply_markup)
        return
    if edit:
        await replace_inline_message_text(message, text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


async def open_slot_picker(
    callback: CallbackQuery,
    state: FSMContext | None = None,
    *,
    approval: ApprovalRequest,
    db_session: AsyncSession,
    settings: Settings,
    prompt_text: str = texts.ADMIN_APPROVAL_CONFIRM_TEXT,
    offer_mode: bool = False,
) -> None:
    """Show the slot picker for a pending approval request.

    When *offer_mode* is True the picked slot triggers a client-side
    confirmation request (``approval:offer_slot``) instead of an immediate
    booking (``approval:book_slot``).
    """
    if callback.message is None:
        return

    if state is not None:
        await _show_approval_day_picker(
            callback.message,
            bot=callback.bot,
            state=state,
            approval=approval,
            db_session=db_session,
            settings=settings,
            offer_mode=offer_mode,
        )
        return

    slot_repository = SlotRepository(db_session)
    slots = await slot_repository.list_free_future()

    panel = await upsert_inline_panel(
        callback.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=prompt_text,
        reply_markup=build_admin_approval_slot_keyboard(
            approval_id=approval.id,
            slots=slots,
            tz_name=settings.tz,
            include_back=True,
            slot_callback_prefix="approval:offer_slot" if offer_mode else "approval:book_slot",
            custom_offer_callback=(
                f"approval:repair_offer_custom:{approval.id}"
                if offer_mode and approval.kind == ApprovalRequestKind.REPAIR_REQUEST
                else None
            ),
        ),
    )
    if state is not None:
        await remember_admin_panel(state, panel)


async def resolve_with_slot(
    *,
    callback: CallbackQuery,
    state: FSMContext | None = None,
    approval: ApprovalRequest,
    slot_id: int,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Confirm an approval request by attaching it to a concrete slot."""
    if callback.message is None:
        return

    result = await finalize_approval_with_slot(
        approval=approval,
        slot_id=slot_id,
        db_session=db_session,
        settings=settings,
    )
    if not result.ok:
        await show_approval_detail(
            callback.message,
            approval_id=approval.id,
            db_session=db_session,
            settings=settings,
            state=state,
            edit=True,
            notice_text=(
                texts.ADMIN_APPROVAL_CONFIRM_FAILED_TEXT
                if result.reason == "confirm_failed"
                else texts.ADMIN_APPROVAL_SLOT_UNAVAILABLE_TEXT
            ),
        )
        return

    await send_client_approval_confirmation(
        bot=callback.bot,
        db_session=db_session,
        settings=settings,
        client_confirmation=result.client_confirmation,
    )
    if state is not None:
        await show_pending_approvals(
            callback.message,
            db_session=db_session,
            is_admin=True,
            settings=settings,
            state=state,
            edit=True,
            notice_text=texts.ADMIN_APPROVAL_PROCESSED_TEXT,
        )
    else:
        await _replace_approval_callback_notice(callback, texts.ADMIN_APPROVAL_PROCESSED_TEXT)


async def finalize_approval_with_slot(
    *,
    approval: ApprovalRequest,
    slot_id: int,
    db_session: AsyncSession,
    settings: Settings,
) -> ApprovalSlotResolutionResult:
    """Resolve one approval against a concrete slot using the shared business path."""
    return await admin_approvals_service.finalize_approval_with_slot(
        approval=approval,
        slot_id=slot_id,
        db_session=db_session,
        settings=settings,
        calendar_event_updater=update_booking_event,
    )


async def send_client_approval_confirmation(
    *,
    bot,
    db_session: AsyncSession,
    settings: Settings,
    client_confirmation: BookingClientConfirmationPayload | None,
) -> None:
    """Send the standard approved-booking confirmation to the client."""
    if client_confirmation is None:
        return
    await send_booking_confirmation_bot_message(
        bot,
        db_session=db_session,
        settings=settings,
        payload=client_confirmation,
    )


async def render_client_offer_text(
    *,
    approval: ApprovalRequest,
    start_at: datetime,
    db_session: AsyncSession,
    settings: Settings,
) -> str:
    """Render the client-facing offer text for standard or repair requests."""
    return await admin_approvals_service.render_client_offer_text(
        approval=approval,
        start_at=start_at,
        db_session=db_session,
        settings=settings,
    )


def parse_custom_offer_start_at(raw_text: str, *, tz_name: str) -> datetime | None:
    """Parse one custom off-schedule offer datetime from admin input."""
    return admin_approvals_service.parse_custom_offer_start_at(
        raw_text,
        tz_name=tz_name,
    )


@router.message(lambda message: bool(message.text) and message.text.startswith("📥 Запросы ("))
async def approvals_queue(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the pending-approval queue from the admin menu."""
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await show_pending_approvals(
        message,
        db_session=db_session,
        is_admin=is_admin,
        settings=settings,
        state=state,
    )


@router.callback_query(F.data == "admin_approvals:home")
async def approvals_queue_home(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Return to the approvals queue list."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    if callback.message is not None:
        await show_pending_approvals(
            callback.message,
            db_session=db_session,
            is_admin=is_admin,
            settings=settings,
            state=state,
            edit=True,
        )


@router.callback_query(F.data.startswith("admin_approvals:open:"))
async def open_approval_detail_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open one request from the queue list."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    approval_id = int(callback.data.rsplit(":", 1)[-1])
    await show_approval_detail(
        callback.message,
        approval_id=approval_id,
        db_session=db_session,
        settings=settings,
        state=state,
        edit=True,
    )


@router.callback_query(F.data.startswith("approval:confirm:"))
async def confirm_request(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Confirm directly when possible, otherwise open the slot picker."""
    await callback.answer()
    if not is_admin or callback.data is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        if callback.message is not None:
            await _replace_approval_callback_notice(
                callback,
                texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
            )
        return

    exact_slot_id = await create_or_get_exact_slot_id(
        approval=approval,
        db_session=db_session,
        settings=settings,
    )
    if exact_slot_id is not None:
        await resolve_with_slot(
            callback=callback,
            state=state,
            approval=approval,
            slot_id=exact_slot_id,
            db_session=db_session,
            settings=settings,
        )
        return

    await open_slot_picker(
        callback,
        state=state,
        approval=approval,
        db_session=db_session,
        settings=settings,
    )


@router.callback_query(F.data.startswith("approval:offer_time:"))
async def offer_alternative_time(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the slot picker for offering an alternative time."""
    await callback.answer()
    if not is_admin or callback.data is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        if callback.message is not None:
            await _replace_approval_callback_notice(
                callback,
                texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
            )
        return
    if approval.kind == ApprovalRequestKind.REPAIR_REQUEST and not is_repair_mode_selected(
        approval
    ):
        if callback.message is not None:
            await show_approval_detail(
                callback.message,
                approval_id=approval.id,
                db_session=db_session,
                settings=settings,
                state=state,
                edit=True,
                notice_text=texts.ADMIN_REPAIR_ACCEPTANCE_REQUIRED_TEXT,
            )
        return

    await open_slot_picker(
        callback,
        state=state,
        approval=approval,
        db_session=db_session,
        settings=settings,
        prompt_text=texts.ADMIN_APPROVAL_OFFER_TIME_TEXT,
        offer_mode=True,
    )


@router.callback_query(F.data.startswith("approval:pick_page:"))
async def change_approval_slot_picker_page(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Flip one schedule-image page inside the admin approval day picker."""
    await callback.answer()
    if not is_admin or callback.data is None or callback.message is None:
        return

    _, _, approval_id_str, mode_token, page_str = callback.data.split(":", 4)
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(int(approval_id_str))
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await show_pending_approvals(
            callback.message,
            db_session=db_session,
            is_admin=True,
            settings=settings,
            state=state,
            edit=True,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    await _show_approval_day_picker(
        callback.message,
        bot=callback.bot,
        state=state,
        approval=approval,
        db_session=db_session,
        settings=settings,
        offer_mode=_approval_offer_mode_from_token(mode_token),
        image_page=int(page_str),
    )


@router.callback_query(F.data == "approval:pick_page_noop")
async def noop_approval_slot_picker_page(callback: CallbackQuery) -> None:
    """Acknowledge the inert schedule-page label button."""
    await callback.answer()


@router.callback_query(F.data.startswith("approval:pick_day:"))
async def choose_approval_slot_picker_day(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the concrete time list for one selected day in approvals."""
    await callback.answer()
    if not is_admin or callback.data is None or callback.message is None:
        return

    _, _, approval_id_str, mode_token, local_day_str = callback.data.split(":", 4)
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(int(approval_id_str))
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await show_pending_approvals(
            callback.message,
            db_session=db_session,
            is_admin=True,
            settings=settings,
            state=state,
            edit=True,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    await _show_approval_time_picker(
        callback.message,
        bot=callback.bot,
        state=state,
        approval=approval,
        local_day=date.fromisoformat(local_day_str),
        db_session=db_session,
        settings=settings,
        offer_mode=_approval_offer_mode_from_token(mode_token),
    )


@router.callback_query(F.data.startswith("approval:pick_days_back:"))
async def back_to_approval_slot_picker_days(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Return from approval time buttons back to the paginated day picker."""
    await callback.answer()
    if not is_admin or callback.data is None or callback.message is None:
        return

    _, _, approval_id_str, mode_token, local_day_str = callback.data.split(":", 4)
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(int(approval_id_str))
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await show_pending_approvals(
            callback.message,
            db_session=db_session,
            is_admin=True,
            settings=settings,
            state=state,
            edit=True,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    await _show_approval_day_picker(
        callback.message,
        bot=callback.bot,
        state=state,
        approval=approval,
        db_session=db_session,
        settings=settings,
        offer_mode=_approval_offer_mode_from_token(mode_token),
        focus_day=date.fromisoformat(local_day_str),
    )


@router.callback_query(F.data.startswith("approval:book_slot:"))
async def approve_with_existing_slot(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Approve a request with one of the published free slots."""
    await callback.answer()
    if not is_admin or callback.data is None:
        return

    _, _, approval_id_str, slot_id_str = callback.data.split(":", 3)
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(int(approval_id_str))
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        if callback.message is not None:
            await _replace_approval_callback_notice(
                callback,
                texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
            )
        return

    await resolve_with_slot(
        callback=callback,
        state=state,
        approval=approval,
        slot_id=int(slot_id_str),
        db_session=db_session,
        settings=settings,
    )


@router.callback_query(F.data.startswith("approval:offer_slot:"))
async def offer_slot_to_client(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Send a time-slot offer to the client and await their confirmation."""
    await callback.answer()
    if not is_admin or callback.data is None:
        return

    _, _, approval_id_str, slot_id_str = callback.data.split(":", 3)
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(int(approval_id_str))
    if approval is None or approval.status not in (
        ApprovalRequestStatus.PENDING,
        ApprovalRequestStatus.OFFERED,
    ):
        if callback.message is not None:
            await _replace_approval_callback_notice(
                callback,
                texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
            )
        return
    if approval.kind == ApprovalRequestKind.REPAIR_REQUEST and not is_repair_mode_selected(
        approval
    ):
        if callback.message is not None:
            await show_approval_detail(
                callback.message,
                approval_id=approval.id,
                db_session=db_session,
                settings=settings,
                state=state,
                edit=True,
                notice_text=texts.ADMIN_REPAIR_ACCEPTANCE_REQUIRED_TEXT,
            )
        return

    slot_repository = SlotRepository(db_session)
    slot = await slot_repository.get_by_id(int(slot_id_str))
    if slot is None:
        if callback.message is not None:
            await _replace_approval_callback_notice(
                callback,
                texts.ADMIN_APPROVAL_SLOT_UNAVAILABLE_TEXT,
            )
        return

    # Update approval to OFFERED, store the slot being offered.
    approval.status = ApprovalRequestStatus.OFFERED
    approval.offered_slot_id = slot.id
    approval.offered_start_at = None
    await db_session.commit()

    # Notify client.
    try:
        await callback.bot.send_message(
            chat_id=approval.client.tg_id,
            text=await render_client_offer_text(
                approval=approval,
                start_at=slot.start_at,
                db_session=db_session,
                settings=settings,
            ),
            reply_markup=build_offered_time_keyboard(approval.id),
        )
    except Exception:
        logger.exception("Failed to send time-offer message to client %s", approval.client_id)

    # Acknowledge to admin.
    if callback.message is not None:
        if state is not None:
            await show_pending_approvals(
                callback.message,
                db_session=db_session,
                is_admin=True,
                settings=settings,
                state=state,
                edit=True,
                notice_text=texts.APPROVAL_TIME_OFFER_SENT_ADMIN_TEXT,
            )
        else:
            await _replace_approval_callback_notice(
                callback,
                texts.APPROVAL_TIME_OFFER_SENT_ADMIN_TEXT,
            )


@router.callback_query(F.data.startswith("approval:repair_warranty:"))
async def mark_repair_warranty(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Mark one repair request as warranty-approved."""
    await callback.answer()
    if not is_admin or callback.data is None or callback.message is None:
        return
    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await _replace_approval_callback_notice(callback, texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT)
        return

    nails_limit = await get_int_setting(
        SettingRepository(db_session),
        key="repair_warranty_nails_limit",
        default=2,
    )
    if approval.repair_nails_count is not None and approval.repair_nails_count > nails_limit:
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_REPAIR_WARRANTY_LIMIT_CONFIRM_TEXT.format(nails_limit=nails_limit),
            reply_markup=build_admin_repair_warranty_force_keyboard(approval.id),
        )
        return

    approval.admin_response_text = REPAIR_WARRANTY_SENTINEL
    await db_session.commit()
    await show_approval_detail(
        callback.message,
        approval_id=approval.id,
        db_session=db_session,
        settings=settings,
        state=state,
        edit=True,
        notice_text=texts.ADMIN_REPAIR_WARRANTY_MARKED_TEXT,
    )


@router.callback_query(F.data.startswith("approval:repair_paid:"))
async def mark_repair_paid(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Mark one repair request as accepted in paid mode."""
    await callback.answer()
    if not is_admin or callback.data is None or callback.message is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await _replace_approval_callback_notice(callback, texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT)
        return

    approval.admin_response_text = REPAIR_PAID_SENTINEL
    await db_session.commit()
    await show_approval_detail(
        callback.message,
        approval_id=approval.id,
        db_session=db_session,
        settings=settings,
        state=state,
        edit=True,
        notice_text=texts.ADMIN_REPAIR_PAID_MARKED_TEXT,
    )


@router.callback_query(F.data.startswith("approval:repair_warranty_force:"))
async def mark_repair_warranty_force(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Override the nails-limit warning and mark the repair as warranty-approved."""
    await callback.answer()
    if not is_admin or callback.data is None or callback.message is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await _replace_approval_callback_notice(callback, texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT)
        return

    approval.admin_response_text = REPAIR_WARRANTY_SENTINEL
    await db_session.commit()
    await show_approval_detail(
        callback.message,
        approval_id=approval.id,
        db_session=db_session,
        settings=settings,
        state=state,
        edit=True,
        notice_text=texts.ADMIN_REPAIR_WARRANTY_MARKED_TEXT,
    )


@router.callback_query(F.data.startswith("approval:repair_offer_custom:"))
async def prompt_custom_repair_offer(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Prompt the admin for a custom off-schedule repair time."""
    await callback.answer()
    if not is_admin or callback.data is None or callback.message is None:
        return
    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await _replace_approval_callback_notice(callback, texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT)
        return
    if not is_repair_mode_selected(approval):
        await show_approval_detail(
            callback.message,
            approval_id=approval.id,
            db_session=db_session,
            settings=settings,
            state=state,
            edit=True,
            notice_text=texts.ADMIN_REPAIR_ACCEPTANCE_REQUIRED_TEXT,
        )
        return

    await state.set_state(AdminRepairOfferCustom.input_text)
    await state.update_data(
        admin_repair_offer_approval_id=approval.id,
        admin_repair_offer_panel_chat_id=callback.message.chat.id,
        admin_repair_offer_panel_message_id=callback.message.message_id,
    )
    await replace_inline_message_text(
        callback.message,
        texts.ADMIN_REPAIR_CUSTOM_OFFER_PROMPT_TEXT,
        reply_markup=build_admin_proxy_reply_prompt_keyboard(approval.id),
    )


@router.callback_query(F.data.startswith("approval:book_exact:"))
async def approve_with_exact_requested_slot(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Approve a request by creating or reusing the exact requested slot."""
    await callback.answer()
    if not is_admin or callback.data is None:
        return

    _, _, approval_id_str, code = callback.data.split(":", 3)
    approval_id = int(approval_id_str)
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        if callback.message is not None:
            await _replace_approval_callback_notice(
                callback,
                texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
            )
        return

    local_dt = datetime.strptime(code, "%Y%m%d%H%M").replace(tzinfo=ZoneInfo(settings.tz))
    start_at = local_dt.astimezone(UTC)
    slot_repository = SlotRepository(db_session)
    slot, _ = await slot_repository.create_if_missing(start_at)
    await db_session.commit()

    await resolve_with_slot(
        callback=callback,
        state=state,
        approval=approval,
        slot_id=slot.id,
        db_session=db_session,
        settings=settings,
    )


@router.message(StateFilter(AdminRepairOfferCustom.input_text))
async def submit_custom_repair_offer(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Save and send a custom off-schedule repair offer."""
    data = await state.get_data()
    approval_id = int(data.get("admin_repair_offer_approval_id", 0))
    panel_chat_id = int(data.get("admin_repair_offer_panel_chat_id", 0))
    panel_message_id = int(data.get("admin_repair_offer_panel_message_id", 0))
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await state.clear()
        if panel_chat_id > 0 and panel_message_id > 0:
            await upsert_inline_panel(
                message.bot,
                chat_id=panel_chat_id,
                message_id=panel_message_id,
                text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
            )
        else:
            await message.answer(texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT)
        return

    if not is_repair_mode_selected(approval):
        await state.clear()
        await upsert_inline_panel(
            message.bot,
            chat_id=panel_chat_id,
            message_id=panel_message_id,
            text=await render_approval_detail_text(
                approval,
                db_session=db_session,
                settings=settings,
            ),
            reply_markup=build_admin_approval_actions_keyboard(
                approval_id=approval.id,
                kind=approval.kind,
                repair_warranty_marked=is_repair_warranty_marked(approval),
                repair_paid_marked=is_repair_paid_marked(approval),
                include_back=True,
            ),
        )
        return

    start_at = parse_custom_offer_start_at(message.text or "", tz_name=settings.tz)
    if start_at is None:
        await upsert_inline_panel(
            message.bot,
            chat_id=panel_chat_id,
            message_id=panel_message_id,
            text=texts.ADMIN_REPAIR_CUSTOM_OFFER_INVALID_TEXT,
            reply_markup=build_admin_proxy_reply_prompt_keyboard(approval.id),
        )
        return

    approval.status = ApprovalRequestStatus.OFFERED
    approval.offered_slot_id = None
    approval.offered_start_at = start_at
    await db_session.commit()

    try:
        await message.bot.send_message(
            chat_id=approval.client.tg_id,
            text=await render_client_offer_text(
                approval=approval,
                start_at=start_at,
                db_session=db_session,
                settings=settings,
            ),
            reply_markup=build_offered_time_keyboard(approval.id),
        )
    except Exception:
        logger.exception("Failed to send custom repair offer %s", approval.id)

    await state.clear()
    pending_approvals = await repository.list_pending()
    await upsert_inline_panel(
        message.bot,
        chat_id=panel_chat_id,
        message_id=panel_message_id,
        text=f"{texts.APPROVAL_TIME_OFFER_SENT_ADMIN_TEXT}\n\n{texts.ADMIN_APPROVALS_HEADER_TEXT}",
        reply_markup=build_admin_approvals_list_keyboard(
            [(pending.id, render_approval_queue_label(pending)) for pending in pending_approvals]
        )
        if pending_approvals
        else None,
    )


@router.callback_query(F.data.startswith("approval:client:"))
async def open_approval_client_card(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the client card linked to one approval request."""
    await callback.answer()
    if not is_admin or callback.data is None or callback.message is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None:
        await _replace_approval_callback_notice(callback, texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT)
        return

    await show_client_card(
        callback.message,
        db_session=db_session,
        settings=settings,
        client_id=approval.client_id,
        back_callback=f"admin_approvals:open:{approval.id}",
        edit=True,
    )


@router.callback_query(F.data.startswith("approval:decline:"))
async def decline_request(
    callback: CallbackQuery,
    state: FSMContext | None = None,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Open the decline-reason picker for a request."""
    await callback.answer()
    if not is_admin or callback.message is None or callback.data is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None:
        await _replace_approval_callback_notice(callback, texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT)
        return
    if approval.kind == ApprovalRequestKind.REPAIR_REQUEST:
        panel = await upsert_inline_panel(
            callback.bot,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=texts.ADMIN_REPAIR_DECLINE_CONFIRM_TEXT,
            reply_markup=build_admin_repair_decline_confirm_keyboard(approval.id),
        )
        if state is not None:
            await remember_admin_panel(state, panel)
        return

    panel = await upsert_inline_panel(
        callback.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=texts.ADMIN_APPROVAL_DECLINE_PROMPT_TEXT,
        reply_markup=build_admin_decline_reason_keyboard(approval_id, include_back=True),
    )
    if state is not None:
        await remember_admin_panel(state, panel)


@router.callback_query(F.data.startswith("approval:decline_reason:"))
async def decline_with_template_reason(
    callback: CallbackQuery,
    state: FSMContext | None = None,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings | None = None,
) -> None:
    """Decline a request with one of the predefined reasons."""
    await callback.answer()
    if not is_admin or callback.data is None:
        return

    _, _, approval_id_str, reason_code = callback.data.split(":", 3)
    approval_id = int(approval_id_str)
    reason = await resolve_decline_reason_text(db_session=db_session, reason_code=reason_code)
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await _show_pending_approvals_or_notice(
            callback,
            db_session=db_session,
            state=state,
            settings=settings,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    if callback.message is None:
        return

    panel = await upsert_inline_panel(
        callback.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=texts.ADMIN_APPROVAL_DECLINE_CONFIRM_TEXT.format(reason=reason),
        reply_markup=build_admin_decline_confirm_keyboard(
            approval.id,
            reason_code=reason_code,
        ),
    )
    if state is not None:
        await remember_admin_panel(state, panel)


@router.callback_query(F.data.startswith("approval:decline_commit:"))
async def decline_with_template_reason_commit(
    callback: CallbackQuery,
    state: FSMContext | None = None,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings | None = None,
) -> None:
    """Finalize a canned decline after the explicit confirmation click."""
    await callback.answer()
    if not is_admin or callback.data is None:
        return

    _, _, approval_id_str, reason_code = callback.data.split(":", 3)
    approval_id = int(approval_id_str)
    reason = await resolve_decline_reason_text(db_session=db_session, reason_code=reason_code)
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await _show_pending_approvals_or_notice(
            callback,
            db_session=db_session,
            state=state,
            settings=settings,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    await commit_decline_request(
        approval=approval,
        reason=reason,
        db_session=db_session,
        bot=callback.bot,
    )
    if callback.message is not None:
        if settings is not None and state is not None:
            await show_pending_approvals(
                callback.message,
                db_session=db_session,
                is_admin=True,
                settings=settings,
                state=state,
                edit=True,
                notice_text=texts.ADMIN_APPROVAL_PROCESSED_TEXT,
            )
        else:
            await replace_inline_message_text(
                callback.message,
                texts.ADMIN_APPROVAL_PROCESSED_TEXT,
            )


@router.callback_query(F.data.startswith("approval:decline_custom_commit:"))
async def decline_with_custom_reason_commit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Finalize a free-text decline after the explicit confirmation click."""
    await callback.answer()
    if not is_admin or callback.data is None or callback.message is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    data = await state.get_data()
    reason = str(data.get("decline_pending_reason") or "").strip()
    if not reason:
        panel = await upsert_inline_panel(
            callback.bot,
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=texts.ADMIN_APPROVAL_DECLINE_PROMPT_TEXT,
            reply_markup=build_admin_proxy_reply_prompt_keyboard(approval_id),
        )
        await remember_admin_panel(state, panel)
        await state.set_state(AdminReplying.input_message)
        await state.update_data(admin_action="decline", approval_id=approval_id)
        return

    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await show_pending_approvals(
            callback.message,
            db_session=db_session,
            is_admin=True,
            settings=settings,
            state=state,
            edit=True,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    await commit_decline_request(
        approval=approval,
        reason=reason,
        db_session=db_session,
        bot=callback.bot,
    )
    await clear_state_preserving_admin_panel(state, admin_as_client=False)
    await show_pending_approvals(
        callback.message,
        db_session=db_session,
        is_admin=True,
        settings=settings,
        state=state,
        edit=True,
        notice_text=texts.ADMIN_APPROVAL_PROCESSED_TEXT,
    )


@router.callback_query(F.data.startswith("approval:repair_decline_commit:"))
async def decline_repair_request_commit(
    callback: CallbackQuery,
    state: FSMContext | None = None,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings | None = None,
) -> None:
    """Finalize a repair decline after the explicit confirmation click."""
    await callback.answer()
    if not is_admin or callback.data is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    if approval is None or approval.status != ApprovalRequestStatus.PENDING:
        await _show_pending_approvals_or_notice(
            callback,
            db_session=db_session,
            state=state,
            settings=settings,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    await commit_repair_decline_request(
        approval=approval,
        db_session=db_session,
        bot=callback.bot,
    )
    if callback.message is not None:
        if settings is not None and state is not None:
            await show_pending_approvals(
                callback.message,
                db_session=db_session,
                is_admin=True,
                settings=settings,
                state=state,
                edit=True,
                notice_text=texts.ADMIN_APPROVAL_PROCESSED_TEXT,
            )
        else:
            await replace_inline_message_text(
                callback.message,
                texts.ADMIN_APPROVAL_PROCESSED_TEXT,
            )


@router.callback_query(F.data.startswith("approval:decline_other:"))
async def decline_with_custom_reason(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Switch into free-text decline mode."""
    await callback.answer()
    if not is_admin or callback.message is None or callback.data is None:
        return

    approval_id = int(callback.data.rsplit(":", 1)[1])
    await state.set_state(AdminReplying.input_message)
    await state.update_data(
        admin_action="decline",
        approval_id=approval_id,
        decline_pending_reason=None,
    )
    panel = await upsert_inline_panel(
        callback.bot,
        chat_id=callback.message.chat.id,
        message_id=callback.message.message_id,
        text=texts.ADMIN_APPROVAL_DECLINE_PROMPT_TEXT,
        reply_markup=build_admin_proxy_reply_prompt_keyboard(approval_id),
    )
    await remember_admin_panel(state, panel)


@router.callback_query(F.data.startswith("approval:read:"))
@router.callback_query(F.data.startswith("approval:quiet_close:"))
async def quietly_close_approval(
    callback: CallbackQuery,
    state: FSMContext | None = None,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings | None = None,
) -> None:
    """Resolve an approval quietly without sending anything to the client."""
    await callback.answer()
    if not is_admin or callback.data is None:
        return

    quiet_close = callback.data.startswith("approval:quiet_close:")
    approval_id = int(callback.data.rsplit(":", 1)[1])
    repository = ApprovalRequestRepository(db_session)
    approval = await repository.get_by_id(approval_id)
    allowed_statuses = (
        (ApprovalRequestStatus.PENDING, ApprovalRequestStatus.OFFERED)
        if quiet_close
        else (ApprovalRequestStatus.PENDING,)
    )
    if approval is None or approval.status not in allowed_statuses:
        await _show_pending_approvals_or_notice(
            callback,
            db_session=db_session,
            state=state,
            settings=settings,
            notice_text=texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
        )
        return

    approval.status = ApprovalRequestStatus.RESPONDED
    approval.resolved_at = utcnow()
    notice_text = (
        texts.ADMIN_APPROVAL_QUIET_CLOSE_TEXT
        if quiet_close
        else texts.ADMIN_APPROVAL_READ_TEXT
    )
    approval.admin_response_text = "Тихо закрыто" if quiet_close else "Прочитано"
    await db_session.commit()
    if callback.message is not None:
        if settings is not None and state is not None:
            await show_pending_approvals(
                callback.message,
                db_session=db_session,
                is_admin=True,
                settings=settings,
                state=state,
                edit=True,
                notice_text=notice_text,
            )
        else:
            await _replace_approval_callback_notice(callback, notice_text)
