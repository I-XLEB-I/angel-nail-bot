from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.fsm_utils import clear_state_preserving_admin_mode
from src.bot.handlers.admin.approvals import send_approval_card_to_admins
from src.bot.handlers.client.brand import send_template_message
from src.bot.handlers.client.my_bookings import (
    load_booking_and_addons,
    show_booking_card_message,
)
from src.bot.keyboards.admin import build_admin_late_notice_keyboard
from src.bot.keyboards.client import (
    build_back_to_booking_keyboard,
    build_back_to_menu_keyboard,
    build_late_notice_minutes_keyboard,
    build_late_notice_reason_keyboard,
    build_late_notice_result_keyboard,
    build_repair_description_keyboard,
    build_repair_issue_keyboard,
    build_repair_nails_keyboard,
    build_repair_photos_keyboard,
)
from src.bot.states import MyBookings as MyBookingsStates
from src.bot.states import RepairRequestFlow
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.models import ApprovalRequestKind, Booking, User
from src.db.repositories.approvals import ApprovalRequestRepository
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.late_arrival_notices import LateArrivalNoticeRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.aftercare import (
    build_admin_late_notice_text,
    can_report_late_arrival,
    can_request_repair,
    normalize_notice_reason,
    normalize_repair_issue,
)
from src.services.booking import (
    build_booking_service_label,
    format_local_datetime,
    format_local_day_label,
)
from src.services.button_configs import ClientMenuButtonConfig, load_all_button_configs
from src.services.notifications import send_text_to_admins
from src.services.runtime_settings import get_int_setting
from src.services.template_texts import render_named_template

router = Router(name="client_aftercare")


async def load_runtime_button_configs(
    db_session: AsyncSession,
) -> dict[str, ClientMenuButtonConfig]:
    """Load editable runtime button configs for aftercare client screens."""
    return await load_all_button_configs(SettingRepository(db_session))


async def get_aftercare_settings(
    db_session: AsyncSession,
) -> dict[str, int]:
    """Load the runtime settings used by late notices and repair requests."""
    repository = SettingRepository(db_session)
    return {
        "late_notice_warning_minutes": await get_int_setting(
            repository,
            key="late_notice_warning_minutes",
            default=15,
        ),
        "repair_warranty_days": await get_int_setting(
            repository,
            key="repair_warranty_days",
            default=14,
        ),
        "repair_warranty_nails_limit": await get_int_setting(
            repository,
            key="repair_warranty_nails_limit",
            default=2,
        ),
        "repair_request_window_days": await get_int_setting(
            repository,
            key="repair_request_window_days",
            default=30,
        ),
    }


def build_late_notice_template_values(
    *,
    booking: Booking,
    minutes: int,
    reason_code: str | None,
    comment: str | None,
    tz_name: str,
) -> dict[str, str]:
    """Build placeholder values for late-notice client templates."""
    service = build_booking_service_label(booking.base_service, [])
    values = {
        "minutes": str(minutes),
        "reason": escape(normalize_notice_reason(reason_code)),
        "comment": escape(comment or "—"),
        "service": escape(service),
        "date": "",
        "time": "",
    }
    if booking.slot is not None:
        local_dt = format_local_datetime(booking.slot.start_at, tz_name)
        values["date"] = escape(format_local_day_label(local_dt.date()))
        values["time"] = escape(local_dt.strftime("%H:%M"))
    return values


async def render_late_notice_client_text(
    db_session: AsyncSession,
    *,
    template_key: str,
    booking: Booking,
    minutes: int,
    reason_code: str | None,
    comment: str | None,
    tz_name: str,
) -> str:
    """Render one late-notice client-facing message from templates."""
    return await render_named_template(
        TemplateRepository(db_session),
        key=template_key,
        values=build_late_notice_template_values(
            booking=booking,
            minutes=minutes,
            reason_code=reason_code,
            comment=comment,
            tz_name=tz_name,
        ),
    )


