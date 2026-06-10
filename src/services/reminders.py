from __future__ import annotations

import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram import Bot

from src.bot import texts
from src.bot.handlers.client.address import (
    build_address_copy_text,
    build_address_map_url,
    build_address_text,
)
from src.bot.handlers.client.brand import send_brand_bot_message
from src.bot.keyboards.admin import build_admin_unconfirmed_alert_keyboard
from src.bot.keyboards.client import (
    build_postvisit_rating_keyboard,
    build_reminder_2h_keyboard,
    build_reminder_24h_keyboard,
    build_repeat_prompt_keyboard,
)
from src.config import Settings
from src.db.base import session_scope
from src.db.models import Booking, BookingStatus
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.reminder_admin_alert_deliveries import (
    ReminderAdminAlertDeliveryRepository,
)
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.booking import booking_needs_manual_resolution, format_local_datetime
from src.services.button_configs import load_all_button_configs
from src.services.morning_summary import refresh_live_morning_summary_for_today
from src.services.runtime_settings import get_bool_setting, get_int_setting, get_runtime_tz
from src.services.template_texts import ensure_late_policy_notice, render_template_text

logger = logging.getLogger(__name__)


async def render_runtime_template(
    template_repository: TemplateRepository,
    *,
    key: str,
    default_template: str,
    runtime_template: str,
    values: dict[str, str],
) -> str:
    """Use runtime copy by default, while preserving explicit admin overrides."""
    template = await template_repository.get_content_or_default(
        key,
        default_template,
    )
    source = runtime_template if template.strip() == default_template.strip() else template
    return render_template_text(source, values).strip()


async def build_24h_reminder_text(
    booking: Booking,
    *,
    template_repository: TemplateRepository,
    address_text: str,
    tz_name: str,
) -> str:
    """Render the 24h reminder text."""
    if booking.slot is None:
        raise ValueError("Booking slot is required for reminders")
    local_dt = format_local_datetime(booking.slot.start_at, tz_name)
    text = await render_runtime_template(
        template_repository,
        key="reminder_24h",
        default_template=texts.DEFAULT_REMINDER_24H_TEMPLATE,
        runtime_template=texts.REMINDER_24H_TEXT,
        values={
            "name": booking.client.display_name,
            "date": local_dt.strftime("%d.%m.%Y"),
            "time": local_dt.strftime("%H:%M"),
            "service": booking.base_service.name,
            "address": address_text,
            "address_short": build_address_copy_text(),
            "display_name": booking.client.display_name,
            "service_name": booking.base_service.name,
            "address_text": address_text,
        },
    )
    return ensure_late_policy_notice(text)


async def build_2h_reminder_text(
    booking: Booking,
    *,
    template_repository: TemplateRepository,
    tz_name: str,
) -> str:
    """Render the 2h reminder text."""
    if booking.slot is None:
        raise ValueError("Booking slot is required for reminders")
    local_dt = format_local_datetime(booking.slot.start_at, tz_name)
    text = await render_runtime_template(
        template_repository,
        key="reminder_2h",
        default_template=texts.DEFAULT_REMINDER_2H_TEMPLATE,
        runtime_template=texts.REMINDER_2H_TEXT,
        values={
            "name": booking.client.display_name,
            "date": local_dt.strftime("%d.%m.%Y"),
            "time": local_dt.strftime("%H:%M"),
            "service": booking.base_service.name,
            "service_name": booking.base_service.name,
        },
    )
    return ensure_late_policy_notice(text)


async def build_repeat_prompt_text(
    booking: Booking,
    *,
    template_repository: TemplateRepository,
) -> str:
    """Render the repeat-prompt text."""
    return await render_runtime_template(
        template_repository,
        key="repeat_prompt",
        default_template=texts.DEFAULT_REPEAT_PROMPT_TEMPLATE,
        runtime_template=texts.REPEAT_PROMPT_TEXT,
        values={
            "name": booking.client.display_name,
            "display_name": booking.client.display_name,
        },
    )


async def build_postvisit_text(template_repository: TemplateRepository) -> str:
    """Render the post-visit prompt text."""
    return await render_runtime_template(
        template_repository,
        key="postvisit",
        default_template=texts.DEFAULT_POSTVISIT_TEMPLATE,
        runtime_template=texts.POSTVISIT_PROMPT_TEXT,
        values={},
    )


