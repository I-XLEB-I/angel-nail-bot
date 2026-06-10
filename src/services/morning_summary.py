"""Morning summary: send a daily digest to all admins at 08:00."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from aiogram import Bot

from src.config import Settings
from src.db.base import session_scope
from src.db.models import Booking, BookingStatus, utcnow
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.morning_summary_deliveries import MorningSummaryDeliveryRepository
from src.db.repositories.settings import SettingRepository
from src.services.booking import format_local_datetime
from src.services.observability import log_event
from src.services.runtime_settings import get_bool_setting, get_runtime_tz

logger = logging.getLogger(__name__)
SUMMARY_DIVIDER = "──────────────"

RUS_MONTHS_GENITIVE = (
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
)


def _format_duration(minutes: int) -> str:
    """Format a duration in minutes as a human string."""
    if minutes < 60:
        return f"{minutes} мин"
    hours = minutes // 60
    remainder = minutes % 60
    if remainder == 0:
        return f"{hours} ч"
    return f"{hours} ч {remainder} мин"


def _format_money(value: int) -> str:
    """Format integer rubles with thin grouping spaces."""
    return f"{value:,} ₽".replace(",", " ")


def _format_ru_count(value: int, forms: tuple[str, str, str]) -> str:
    """Format a Russian pluralized count."""
    mod10 = value % 10
    mod100 = value % 100
    if mod10 == 1 and mod100 != 11:
        form = forms[0]
    elif mod10 in (2, 3, 4) and mod100 not in (12, 13, 14):
        form = forms[1]
    else:
        form = forms[2]
    return f"{value} {form}"


def _format_local_day_title(local_today: date) -> str:
    """Format a local date like '18 мая'."""
    return f"{local_today.day} {RUS_MONTHS_GENITIVE[local_today.month - 1]}"


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Normalize SQLite-returned timestamps into explicit UTC datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _stage_snapshot(
    booking: Booking,
    *,
    stage: str,
    tz_name: str,
    now_utc: datetime,
) -> tuple[str, str]:
    """Return a semantic stage kind plus its compact display label."""
    if booking.slot is None:
        return "missing", "—"

    start_at = _ensure_utc(booking.slot.start_at)
    if start_at is None:
        return "missing", "—"

    if stage == "24h":
        sent_at = _ensure_utc(booking.reminder_24h_sent_at)
        confirmed_at = _ensure_utc(booking.reminder_24h_confirmed_at)
        alert_sent_at = _ensure_utc(booking.reminder_24h_unconfirmed_alert_sent_at)
        threshold = start_at - timedelta(hours=24)
    else:
        sent_at = _ensure_utc(booking.reminder_2h_sent_at)
        confirmed_at = _ensure_utc(booking.reminder_2h_confirmed_at)
        alert_sent_at = _ensure_utc(booking.reminder_2h_unconfirmed_alert_sent_at)
        threshold = start_at - timedelta(hours=2)

    if confirmed_at is not None:
        local_confirmed = format_local_datetime(confirmed_at, tz_name)
        return "confirmed", f"✅ {local_confirmed:%H:%M}"
    if alert_sent_at is not None:
        return "alert", "❌"
    if sent_at is not None:
        return "waiting", "⌛"
    if now_utc < threshold:
        return "early", "🕒"
    return "missing", "—"


def _format_stage_status(
    booking: Booking,
    *,
    stage: str,
    tz_name: str,
    now_utc: datetime,
) -> str:
    """Render one compact reminder-confirmation status for the admin summary."""
    return _stage_snapshot(
        booking,
        stage=stage,
        tz_name=tz_name,
        now_utc=now_utc,
    )[1]


def build_morning_summary_text(
    bookings: list[Booking],
    *,
    local_today: date,
    tz_name: str,
    now_utc: datetime | None = None,
) -> str:
    """Render the live admin summary for today's bookings and reminder statuses."""
    current_utc = now_utc or utcnow()
    total_revenue = sum(
        booking.fixed_price
        for booking in bookings
        if not booking.has_variable_price and booking.fixed_price > 0
    )
    variable_price_count = sum(1 for booking in bookings if booking.has_variable_price)
    waiting_count = 0
    alert_count = 0
    calm_count = 0

    next_upcoming_id: int | None = None
    for booking in bookings:
        if booking.slot is None:
            continue
        start_at = _ensure_utc(booking.slot.start_at)
        if start_at is None:
            continue
        if start_at >= current_utc:
            next_upcoming_id = booking.id
            break

    revenue_label = _format_money(total_revenue)
    if variable_price_count:
        revenue_label = f"{revenue_label} + {variable_price_count} уточнить"

    lines = [
        (
            f"🌸 {_format_local_day_title(local_today)} · "
            f"{_format_ru_count(len(bookings), ('запись', 'записи', 'записей'))} · "
            f"{revenue_label}"
        ),
        "",
    ]
    for booking in bookings:
        if booking.slot is None or booking.base_service is None or booking.client is None:
            continue
        local_dt = format_local_datetime(booking.slot.start_at, tz_name)
        duration = _format_duration(booking.base_service.duration_min)
        reminder_24h_kind, reminder_24h_status = _stage_snapshot(
            booking,
            stage="24h",
            tz_name=tz_name,
            now_utc=current_utc,
        )
        reminder_2h_kind, reminder_2h_status = _stage_snapshot(
            booking,
            stage="2h",
            tz_name=tz_name,
            now_utc=current_utc,
        )
        has_attention = "alert" in {reminder_24h_kind, reminder_2h_kind}
        is_waiting = "waiting" in {reminder_24h_kind, reminder_2h_kind}

        if has_attention:
            alert_count += 1
        elif is_waiting:
            waiting_count += 1
        else:
            calm_count += 1

        marker = "!"
        if not has_attention:
            marker = "▸" if booking.id == next_upcoming_id else " "

        username_suffix = (
            f" @{booking.client.tg_username}" if booking.client.tg_username else ""
        )
        lines.extend(
            [
                f"{marker} {local_dt:%H:%M}  {booking.client.display_name}{username_suffix}",
                f"  {booking.base_service.name}, {duration}",
                f"  24h: {reminder_24h_status}",
                f"  2h: {reminder_2h_status}",
                "",
            ]
        )

    lines.insert(
        2,
        f"{alert_count} не подтвердила · {waiting_count} ждём · {calm_count} спокойно",
    )
    lines.insert(3, "")
    lines.insert(4, SUMMARY_DIVIDER)
    lines.append(SUMMARY_DIVIDER)
    lines.append(f"🤍 К концу дня · {revenue_label}")

    return "\n".join(lines).rstrip()


