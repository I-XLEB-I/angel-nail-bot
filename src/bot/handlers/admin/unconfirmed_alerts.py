"""Admin handlers for the «client did not confirm 2h reminder» alert keyboard."""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.handlers.admin.rescue_slots import send_rescue_slot_prompt_to_admins
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.models import BookingStatus
from src.db.repositories.bookings import BookingRepository
from src.services.anti_abuse import get_anti_abuse_settings, record_rate_event
from src.services.booking import apply_booking_no_show, build_no_show_client_notice
from src.services.notifications import send_text_to_user
from src.services.rescue_slots import slot_is_rescuable

router = Router(name="admin_unconfirmed_alerts")


@router.callback_query(F.data.startswith("admin_unconfirmed:no_show:"))
async def mark_unconfirmed_as_no_show(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    is_admin: bool,
    settings: Settings,
) -> None:
    """Cancel a confirmed booking as a no-show from the unconfirmed-alert keyboard.

    Increments the client's strike counter the same way the schedule-detail
    no-show button does, so anti-abuse stays consistent.
    """
    if not is_admin:
        await callback.answer()
        return
    if callback.data is None:
        await callback.answer()
        return

    await callback.answer()
    booking_id = int(callback.data.rsplit(":", 1)[-1])
    booking = await BookingRepository(db_session).get_by_id(booking_id)
    if booking is None or booking.client is None or booking.status != BookingStatus.CONFIRMED:
        if callback.message is not None:
            await replace_inline_message_text(
                callback.message,
                texts.ADMIN_UNCONFIRMED_NO_SHOW_NOT_FOUND_TEXT,
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
        metadata={"booking_id": booking.id, "source": "unconfirmed_alert"},
    )
    await db_session.commit()

    if callback.message is not None:
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_UNCONFIRMED_NO_SHOW_DONE_TEXT,
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