async def send_due_reminders(bot: Bot, settings: Settings) -> None:
    """Send 24h and 2h reminders that are due right now."""
    now_utc = datetime.now(UTC)
    async with session_scope(settings) as session:
        settings_repository = SettingRepository(session)
        tz_name = await get_runtime_tz(settings_repository, settings=settings)
        reminder_24h_enabled = await get_bool_setting(
            settings_repository,
            key="reminder_24h_enabled",
            default=True,
        )
        reminder_2h_enabled = await get_bool_setting(
            settings_repository,
            key="reminder_2h_enabled",
            default=settings.feature_reminder_2h,
        )
        booking_repository = BookingRepository(session)
        template_repository = TemplateRepository(session)
        due_24h = (
            await booking_repository.list_due_24h_reminders(now_utc=now_utc)
            if reminder_24h_enabled
            else []
        )
        address_text = await build_address_text(session) if due_24h else ""
        button_configs_24h = (
            await load_all_button_configs(settings_repository) if due_24h else None
        )
        local_today = datetime.now(ZoneInfo(tz_name)).date()
        should_refresh_morning_summary = False

        for booking in due_24h:
            try:
                await send_brand_bot_message(
                    chat_id=booking.client.tg_id,
                    bot=bot,
                    caption=await build_24h_reminder_text(
                        booking,
                        template_repository=template_repository,
                        address_text=address_text,
                        tz_name=tz_name,
                    ),
                    template_key="reminder_24h",
                    reply_markup=build_reminder_24h_keyboard(
                        booking.id,
                        address_map_url=build_address_map_url(),
                        address_copy_text=build_address_copy_text(),
                        button_configs=button_configs_24h,
                    ),
                    parse_mode="HTML",
                )
                booking.reminder_24h_sent_at = now_utc
                await session.commit()
                if booking.slot is not None:
                    local_day = format_local_datetime(booking.slot.start_at, tz_name).date()
                    if local_day == local_today:
                        should_refresh_morning_summary = True
            except Exception:
                logger.exception("Failed to send 24h reminder for booking %s", booking.id)
                await session.rollback()

        if not reminder_2h_enabled:
            if should_refresh_morning_summary:
                await refresh_live_morning_summary_for_today(
                    bot,
                    db_session=session,
                    settings=settings,
                    tz_name=tz_name,
                    local_today=local_today,
                    now_utc=now_utc,
                )
            return

        # 2h reminders are a fresh pre-visit check and go out even if the client
        # already confirmed the visit at the 24h step.
        due_2h = await booking_repository.list_due_2h_reminders(now_utc=now_utc)
        button_configs = (
            await load_all_button_configs(settings_repository) if due_2h else None
        )
        for booking in due_2h:
            try:
                await send_brand_bot_message(
                    bot=bot,
                    chat_id=booking.client.tg_id,
                    caption=await build_2h_reminder_text(
                        booking,
                        template_repository=template_repository,
                        tz_name=tz_name,
                    ),
                    template_key="reminder_2h",
                    reply_markup=build_reminder_2h_keyboard(
                        booking.id,
                        button_configs=button_configs,
                    ),
                )
                booking.reminder_2h_sent_at = now_utc
                await session.commit()
                if booking.slot is not None:
                    local_day = format_local_datetime(booking.slot.start_at, tz_name).date()
                    if local_day == local_today:
                        should_refresh_morning_summary = True
            except Exception:
                logger.exception("Failed to send 2h reminder for booking %s", booking.id)
                await session.rollback()
        if should_refresh_morning_summary:
            await refresh_live_morning_summary_for_today(
                bot,
                db_session=session,
                settings=settings,
                tz_name=tz_name,
                local_today=local_today,
                now_utc=now_utc,
            )


async def mark_completed(bot: Bot, settings: Settings) -> None:
    """Mark due confirmed bookings as completed."""
    now_utc = datetime.now(UTC)
    async with session_scope(settings) as session:
        settings_repository = SettingRepository(session)
        tz_name = await get_runtime_tz(settings_repository, settings=settings)
        booking_repository = BookingRepository(session)
        due_bookings = await booking_repository.list_due_completion(now_utc=now_utc)
        if not due_bookings:
            return

        changed = False
        for booking in due_bookings:
            if booking_needs_manual_resolution(booking, now_utc=now_utc):
                continue
            booking.status = BookingStatus.COMPLETED
            changed = True
        if changed:
            await session.commit()
            await refresh_live_morning_summary_for_today(
                bot,
                db_session=session,
                settings=settings,
                tz_name=tz_name,
                local_today=datetime.now(ZoneInfo(tz_name)).date(),
                now_utc=now_utc,
            )