def build_empty_morning_summary_text(*, local_today: date) -> str:
    """Render the fallback text when today's active bookings are gone."""
    return (
        f"🌸 {_format_local_day_title(local_today)} · 0 записей · 0 ₽\n\n"
        f"{SUMMARY_DIVIDER}\n\n"
        "Сегодня активных записей нет.\n\n"
        f"{SUMMARY_DIVIDER}\n"
        "🤍 Спокойный день"
    )


async def _send_or_update_summary_message(
    bot: Bot,
    *,
    delivery_repository: MorningSummaryDeliveryRepository,
    admin_tg_id: int,
    local_today: date,
    text: str,
    sent_at: datetime,
    force_new_message: bool = False,
) -> None:
    """Create or refresh one admin morning summary message."""
    delivery = await delivery_repository.get_by_admin_tg_id(admin_tg_id=admin_tg_id)
    if delivery is not None and not force_new_message:
        try:
            await bot.edit_message_text(
                chat_id=delivery.chat_id,
                message_id=delivery.message_id,
                text=text,
            )
            await delivery_repository.upsert(
                admin_tg_id=admin_tg_id,
                chat_id=delivery.chat_id,
                message_id=delivery.message_id,
                summary_local_date=local_today,
                sent_at=sent_at,
            )
            return
        except Exception:
            log_event(
                logger,
                logging.WARNING,
                "morning_summary_edit_failed",
                admin_tg_id=admin_tg_id,
                message_id=delivery.message_id,
                summary_local_date=local_today.isoformat(),
            )
    elif delivery is not None and force_new_message:
        try:
            await bot.delete_message(chat_id=delivery.chat_id, message_id=delivery.message_id)
        except Exception:
            log_event(
                logger,
                logging.WARNING,
                "morning_summary_delete_previous_failed",
                admin_tg_id=admin_tg_id,
                message_id=delivery.message_id,
                summary_local_date=local_today.isoformat(),
            )

    sent_message = await bot.send_message(chat_id=admin_tg_id, text=text)
    await delivery_repository.upsert(
        admin_tg_id=admin_tg_id,
        chat_id=sent_message.chat.id,
        message_id=sent_message.message_id,
        summary_local_date=local_today,
        sent_at=sent_at,
    )


