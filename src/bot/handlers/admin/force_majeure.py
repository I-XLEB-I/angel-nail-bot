"""Admin force-majeure flow: mass-cancel all active bookings on a given day."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import clear_state_preserving_admin_panel
from src.bot.keyboards.admin import (
    build_force_majeure_client_keyboard,
    build_force_majeure_confirm_keyboard,
    build_force_majeure_day_keyboard,
    build_force_majeure_final_keyboard,
    build_force_majeure_reason_keyboard,
)
from src.bot.states import AdminForceMajeure
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.force_majeure import (
    apply_force_majeure_cancellation,
    build_force_majeure_notice,
)
from src.services.notifications import send_text_to_user
from src.services.runtime_settings import get_runtime_tz

router = Router(name="admin_force_majeure")
logger = logging.getLogger(__name__)


async def _load_force_majeure_bookings(
    *,
    db_session: AsyncSession,
    settings: Settings,
    local_day: date,
) -> list:
    """Load all active bookings for the chosen local day."""
    tz_name = await get_runtime_tz(SettingRepository(db_session), settings=settings)
    return await BookingRepository(db_session).list_active_for_day(
        local_day=local_day,
        tz_name=tz_name,
    )


async def _load_force_majeure_unnotified_bookings(
    *,
    db_session: AsyncSession,
    settings: Settings,
    local_day: date,
) -> list:
    """Load already cancelled bookings that still need a client notice."""
    tz_name = await get_runtime_tz(SettingRepository(db_session), settings=settings)
    return await BookingRepository(db_session).list_force_majeure_unnotified_for_day(
        local_day=local_day,
        tz_name=tz_name,
    )


@router.message(lambda message: message.text == "🌷 Форс-мажор")
async def force_majeure_entry(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Show the day-picker for mass cancellation."""
    if not is_admin:
        return

    settings_repository = SettingRepository(db_session)
    tz_name = await get_runtime_tz(settings_repository, settings=settings)
    now_utc = datetime.now(UTC)
    booking_repository = BookingRepository(db_session)
    upcoming_days = await booking_repository.list_upcoming_active_days(
        now_utc=now_utc,
        tz_name=tz_name,
    )

    if not upcoming_days:
        await message.answer(texts.FORCE_MAJEURE_NO_BOOKINGS_TEXT)
        return

    day_options: list[tuple[str, str]] = []
    for local_day in upcoming_days:
        bookings = await booking_repository.list_active_for_day(
            local_day=local_day,
            tz_name=tz_name,
        )
        label = f"{local_day.strftime('%d.%m')} — {len(bookings)} зап."
        day_options.append((label, local_day.isoformat()))

    await state.set_state(AdminForceMajeure.choose_day)
    await message.answer(
        texts.FORCE_MAJEURE_CHOOSE_DAY_TEXT,
        reply_markup=build_force_majeure_day_keyboard(day_options),
    )