async def send_postvisit(bot: Bot, settings: Settings) -> None:
    """Send post-visit prompts to completed bookings after the configured delay."""
    now_utc = datetime.now(UTC)
    async with session_scope(settings) as session:
        settings_repository = SettingRepository(session)
        postvisit_enabled = await get_bool_setting(
            settings_repository,
            key="postvisit_enabled",
            default=settings.feature_postvisit_feedback,
        )
        if not postvisit_enabled:
            return

        delay_hours = await get_int_setting(
            settings_repository,
            key="postvisit_delay_hours",
            default=2,
        )
        booking_repository = BookingRepository(session)
        template_repository = TemplateRepository(session)
        postvisit_text = await build_postvisit_text(template_repository)
        due_bookings = await booking_repository.list_due_postvisit(
            now_utc=now_utc,
            delay_hours=delay_hours,
        )

        for booking in due_bookings:
            try:
                await send_brand_bot_message(
                    bot=bot,
                    chat_id=booking.client.tg_id,
                    caption=postvisit_text,
                    template_key="postvisit",
                    reply_markup=build_postvisit_rating_keyboard(booking.id),
                )
                booking.postvisit_sent_at = now_utc
                await session.commit()
            except Exception:
                logger.exception("Failed to send postvisit prompt for booking %s", booking.id)
                await session.rollback()


async def send_winback_prompts(bot: Bot, settings: Settings) -> None:
    """Send win-back messages to lapsed clients (no visit > N days, one-shot)."""
    now_utc = datetime.now(UTC)
    async with session_scope(settings) as session:
        settings_repository = SettingRepository(session)
        if await get_bool_setting(settings_repository, key="vacation_mode", default=False):
            return

        winback_enabled = await get_bool_setting(
            settings_repository,
            key="winback_enabled",
            default=True,
        )
        if not winback_enabled:
            return

        winback_days = await get_int_setting(
            settings_repository,
            key="winback_days",
            default=60,
        )
        booking_repository = BookingRepository(session)
        template_repository = TemplateRepository(session)

        template = await template_repository.get_content_or_default(
            "winback_lapsed",
            texts.DEFAULT_WINBACK_TEMPLATE,
        )
        due_users = await booking_repository.list_due_winback(
            now_utc=now_utc,
            winback_days=winback_days,
        )
        button_configs = (
            await load_all_button_configs(settings_repository) if due_users else None
        )

        for user in due_users:
            try:
                text = render_template_text(template, {"display_name": user.display_name}).strip()
                await send_brand_bot_message(
                    bot=bot,
                    chat_id=user.tg_id,
                    caption=text,
                    template_key="winback_lapsed",
                    reply_markup=build_repeat_prompt_keyboard(button_configs=button_configs),
                )
                user.winback_sent_at = now_utc
                await session.commit()
            except Exception:
                logger.exception("Failed to send win-back message to user %s", user.id)
                await session.rollback()


async def send_repeat_prompt(bot: Bot, settings: Settings) -> None:
    """Send repeat prompts to clients without active bookings."""
    if not settings.feature_repeat_prompt:
        return

    now_utc = datetime.now(UTC)
    async with session_scope(settings) as session:
        settings_repository = SettingRepository(session)
        if await get_bool_setting(settings_repository, key="vacation_mode", default=False):
            return

        repeat_weeks = await get_int_setting(
            settings_repository,
            key="repeat_prompt_weeks",
            default=3,
        )
        booking_repository = BookingRepository(session)
        template_repository = TemplateRepository(session)
        due_bookings = await booking_repository.list_due_repeat_prompts(
            now_utc=now_utc,
            repeat_weeks=repeat_weeks,
        )
        button_configs = (
            await load_all_button_configs(settings_repository) if due_bookings else None
        )

        for booking in due_bookings:
            try:
                await send_brand_bot_message(
                    bot=bot,
                    chat_id=booking.client.tg_id,
                    caption=await build_repeat_prompt_text(
                        booking,
                        template_repository=template_repository,
                    ),
                    template_key="repeat_prompt",
                    reply_markup=build_repeat_prompt_keyboard(
                        booking.id,
                        button_configs=button_configs,
                    ),
                )
                booking.repeat_prompt_sent_at = now_utc
                await session.commit()
            except Exception:
                logger.exception("Failed to send repeat prompt for booking %s", booking.id)
                await session.rollback()