async def refresh_live_morning_summary_for_today(
    bot: Bot,
    *,
    db_session,
    settings: Settings,
    tz_name: str | None = None,
    local_today: date | None = None,
    now_utc: datetime | None = None,
) -> None:
    """Update already-sent morning summary messages for the current local day."""
    settings_repository = SettingRepository(db_session)
    resolved_tz = tz_name or await get_runtime_tz(settings_repository, settings=settings)

    from zoneinfo import ZoneInfo  # noqa: PLC0415

    current_utc = now_utc or utcnow()
    today_local = local_today or datetime.now(ZoneInfo(resolved_tz)).date()
    delivery_repository = MorningSummaryDeliveryRepository(db_session)
    deliveries = await delivery_repository.list_for_local_date(summary_local_date=today_local)
    if not deliveries:
        return

    bookings = await BookingRepository(db_session).list_for_local_day(
        local_day=today_local,
        tz_name=resolved_tz,
    )
    text = (
        build_morning_summary_text(
            bookings,
            local_today=today_local,
            tz_name=resolved_tz,
            now_utc=current_utc,
        )
        if bookings
        else build_empty_morning_summary_text(local_today=today_local)
    )

    changed = False
    for delivery in deliveries:
        try:
            await bot.edit_message_text(
                chat_id=delivery.chat_id,
                message_id=delivery.message_id,
                text=text,
            )
            delivery.updated_at = current_utc
            changed = True
        except Exception:
            log_event(
                logger,
                logging.WARNING,
                "morning_summary_live_update_failed",
                admin_tg_id=delivery.admin_tg_id,
                message_id=delivery.message_id,
                summary_local_date=today_local.isoformat(),
            )
        if changed:
            await db_session.commit()


async def send_live_morning_summary_to_admin(
    bot: Bot,
    *,
    db_session,
    settings: Settings,
    admin_tg_id: int,
    local_today: date | None = None,
    now_utc: datetime | None = None,
) -> None:
    """Send a fresh live summary message for today and track it for future updates."""
    settings_repository = SettingRepository(db_session)
    resolved_tz = await get_runtime_tz(settings_repository, settings=settings)

    from zoneinfo import ZoneInfo  # noqa: PLC0415

    current_utc = now_utc or utcnow()
    today_local = local_today or datetime.now(ZoneInfo(resolved_tz)).date()
    bookings = await BookingRepository(db_session).list_for_local_day(
        local_day=today_local,
        tz_name=resolved_tz,
    )
    text = (
        build_morning_summary_text(
            bookings,
            local_today=today_local,
            tz_name=resolved_tz,
            now_utc=current_utc,
        )
        if bookings
        else build_empty_morning_summary_text(local_today=today_local)
    )
    delivery_repository = MorningSummaryDeliveryRepository(db_session)
    await _send_or_update_summary_message(
        bot,
        delivery_repository=delivery_repository,
        admin_tg_id=admin_tg_id,
        local_today=today_local,
        text=text,
        sent_at=current_utc,
        force_new_message=True,
    )
    await db_session.commit()


async def send_morning_summary(bot: Bot, settings: Settings) -> None:
    """Compose and send the daily booking digest to each admin.

    Skips sending when there are no bookings today, so the master doesn't get
    an empty message on days off.
    """
    admin_tg_ids = settings.admin_tg_id_set
    if not admin_tg_ids:
        return

    async with session_scope(settings) as session:
        settings_repository = SettingRepository(session)
        enabled = await get_bool_setting(
            settings_repository,
            key="morning_summary_enabled",
            default=True,
        )
        if not enabled:
            return

        tz_name = await get_runtime_tz(settings_repository, settings=settings)
        booking_repository = BookingRepository(session)

        from zoneinfo import ZoneInfo  # noqa: PLC0415

        local_today = datetime.now(ZoneInfo(tz_name)).date()
        bookings = await booking_repository.list_for_local_day(
            local_day=local_today,
            tz_name=tz_name,
        )
        if not bookings:
            return

        text = build_morning_summary_text(
            bookings,
            local_today=local_today,
            tz_name=tz_name,
            now_utc=utcnow(),
        )
        delivery_repository = MorningSummaryDeliveryRepository(session)
        sent_at = utcnow()
        try:
            for admin_tg_id in admin_tg_ids:
                await _send_or_update_summary_message(
                    bot,
                    delivery_repository=delivery_repository,
                    admin_tg_id=admin_tg_id,
                    local_today=local_today,
                    text=text,
                    sent_at=sent_at,
                )
            await session.commit()
        except Exception:
            logger.exception("Failed to send morning summary")
            await session.rollback()
