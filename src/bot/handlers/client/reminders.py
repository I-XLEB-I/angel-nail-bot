from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.keyboards.client import build_reminder_confirmed_keyboard
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.models import BookingStatus, User, utcnow
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.settings import SettingRepository
from src.services.button_configs import load_all_button_configs
from src.services.morning_summary import refresh_live_morning_summary_for_today
from src.services.reminders import resolve_admin_unconfirmed_alert_messages
from src.services.runtime_settings import get_str_setting

router = Router(name="client_reminders")


def _parse_reminder_confirmation_callback(raw_data: str) -> tuple[str, int] | None:
    """Return the reminder kind and booking id from a confirmation callback."""
    prefixes = {
        "reminder:ok24h:": "24h",
        "reminder:ok2h:": "2h",
        "reminder:ok:": "legacy",
    }
    for prefix, kind in prefixes.items():
        if raw_data.startswith(prefix):
            return kind, int(raw_data.removeprefix(prefix))
    return None


@router.callback_query(F.data.startswith("reminder:ok24h:"))
@router.callback_query(F.data.startswith("reminder:ok2h:"))
@router.callback_query(F.data.startswith("reminder:ok:"))
async def confirm_reminder(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Acknowledge a reminder confirmation button."""
    booking_id: int | None = None
    confirmed = False
    resolved_alert_kind: str | None = None
    resolved_booking = None
    resolved_confirmed_at = None
    if callback.data:
        parsed = _parse_reminder_confirmation_callback(callback.data)
        if parsed is None:
            await callback.answer(texts.REMINDER_STALE_TEXT)
            return
        reminder_kind, booking_id = parsed
        booking = await BookingRepository(db_session).get_by_id(booking_id)
        now = utcnow()
        slot_start_at = None
        if booking is not None and booking.slot is not None:
            slot_start_at = booking.slot.start_at
            if slot_start_at.tzinfo is None:
                slot_start_at = slot_start_at.replace(tzinfo=UTC)
        if (
            booking is not None
            and booking.client_id == user.id
            and booking.status == BookingStatus.CONFIRMED
            and slot_start_at is not None
            and slot_start_at > now
        ):
            changed = False
            if reminder_kind == "24h":
                if booking.reminder_24h_confirmed_at is None:
                    booking.reminder_24h_confirmed_at = now
                    changed = True
                    resolved_alert_kind = "24h"
            elif reminder_kind == "2h":
                if booking.reminder_2h_confirmed_at is None:
                    booking.reminder_2h_confirmed_at = now
                    changed = True
                    resolved_alert_kind = "2h"
            else:
                if (
                    booking.reminder_2h_sent_at is not None
                    and booking.reminder_2h_confirmed_at is None
                ):
                    booking.reminder_2h_confirmed_at = now
                    changed = True
                    resolved_alert_kind = "2h"
                elif booking.reminder_24h_confirmed_at is None:
                    booking.reminder_24h_confirmed_at = now
                    changed = True
                    resolved_alert_kind = "24h"
            if changed:
                await db_session.commit()
                resolved_booking = booking
                resolved_confirmed_at = now
            confirmed = True
    if confirmed:
        callback_bot = getattr(callback, "bot", None) or getattr(callback.message, "bot", None)
        if (
            resolved_booking is not None
            and resolved_alert_kind is not None
            and resolved_confirmed_at is not None
            and callback_bot is not None
        ):
            tz_name = await get_str_setting(
                SettingRepository(db_session),
                key="tz",
                default="Europe/Moscow",
            )
            await resolve_admin_unconfirmed_alert_messages(
                callback_bot,
                db_session=db_session,
                booking=resolved_booking,
                reminder_kind=resolved_alert_kind,
                tz_name=tz_name,
                confirmed_at=resolved_confirmed_at,
            )
            await refresh_live_morning_summary_for_today(
                callback_bot,
                db_session=db_session,
                settings=settings,
                tz_name=tz_name,
                now_utc=resolved_confirmed_at,
            )
        await callback.answer(texts.REMINDER_ACK_NOTICE_TEXT)
        if callback.message is not None:
            button_configs = await load_all_button_configs(SettingRepository(db_session))
            await replace_inline_message_text(
                callback.message,
                texts.REMINDER_CONFIRMED_TEXT,
                reply_markup=(
                    build_reminder_confirmed_keyboard(
                        booking_id,
                        button_configs=button_configs,
                    )
                    if booking_id is not None
                    else None
                ),
            )
        return
    await callback.answer(texts.REMINDER_STALE_TEXT)


@router.callback_query(F.data.startswith("reminder:manage:"))
async def open_booking_from_reminder(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Open the concrete booking card referenced by a reminder CTA."""
    await callback.answer(texts.REMINDER_ACK_NOTICE_TEXT)
    if callback.message is None or callback.data is None:
        return

    from src.bot.handlers.client.my_bookings import show_booking_card_message

    booking_id = int(callback.data.rsplit(":", 1)[-1])
    await show_booking_card_message(
        callback.message,
        booking_id=booking_id,
        db_session=db_session,
        user=user,
        settings=settings,
        edit=True,
        prefix_text=texts.REMINDER_MANAGE_BOOKING_TEXT,
    )


@router.callback_query(F.data == "repeat_prompt:repeat_last")
@router.callback_query(F.data.startswith("repeat_prompt:repeat_last:"))
async def repeat_last_booking_from_prompt(
    callback: CallbackQuery,
    state,
    *,
    db_session: AsyncSession,
    user: User,
    settings: Settings,
) -> None:
    """Start a repeat booking from a repeat-prompt CTA."""
    await callback.answer(texts.REMINDER_ACK_NOTICE_TEXT)
    if callback.message is None:
        return

    from src.bot.handlers.client.booking_flow import start_repeat_booking_entry

    source_booking_id: int | None = None
    if callback.data and callback.data.count(":") >= 3:
        source_booking_id = int(callback.data.rsplit(":", 1)[-1])
    await start_repeat_booking_entry(
        callback.message,
        state,
        db_session=db_session,
        user=user,
        settings=settings,
        source_booking_id=source_booking_id,
        first_name=(callback.from_user.first_name if callback.from_user else None),
        replace_current=True,
    )


@router.callback_query(F.data.startswith("repeat_prompt:snooze:"))
async def snooze_repeat_prompt(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Snooze or stop repeat prompts for the current client."""
    await callback.answer(texts.REMINDER_ACK_NOTICE_TEXT)
    if callback.message is None or callback.data is None:
        return

    snooze_code = callback.data.rsplit(":", 1)[-1]
    now = datetime.now(UTC)
    if snooze_code == "1":
        user.repeat_prompt_snoozed_until = now + timedelta(weeks=1)
        text = texts.REPEAT_PROMPT_SNOOZE_1W_TEXT
    elif snooze_code == "2":
        user.repeat_prompt_snoozed_until = now + timedelta(weeks=2)
        text = texts.REPEAT_PROMPT_SNOOZE_2W_TEXT
    else:
        user.repeat_prompt_snoozed_until = now + timedelta(days=3650)
        text = texts.REPEAT_PROMPT_STOP_TEXT
    await db_session.commit()
    await replace_inline_message_text(callback.message, text)


@router.callback_query(F.data == "repeat_prompt:later")
async def repeat_prompt_later(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession | None = None,
    user: User | None = None,
) -> None:
    """Gracefully handle older «later» buttons that may remain in chat history."""
    await callback.answer(texts.REMINDER_ACK_NOTICE_TEXT)
    if callback.message is None:
        return

    if db_session is not None and user is not None:
        user.repeat_prompt_snoozed_until = datetime.now(UTC) + timedelta(weeks=1)
        await db_session.commit()
        await replace_inline_message_text(callback.message, texts.REPEAT_PROMPT_SNOOZE_1W_TEXT)
        return

    await replace_inline_message_text(callback.message, texts.REPEAT_PROMPT_LATER_TEXT)