def _format_hours_left(hours: float) -> str:
    """Render the «time remaining until booking» string in a human way."""
    if hours <= 0:
        return "уже скоро"
    if hours < 1:
        minutes = max(1, int(round(hours * 60)))
        return f"~{minutes} мин"
    rounded = round(hours * 2) / 2  # nearest half-hour
    if rounded.is_integer():
        return f"~{int(rounded)} ч"
    return f"~{rounded:.1f} ч"


def _build_phone_hint(phone: str | None) -> str:
    """Render the optional phone line that is embedded into admin alerts."""
    normalized = (phone or "").strip()
    if not normalized:
        return ""
    return f"\n\n📞 Номер: {normalized}"


def _build_admin_unconfirmed_alert_confirmed_text(
    booking: Booking,
    *,
    tz_name: str,
    confirmed_at: datetime,
) -> str:
    """Render the live-updated admin text after the client confirms the visit."""
    if booking.slot is None or booking.client is None:
        return texts.ADMIN_UNCONFIRMED_NO_SHOW_NOT_FOUND_TEXT
    local_slot = format_local_datetime(booking.slot.start_at, tz_name)
    local_confirmed = format_local_datetime(confirmed_at, tz_name)
    return texts.ADMIN_UNCONFIRMED_ALERT_CONFIRMED_TEXT.format(
        name=booking.client.display_name,
        time=local_slot.strftime("%d.%m %H:%M"),
        confirmed_at=local_confirmed.strftime("%H:%M"),
    )


async def resolve_admin_unconfirmed_alert_messages(
    bot: Bot,
    *,
    db_session,
    booking: Booking,
    reminder_kind: str,
    tz_name: str,
    confirmed_at: datetime,
) -> None:
    """Update unresolved admin alert cards after the client confirms the visit."""
    if booking.client is None:
        return
    repository = ReminderAdminAlertDeliveryRepository(db_session)
    deliveries = await repository.list_open_by_booking_kind(
        booking_id=booking.id,
        reminder_kind=reminder_kind,
    )
    if not deliveries:
        return

    text = _build_admin_unconfirmed_alert_confirmed_text(
        booking,
        tz_name=tz_name,
        confirmed_at=confirmed_at,
    )
    keyboard = build_admin_unconfirmed_alert_keyboard(
        booking_id=booking.id,
        user_id=booking.client.id,
        allow_no_show=False,
    )
    updated_any = False
    for delivery in deliveries:
        try:
            await bot.edit_message_text(
                chat_id=delivery.chat_id,
                message_id=delivery.message_id,
                text=text,
                reply_markup=keyboard,
            )
            delivery.resolved_at = confirmed_at
            updated_any = True
        except Exception:
            logger.exception(
                "Failed to update admin reminder alert message for booking %s",
                booking.id,
            )
    if updated_any:
        await db_session.commit()