async def submit_late_notice(
    *,
    message: Message,
    state: FSMContext,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
    booking_id: int,
    minutes: int,
    reason_code: str | None,
    comment: str | None,
    replace_current: bool,
) -> None:
    """Create or update one late-arrival notice and notify both sides."""
    button_configs = await load_runtime_button_configs(db_session)
    booking, _ = await load_booking_and_addons(
        db_session,
        client_id=user.id,
        booking_id=booking_id,
    )
    if booking is None or not can_report_late_arrival(booking):
        await clear_state_preserving_admin_mode(state)
        if replace_current:
            await show_booking_card_message(
                message,
                booking_id=booking_id,
                db_session=db_session,
                user=user,
                settings=settings,
                edit=True,
                prefix_text=texts.LATE_NOTICE_NEED_ACTIVE_BOOKING_TEXT,
            )
        else:
            await message.answer(
                texts.LATE_NOTICE_NEED_ACTIVE_BOOKING_TEXT,
                reply_markup=build_back_to_booking_keyboard(
                    booking_id,
                    button_configs=button_configs,
                ),
            )
        return

    repository = LateArrivalNoticeRepository(db_session)
    existing_notice = await repository.get_active_for_booking(booking.id)
    is_update = existing_notice is not None
    if existing_notice is None:
        notice = await repository.create(
            booking_id=booking.id,
            client_id=user.id,
            minutes=minutes,
            reason_code=reason_code,
            comment=comment,
        )
    else:
        notice = await repository.update(
            existing_notice,
            minutes=minutes,
            reason_code=reason_code,
            comment=(comment or "").strip() or None,
        )
    await db_session.commit()
    loaded_notice = await repository.get_by_id(notice.id)

    if loaded_notice is not None:
        await send_text_to_admins(
            message.bot,
            admin_tg_ids=settings.admin_tg_id_set,
            text=build_admin_late_notice_text(
                notice=loaded_notice,
                booking=booking,
                tz_name=settings.tz,
                is_update=is_update,
            ),
            reply_markup=build_admin_late_notice_keyboard(loaded_notice.id),
        )

    runtime_settings = await get_aftercare_settings(db_session)
    warning_minutes = runtime_settings["late_notice_warning_minutes"]
    template_key = (
        "late_notice_client_risky" if minutes > warning_minutes else "late_notice_client_sent"
    )
    response_text = await render_late_notice_client_text(
        db_session,
        template_key=template_key,
        booking=booking,
        minutes=minutes,
        reason_code=reason_code,
        comment=comment,
        tz_name=settings.tz,
    )
    if is_update:
        response_text = f"{texts.LATE_NOTICE_CLIENT_UPDATED_TEXT}\n\n{response_text}"

    await clear_state_preserving_admin_mode(state)
    if replace_current:
        await send_template_message(
            message,
            template_key=template_key,
            caption=response_text,
            reply_markup=build_late_notice_result_keyboard(
                booking.id,
                allow_reschedule_request=minutes >= 30,
                button_configs=button_configs,
            ),
            replace_current=True,
        )
        return

    await send_template_message(
        message,
        template_key=template_key,
        caption=response_text,
        reply_markup=build_late_notice_result_keyboard(
            booking.id,
            allow_reschedule_request=minutes >= 30,
            button_configs=button_configs,
        ),
    )