@router.callback_query(
    StateFilter(AdminForceMajeure.choose_day),
    F.data.startswith("force_majeure:day:"),
)
async def force_majeure_day_chosen(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Store the chosen day and ask for the reason text."""
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.data is None or callback.message is None:
        return

    iso_date = callback.data.removeprefix("force_majeure:day:")
    default_reason = await TemplateRepository(db_session).get_content_or_default(
        "force_majeure_notice",
        texts.DEFAULT_FORCE_MAJEURE_TEMPLATE,
    )
    await state.update_data(
        force_majeure_date=iso_date,
        force_majeure_reason=default_reason,
    )
    await state.set_state(AdminForceMajeure.input_reason)
    await replace_inline_message_text(
        callback.message,
        (
            f"{texts.FORCE_MAJEURE_INPUT_REASON_TEXT}\n\n"
            f"Текущий шаблон:\n{default_reason}"
        ),
        reply_markup=build_force_majeure_reason_keyboard(iso_date),
    )


async def _show_force_majeure_review(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
    iso_date: str,
    reason: str,
    replace_current: bool,
) -> bool:
    """Validate the selected day and render the first destructive-action review."""
    settings_repository = SettingRepository(db_session)
    tz_name = await get_runtime_tz(settings_repository, settings=settings)
    try:
        local_day = date.fromisoformat(iso_date)
    except ValueError:
        if replace_current:
            await replace_inline_message_text(message, texts.FORCE_MAJEURE_NO_BOOKINGS_TEXT)
        else:
            await message.answer(texts.FORCE_MAJEURE_NO_BOOKINGS_TEXT)
        return False

    bookings = await BookingRepository(db_session).list_active_for_day(
        local_day=local_day,
        tz_name=tz_name,
    )
    if not bookings:
        if replace_current:
            await replace_inline_message_text(message, texts.FORCE_MAJEURE_NO_BOOKINGS_TEXT)
        else:
            await message.answer(texts.FORCE_MAJEURE_NO_BOOKINGS_TEXT)
        await clear_state_preserving_admin_panel(state)
        return False

    await state.update_data(force_majeure_reason=reason)
    await state.set_state(AdminForceMajeure.confirm)
    review_text = texts.FORCE_MAJEURE_CONFIRM_TEXT.format(
        count=len(bookings),
        date=local_day.strftime("%d.%m.%Y"),
        reason=reason,
    )
    reply_markup = build_force_majeure_confirm_keyboard(iso_date)
    if replace_current:
        await replace_inline_message_text(
            message,
            review_text,
            reply_markup=reply_markup,
        )
    else:
        await message.answer(review_text, reply_markup=reply_markup)
    return True


@router.callback_query(
    StateFilter(AdminForceMajeure.input_reason),
    F.data.startswith("force_majeure:use_template:"),
)
async def force_majeure_use_template(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Use the admin-editable force-majeure template as the cancellation reason."""
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.data is None or callback.message is None:
        return
    data = await state.get_data()
    reason = str(data.get("force_majeure_reason") or "").strip()
    if not reason:
        reason = await TemplateRepository(db_session).get_content_or_default(
            "force_majeure_notice",
            texts.DEFAULT_FORCE_MAJEURE_TEMPLATE,
        )
    iso_date = callback.data.removeprefix("force_majeure:use_template:")
    await _show_force_majeure_review(
        callback.message,
        state,
        db_session=db_session,
        settings=settings,
        iso_date=iso_date,
        reason=reason,
        replace_current=True,
    )


@router.message(StateFilter(AdminForceMajeure.input_reason), F.text)
async def force_majeure_reason_entered(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Show confirmation with booking count and the entered reason."""
    if not is_admin:
        return

    data = await state.get_data()
    iso_date = data.get("force_majeure_date", "")
    reason = (message.text or "").strip()
    if not reason or not iso_date:
        await message.answer(texts.FORCE_MAJEURE_INPUT_REASON_TEXT)
        return

    await _show_force_majeure_review(
        message,
        state,
        db_session=db_session,
        settings=settings,
        iso_date=str(iso_date),
        reason=reason,
        replace_current=False,
    )


@router.callback_query(
    StateFilter(AdminForceMajeure.confirm),
    F.data.startswith("force_majeure:confirm:"),
)
async def force_majeure_confirmed(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Show the second confirmation step before the real mass cancellation."""
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.data is None or callback.message is None:
        return

    iso_date = callback.data.removeprefix("force_majeure:confirm:")

    settings_repository = SettingRepository(db_session)
    tz_name = await get_runtime_tz(settings_repository, settings=settings)
    try:
        local_day = date.fromisoformat(iso_date)
    except ValueError:
        await replace_inline_message_text(callback.message, texts.FORCE_MAJEURE_NO_BOOKINGS_TEXT)
        await clear_state_preserving_admin_panel(state)
        return

    booking_repository = BookingRepository(db_session)
    bookings = await booking_repository.list_active_for_day(local_day=local_day, tz_name=tz_name)
    if not bookings:
        await replace_inline_message_text(callback.message, texts.FORCE_MAJEURE_NO_BOOKINGS_TEXT)
        await clear_state_preserving_admin_panel(state)
        return

    await replace_inline_message_text(
        callback.message,
        texts.FORCE_MAJEURE_FINAL_CONFIRM_TEXT.format(
            count=len(bookings),
            date=local_day.strftime("%d.%m"),
        ),
        reply_markup=build_force_majeure_final_keyboard(iso_date, len(bookings)),
    )


@router.callback_query(
    StateFilter(AdminForceMajeure.confirm),
    F.data.startswith("force_majeure:review:"),
)
async def force_majeure_review(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Return from the final safety screen back to the review step."""
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.data is None or callback.message is None:
        return

    data = await state.get_data()
    iso_date = callback.data.removeprefix("force_majeure:review:")
    reason = data.get("force_majeure_reason", texts.DEFAULT_FORCE_MAJEURE_TEMPLATE)
    try:
        local_day = date.fromisoformat(iso_date)
    except ValueError:
        await replace_inline_message_text(callback.message, texts.FORCE_MAJEURE_NO_BOOKINGS_TEXT)
        await clear_state_preserving_admin_panel(state)
        return

    bookings = await _load_force_majeure_bookings(
        db_session=db_session,
        settings=settings,
        local_day=local_day,
    )
    if not bookings:
        await replace_inline_message_text(callback.message, texts.FORCE_MAJEURE_NO_BOOKINGS_TEXT)
        await clear_state_preserving_admin_panel(state)
        return

    await replace_inline_message_text(
        callback.message,
        texts.FORCE_MAJEURE_CONFIRM_TEXT.format(
            count=len(bookings),
            date=local_day.strftime("%d.%m.%Y"),
            reason=reason,
        ),
        reply_markup=build_force_majeure_confirm_keyboard(iso_date),
    )


@router.callback_query(
    StateFilter(AdminForceMajeure.confirm),
    F.data.startswith("force_majeure:final_commit:"),
)
async def force_majeure_final_commit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Execute the mass cancellation and notify all affected clients."""
    if not is_admin:
        await callback.answer()
        return
    await callback.answer()
    if callback.data is None or callback.message is None:
        return

    data = await state.get_data()
    iso_date = callback.data.removeprefix("force_majeure:final_commit:")
    reason = data.get("force_majeure_reason", texts.DEFAULT_FORCE_MAJEURE_TEMPLATE)
    try:
        local_day = date.fromisoformat(iso_date)
    except ValueError:
        await replace_inline_message_text(callback.message, texts.FORCE_MAJEURE_NO_BOOKINGS_TEXT)
        await clear_state_preserving_admin_panel(state)
        return

    bookings = await _load_force_majeure_bookings(
        db_session=db_session,
        settings=settings,
        local_day=local_day,
    )
    pending_notice_bookings = await _load_force_majeure_unnotified_bookings(
        db_session=db_session,
        settings=settings,
        local_day=local_day,
    )
    if not bookings and not pending_notice_bookings:
        await replace_inline_message_text(callback.message, texts.FORCE_MAJEURE_NO_BOOKINGS_TEXT)
        await clear_state_preserving_admin_panel(state)
        return

    for booking in bookings:
        apply_force_majeure_cancellation(booking, reason=reason)

    await db_session.commit()

    notify_targets_by_id = {booking.id: booking for booking in pending_notice_bookings}
    for booking in bookings:
        notify_targets_by_id.setdefault(booking.id, booking)

    cancelled_count = 0
    notice = build_force_majeure_notice(reason)
    for booking in notify_targets_by_id.values():
        if booking.client is None or booking.force_majeure_notice_sent_at is not None:
            continue
        try:
            await send_text_to_user(
                callback.bot,
                tg_id=booking.client.tg_id,
                text=notice,
                reply_markup=build_force_majeure_client_keyboard(),
            )
            booking.force_majeure_notice_sent_at = datetime.now(UTC)
            await db_session.commit()
            cancelled_count += 1
        except Exception:
            logger.exception(
                "Failed to send force-majeure notice for booking %s",
                booking.id,
            )
            await db_session.rollback()
    await clear_state_preserving_admin_panel(state)
    await replace_inline_message_text(
        callback.message,
        texts.FORCE_MAJEURE_DONE_TEXT.format(
            sent=cancelled_count,
            total=len(notify_targets_by_id),
        ),
    )