async def send_unconfirmed_alerts(bot: Bot, settings: Settings) -> None:
    """Notify masters about bookings where reminder confirmations are missing.

    Runs alongside the other reminder jobs. There are two escalation stages:
    - a soft 24h warning if the client never tapped the day-before reminder
    - a stronger 2h warning close to the visit if the fresh 2h reminder is
      also ignored
    """
    now_utc = datetime.now(UTC)
    admin_tg_ids = settings.admin_tg_id_set
    if not admin_tg_ids:
        return

    async with session_scope(settings) as session:
        settings_repository = SettingRepository(session)
        alert_enabled = await get_bool_setting(
            settings_repository,
            key="unconfirmed_alert_enabled",
            default=True,
        )
        if not alert_enabled:
            return

        alert_delay_minutes = await get_int_setting(
            settings_repository,
            key="unconfirmed_alert_after_minutes",
            default=20,
        )
        alert_before_minutes = await get_int_setting(
            settings_repository,
            key="unconfirmed_alert_before_minutes",
            default=90,
        )
        tz_name = await get_runtime_tz(settings_repository, settings=settings)
        booking_repository = BookingRepository(session)
        due_24h_bookings = await booking_repository.list_due_24h_unconfirmed_alerts(
            now_utc=now_utc,
            alert_delay_minutes=alert_delay_minutes,
        )
        due_bookings = await booking_repository.list_due_2h_unconfirmed_alerts(
            now_utc=now_utc,
            alert_delay_minutes=alert_delay_minutes,
            alert_before_minutes=alert_before_minutes,
        )
        local_today = datetime.now(ZoneInfo(tz_name)).date()
        should_refresh_morning_summary = False

        for booking in due_24h_bookings:
            if booking.slot is None or booking.client is None:
                continue
            try:
                local_dt = format_local_datetime(booking.slot.start_at, tz_name)
                slot_start_utc = booking.slot.start_at
                if slot_start_utc.tzinfo is None:
                    slot_start_utc = slot_start_utc.replace(tzinfo=UTC)
                hours_left = (slot_start_utc - now_utc).total_seconds() / 3600
                sent_at = booking.reminder_24h_sent_at
                if sent_at is not None and sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=UTC)
                minutes_ago = (
                    int((now_utc - sent_at).total_seconds() // 60) if sent_at is not None else 0
                )
                text = texts.ADMIN_UNCONFIRMED_24H_ALERT_TEXT.format(
                    name=booking.client.display_name,
                    time=local_dt.strftime("%d.%m %H:%M"),
                    hours_left=_format_hours_left(hours_left),
                    minutes_ago=max(minutes_ago, 0),
                ) + _build_phone_hint(booking.client.phone)
                keyboard = build_admin_unconfirmed_alert_keyboard(
                    booking_id=booking.id,
                    user_id=booking.client.id,
                    allow_no_show=False,
                )
                delivery_repository = ReminderAdminAlertDeliveryRepository(session)
                for admin_tg_id in admin_tg_ids:
                    sent_message = await bot.send_message(
                        chat_id=admin_tg_id,
                        text=text,
                        reply_markup=keyboard,
                    )
                    await delivery_repository.upsert(
                        booking_id=booking.id,
                        admin_tg_id=admin_tg_id,
                        reminder_kind="24h",
                        chat_id=sent_message.chat.id,
                        message_id=sent_message.message_id,
                        sent_at=now_utc,
                    )
                booking.reminder_24h_unconfirmed_alert_sent_at = now_utc
                await session.commit()
                if booking.slot is not None:
                    local_day = format_local_datetime(booking.slot.start_at, tz_name).date()
                    if local_day == local_today:
                        should_refresh_morning_summary = True
            except Exception:
                logger.exception("Failed to send 24h unconfirmed alert for booking %s", booking.id)
                await session.rollback()

        for booking in due_bookings:
            if booking.slot is None or booking.client is None:
                continue
            try:
                local_dt = format_local_datetime(booking.slot.start_at, tz_name)
                slot_start_utc = booking.slot.start_at
                if slot_start_utc.tzinfo is None:
                    slot_start_utc = slot_start_utc.replace(tzinfo=UTC)
                hours_left = (slot_start_utc - now_utc).total_seconds() / 3600
                sent_at = booking.reminder_2h_sent_at
                if sent_at is not None and sent_at.tzinfo is None:
                    sent_at = sent_at.replace(tzinfo=UTC)
                minutes_ago = (
                    int((now_utc - sent_at).total_seconds() // 60) if sent_at is not None else 0
                )
                text = texts.ADMIN_UNCONFIRMED_ALERT_TEXT.format(
                    name=booking.client.display_name,
                    time=local_dt.strftime("%d.%m %H:%M"),
                    hours_left=_format_hours_left(hours_left),
                    minutes_ago=max(minutes_ago, 0),
                ) + _build_phone_hint(booking.client.phone)
                keyboard = build_admin_unconfirmed_alert_keyboard(
                    booking_id=booking.id,
                    user_id=booking.client.id,
                )
                delivery_repository = ReminderAdminAlertDeliveryRepository(session)
                for admin_tg_id in admin_tg_ids:
                    sent_message = await bot.send_message(
                        chat_id=admin_tg_id,
                        text=text,
                        reply_markup=keyboard,
                    )
                    await delivery_repository.upsert(
                        booking_id=booking.id,
                        admin_tg_id=admin_tg_id,
                        reminder_kind="2h",
                        chat_id=sent_message.chat.id,
                        message_id=sent_message.message_id,
                        sent_at=now_utc,
                    )
                booking.reminder_2h_unconfirmed_alert_sent_at = now_utc
                await session.commit()
                if booking.slot is not None:
                    local_day = format_local_datetime(booking.slot.start_at, tz_name).date()
                    if local_day == local_today:
                        should_refresh_morning_summary = True
            except Exception:
                logger.exception("Failed to send unconfirmed alert for booking %s", booking.id)
                await session.rollback()
        if should_refresh_morning_summary:
            await refresh_live_morning_summary_for_today(
                bot,
                db_session=session,
                settings=settings,
                tz_name=tz_name,
                local_today=local_today,
                now_utc=now_utc,
            )