@router.callback_query(F.data.startswith("my_bookings:late:"))
async def start_late_notice(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Open the late-arrival minute picker from one booking card."""
    await callback.answer(texts.LATE_NOTICE_UPDATED_TOAST)
    if callback.message is None or callback.data is None:
        return

    booking_id = int(callback.data.rsplit(":", 1)[1])
    booking, _ = await load_booking_and_addons(
        db_session,
        client_id=user.id,
        booking_id=booking_id,
    )
    if booking is None or not can_report_late_arrival(booking):
        await show_booking_card_message(
            callback.message,
            booking_id=booking_id,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.LATE_NOTICE_NEED_ACTIVE_BOOKING_TEXT,
        )
        return

    intro_text = await render_named_template(
        TemplateRepository(db_session),
        key="late_notice_intro",
        values={},
    )
    button_configs = await load_runtime_button_configs(db_session)
    await clear_state_preserving_admin_mode(state)
    await send_template_message(
        callback.message,
        template_key="late_notice_intro",
        caption=intro_text,
        reply_markup=build_late_notice_minutes_keyboard(
            booking_id,
            button_configs=button_configs,
        ),
        replace_current=True,
    )


@router.callback_query(F.data.startswith("my_bookings:late_minutes:"))
async def choose_late_notice_minutes(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
) -> None:
    """Open the reason picker for the selected delay amount."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    _, _, booking_id_str, minutes_str = callback.data.split(":", 3)
    button_configs = await load_runtime_button_configs(db_session)
    await replace_inline_message_text(
        callback.message,
        texts.LATE_NOTICE_REASON_PROMPT_TEXT,
        reply_markup=build_late_notice_reason_keyboard(
            int(booking_id_str),
            int(minutes_str),
            button_configs=button_configs,
        ),
    )


@router.callback_query(F.data.startswith("my_bookings:late_reason:"))
async def choose_late_notice_reason(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Handle the selected late-arrival reason."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    _, _, booking_id_str, minutes_str, reason_code = callback.data.split(":", 4)
    booking_id = int(booking_id_str)
    minutes = int(minutes_str)
    button_configs = await load_runtime_button_configs(db_session)
    if reason_code == "other":
        await state.set_state(MyBookingsStates.input_late_other_reason)
        await state.update_data(
            late_notice_booking_id=booking_id,
            late_notice_minutes=minutes,
        )
        await replace_inline_message_text(
            callback.message,
            texts.LATE_NOTICE_OTHER_REASON_PROMPT_TEXT,
            reply_markup=build_back_to_booking_keyboard(
                booking_id,
                button_configs=button_configs,
            ),
        )
        return

    normalized_reason = None if reason_code == "skip" else reason_code
    await submit_late_notice(
        message=callback.message,
        state=state,
        db_session=db_session,
        user=user,
        settings=settings,
        booking_id=booking_id,
        minutes=minutes,
        reason_code=normalized_reason,
        comment=None,
        replace_current=True,
    )


@router.message(StateFilter(MyBookingsStates.input_late_other_reason), F.text)
async def input_late_notice_other_reason(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Accept the free-text comment for a late-arrival notice."""
    reason_text = (message.text or "").strip()
    if not reason_text:
        await message.answer(texts.LATE_NOTICE_OTHER_REASON_INVALID_TEXT)
        return

    data = await state.get_data()
    booking_id = data.get("late_notice_booking_id")
    minutes = data.get("late_notice_minutes")
    if booking_id is None or minutes is None:
        await clear_state_preserving_admin_mode(state)
        button_configs = await load_runtime_button_configs(db_session)
        await message.answer(
            texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT,
            reply_markup=build_back_to_menu_keyboard(button_configs=button_configs),
        )
        return

    await submit_late_notice(
        message=message,
        state=state,
        db_session=db_session,
        user=user,
        settings=settings,
        booking_id=int(booking_id),
        minutes=int(minutes),
        reason_code="other",
        comment=reason_text,
        replace_current=False,
    )


@router.message(StateFilter(MyBookingsStates.input_late_other_reason))
async def reject_non_text_late_reason(message: Message) -> None:
    """Keep the late-arrival free-text step text-only."""
    await message.answer(texts.LATE_NOTICE_PHOTO_HINT_TEXT)


@router.callback_query(F.data.startswith("repair:start:"))
async def start_repair_request(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Enter the repair/warranty request flow from a completed booking."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return

    booking_id = int(callback.data.rsplit(":", 1)[1])
    booking, addons = await load_booking_and_addons(
        db_session,
        client_id=user.id,
        booking_id=booking_id,
    )
    runtime_settings = await get_aftercare_settings(db_session)
    if booking is None or not can_request_repair(
        booking,
        request_window_days=runtime_settings["repair_request_window_days"],
    ):
        await show_booking_card_message(
            callback.message,
            booking_id=booking_id,
            db_session=db_session,
            user=user,
            settings=settings,
            edit=True,
            prefix_text=texts.MY_BOOKINGS_REPAIR_UNAVAILABLE_TEXT,
        )
        return

    local_dt = format_local_datetime(booking.slot.start_at, settings.tz) if booking.slot else None
    service_label = build_booking_service_label(booking.base_service, addons)
    intro_text = await render_named_template(
        TemplateRepository(db_session),
        key="repair_intro",
        values={
            "date": escape(format_local_day_label(local_dt.date())) if local_dt else "—",
            "service": escape(service_label),
            "warranty_days": str(runtime_settings["repair_warranty_days"]),
            "nails_limit": str(runtime_settings["repair_warranty_nails_limit"]),
        },
    )

    await clear_state_preserving_admin_mode(state)
    await state.update_data(
        repair_booking_id=booking_id,
        repair_photos=[],
    )
    button_configs = await load_runtime_button_configs(db_session)
    await send_template_message(
        callback.message,
        template_key="repair_intro",
        caption=intro_text,
        reply_markup=build_repair_nails_keyboard(
            booking_id,
            button_configs=button_configs,
        ),
        replace_current=True,
    )


@router.callback_query(F.data.startswith("repair:nails:"))
async def choose_repair_nails(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Store nail count and move to issue type."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    _, _, booking_id_str, count_str = callback.data.split(":", 3)
    button_configs = await load_runtime_button_configs(db_session)
    await state.set_state(RepairRequestFlow.choose_issue)
    await state.update_data(
        repair_booking_id=int(booking_id_str),
        repair_nails_count=int(count_str),
    )
    await replace_inline_message_text(
        callback.message,
        "🛠 Что именно случилось?\n\nВыбери вариант ниже 👇",
        reply_markup=build_repair_issue_keyboard(
            int(booking_id_str),
            button_configs=button_configs,
        ),
    )


@router.callback_query(F.data.startswith("repair:issue:"))
async def choose_repair_issue(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Store repair issue type and move into photo upload."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    _, _, booking_id_str, issue_code = callback.data.split(":", 3)
    button_configs = await load_runtime_button_configs(db_session)
    await state.set_state(RepairRequestFlow.upload_photos)
    await state.update_data(
        repair_booking_id=int(booking_id_str),
        repair_issue_code=issue_code,
        repair_photos=[],
    )
    await replace_inline_message_text(
        callback.message,
        texts.MY_BOOKINGS_REPAIR_PHOTO_PROMPT_TEXT,
        reply_markup=build_repair_photos_keyboard(
            int(booking_id_str),
            can_finish=False,
            can_remove_last=False,
            button_configs=button_configs,
        ),
    )


@router.message(StateFilter(RepairRequestFlow.upload_photos), F.photo)
async def receive_repair_photo(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Collect up to three repair photos."""
    data = await state.get_data()
    booking_id = int(data.get("repair_booking_id", 0))
    photos = list(data.get("repair_photos", []))
    button_configs = await load_runtime_button_configs(db_session)
    if len(photos) >= 3:
        await message.answer(
            texts.MY_BOOKINGS_REPAIR_PHOTO_PROGRESS_TEXT.format(count=3),
            reply_markup=build_repair_photos_keyboard(
                booking_id,
                can_finish=True,
                can_remove_last=True,
                button_configs=button_configs,
            ),
        )
        return

    photos.append(message.photo[-1].file_id)
    await state.update_data(repair_photos=photos)
    await message.answer(
        texts.MY_BOOKINGS_REPAIR_PHOTO_PROGRESS_TEXT.format(count=len(photos)),
        reply_markup=build_repair_photos_keyboard(
            booking_id,
            can_finish=bool(photos),
            can_remove_last=bool(photos),
            button_configs=button_configs,
        ),
    )


@router.callback_query(
    StateFilter(RepairRequestFlow.upload_photos),
    F.data.startswith("repair:remove_last:"),
)
async def remove_repair_last_photo(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Remove the most recent repair photo from state."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    booking_id = int(callback.data.rsplit(":", 1)[1])
    data = await state.get_data()
    photos = list(data.get("repair_photos", []))
    button_configs = await load_runtime_button_configs(db_session)
    if photos:
        photos.pop()
        await state.update_data(repair_photos=photos)
    await replace_inline_message_text(
        callback.message,
        texts.MY_BOOKINGS_REPAIR_PHOTO_PROMPT_TEXT
        if not photos
        else texts.MY_BOOKINGS_REPAIR_PHOTO_PROGRESS_TEXT.format(count=len(photos)),
        reply_markup=build_repair_photos_keyboard(
            booking_id,
            can_finish=bool(photos),
            can_remove_last=bool(photos),
            button_configs=button_configs,
        ),
    )


@router.callback_query(
    StateFilter(RepairRequestFlow.upload_photos),
    F.data.startswith("repair:photos_done:"),
)
async def finish_repair_photos(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Move from repair-photo upload to the description step."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    booking_id = int(callback.data.rsplit(":", 1)[1])
    data = await state.get_data()
    photos = list(data.get("repair_photos", []))
    button_configs = await load_runtime_button_configs(db_session)
    if not photos:
        await callback.answer(texts.MY_BOOKINGS_REPAIR_NEED_PHOTO_TEXT, show_alert=True)
        return
    await state.set_state(RepairRequestFlow.input_description)
    await replace_inline_message_text(
        callback.message,
        texts.MY_BOOKINGS_REPAIR_DESCRIPTION_PROMPT_TEXT,
        reply_markup=build_repair_description_keyboard(
            booking_id,
            button_configs=button_configs,
        ),
    )


@router.callback_query(
    StateFilter(RepairRequestFlow.upload_photos),
    F.data.startswith("repair:photos_back:"),
)
async def back_to_repair_issue(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Return from photo upload to the issue-type step."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    booking_id = int(callback.data.rsplit(":", 1)[1])
    button_configs = await load_runtime_button_configs(db_session)
    await state.set_state(RepairRequestFlow.choose_issue)
    await state.update_data(repair_booking_id=booking_id, repair_photos=[])
    await replace_inline_message_text(
        callback.message,
        "🛠 Что именно случилось?\n\nВыбери вариант ниже 👇",
        reply_markup=build_repair_issue_keyboard(
            booking_id,
            button_configs=button_configs,
        ),
    )


@router.message(StateFilter(RepairRequestFlow.upload_photos))
async def reject_non_photo_repair_upload(message: Message) -> None:
    """Keep the repair upload step photo-only."""
    await message.answer(texts.MY_BOOKINGS_REPAIR_NEED_PHOTO_TEXT)


@router.callback_query(
    StateFilter(RepairRequestFlow.input_description),
    F.data.startswith("repair:description_back:"),
)
async def back_to_repair_photos(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Return from description input to the photo-upload step."""
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    booking_id = int(callback.data.rsplit(":", 1)[1])
    data = await state.get_data()
    photos = list(data.get("repair_photos", []))
    button_configs = await load_runtime_button_configs(db_session)
    await state.set_state(RepairRequestFlow.upload_photos)
    await replace_inline_message_text(
        callback.message,
        texts.MY_BOOKINGS_REPAIR_PHOTO_PROMPT_TEXT
        if not photos
        else texts.MY_BOOKINGS_REPAIR_PHOTO_PROGRESS_TEXT.format(count=len(photos)),
        reply_markup=build_repair_photos_keyboard(
            booking_id,
            can_finish=bool(photos),
            can_remove_last=bool(photos),
            button_configs=button_configs,
        ),
    )


@router.message(StateFilter(RepairRequestFlow.input_description), F.text)
async def submit_repair_request(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Create a repair approval request after photos and description are ready."""
    description = (message.text or "").strip()
    if not description:
        await message.answer(texts.MY_BOOKINGS_REPAIR_DESCRIPTION_INVALID_TEXT)
        return

    data = await state.get_data()
    booking_id = int(data.get("repair_booking_id", 0))
    booking = await BookingRepository(db_session).get_client_booking(booking_id, user.id)
    runtime_settings = await get_aftercare_settings(db_session)
    if booking is None or not can_request_repair(
        booking,
        request_window_days=runtime_settings["repair_request_window_days"],
    ):
        await clear_state_preserving_admin_mode(state)
        button_configs = await load_runtime_button_configs(db_session)
        await message.answer(
            texts.MY_BOOKINGS_REPAIR_UNAVAILABLE_TEXT,
            reply_markup=build_back_to_booking_keyboard(
                booking_id,
                button_configs=button_configs,
            ),
        )
        return

    photos = list(data.get("repair_photos", []))
    if not photos:
        await message.answer(texts.MY_BOOKINGS_REPAIR_NEED_PHOTO_TEXT)
        return

    issue_code = str(data.get("repair_issue_code") or "other")
    nails_count = int(data.get("repair_nails_count") or 1)
    repository = ApprovalRequestRepository(db_session)
    approval, approval_created = await repository.create_or_reuse_pending(
        client_id=user.id,
        base_service_id=booking.base_service_id,
        requested_text=f"Ремонт: {normalize_repair_issue(issue_code)}",
        kind=ApprovalRequestKind.REPAIR_REQUEST,
        related_booking_id=booking.id,
        design_photos=photos,
        design_comment=description,
        repair_nails_count=nails_count,
        repair_issue_code=issue_code,
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

    local_dt = format_local_datetime(booking.slot.start_at, settings.tz) if booking.slot else None
    service_label = build_booking_service_label(booking.base_service, [])
    text = await render_named_template(
        TemplateRepository(db_session),
        key="repair_request_received",
        values={
            "date": escape(format_local_day_label(local_dt.date())) if local_dt else "—",
            "service": escape(service_label),
            "issue": escape(normalize_repair_issue(issue_code)),
            "nails_count": str(nails_count),
        },
    )
    await clear_state_preserving_admin_mode(state)
    button_configs = await load_runtime_button_configs(db_session)
    await send_template_message(
        message,
        template_key="repair_request_received",
        caption=text,
        reply_markup=build_back_to_booking_keyboard(
            booking.id,
            button_configs=button_configs,
        ),
    )


@router.message(StateFilter(RepairRequestFlow.input_description))
async def reject_non_text_repair_description(message: Message) -> None:
    """Keep the repair description step text-only."""
    await message.answer(texts.MY_BOOKINGS_REPAIR_DESCRIPTION_INVALID_TEXT)
