from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from aiogram import Bot

from src.config import Settings
from src.db.base import session_scope
from src.db.models import SlotStatus
from src.db.repositories.slots import SlotRepository
from src.services.google_workspace import build_calendar_service
from src.services.observability import log_event

logger = logging.getLogger(__name__)
GOOGLE_RETRY_DELAYS_SEC = (1, 3, 9)


@dataclass(slots=True)
class CalendarSmokeResult:
    """Result of a Google Calendar smoke test."""

    calendar_summary: str
    calendar_id: str
    event_id: str
    event_summary: str
    event_html_link: str
    start_at: str
    end_at: str


@dataclass(slots=True)
class CalendarClientInfo:
    """Client details that should be visible in Google Calendar events."""

    display_name: str
    tg_id: int
    tg_username: str | None = None
    phone: str | None = None
    note: str | None = None


@dataclass(slots=True)
class CalendarBookingInfo:
    """Booking details that should be mirrored into Google Calendar."""

    booking_id: int
    start_at: datetime
    duration_min: int
    base_service_name: str
    addon_names: list[str]
    client: CalendarClientInfo
    design_comment: str | None = None


@dataclass(slots=True)
class CalendarBlockRange:
    """External Google Calendar busy range that should block booking slots."""

    start_at: datetime
    end_at: datetime
    event_id: str


def get_calendar_metadata(settings: Settings) -> dict[str, Any]:
    """Return metadata for the configured Google Calendar."""
    if not settings.gcal_enabled:
        raise RuntimeError("Google Calendar is disabled in .env")
    if not settings.gcal_calendar_id:
        raise RuntimeError("GCAL_CALENDAR_ID is empty in .env")

    service = build_calendar_service(settings)
    return _execute_google_request(
        "calendar_metadata",
        lambda: service.calendars().get(calendarId=settings.gcal_calendar_id).execute(),
    )


def build_client_label(client: CalendarClientInfo) -> str:
    """Return a compact client label suitable for calendar summaries."""
    username_part = f" (@{client.tg_username})" if client.tg_username else ""
    return f"{client.display_name}{username_part}"


def build_calendar_summary_client_label(client: CalendarClientInfo) -> str:
    """Return the short client label used in calendar event summaries."""
    if client.tg_username:
        return f"@{client.tg_username}"
    return client.display_name


def build_client_description_lines(client: CalendarClientInfo) -> list[str]:
    """Return detailed client info lines for a calendar event description."""
    lines = [
        f"Клиент: {client.display_name}",
        f"Telegram ID: {client.tg_id}",
    ]
    if client.tg_username:
        lines.append(f"Telegram: @{client.tg_username}")
    if client.phone:
        lines.append(f"Телефон: {client.phone}")
    if client.note:
        lines.append(f"Комментарий: {client.note}")
    return lines


def build_smoke_test_event_body(
    settings: Settings,
    *,
    client: CalendarClientInfo | None = None,
) -> dict[str, Any]:
    """Build a short test event body in the configured local timezone."""
    tz = ZoneInfo(settings.tz)
    now_local = datetime.now(tz)

    # Create the event a bit in the future to avoid "already started" edge cases.
    start_local = (now_local + timedelta(minutes=15)).replace(second=0, microsecond=0)
    end_local = start_local + timedelta(minutes=15)

    summary = "Angel Nail Bot smoke test"
    description_lines = ["Test event created by the Telegram bot integration."]
    if client is not None:
        summary = f"Smoke test — {build_client_label(client)}"
        description_lines.extend(["", *build_client_description_lines(client)])

    return {
        "summary": summary,
        "description": "\n".join(description_lines),
        "start": {
            "dateTime": start_local.isoformat(),
            "timeZone": settings.tz,
        },
        "end": {
            "dateTime": end_local.isoformat(),
            "timeZone": settings.tz,
        },
    }


def create_smoke_test_event(
    settings: Settings,
    *,
    client: CalendarClientInfo | None = None,
) -> CalendarSmokeResult:
    """Create a short test event in the configured Google Calendar."""
    metadata = get_calendar_metadata(settings)
    service = build_calendar_service(settings)
    body = build_smoke_test_event_body(settings, client=client)
    event = _execute_google_request(
        "calendar_smoke_insert",
        lambda: (
            service.events()
            .insert(
                calendarId=settings.gcal_calendar_id,
                body=body,
            )
            .execute()
        ),
    )

    return CalendarSmokeResult(
        calendar_summary=metadata.get("summary", "<unknown>"),
        calendar_id=settings.gcal_calendar_id,
        event_id=event.get("id", ""),
        event_summary=event.get("summary", ""),
        event_html_link=event.get("htmlLink", ""),
        start_at=event.get("start", {}).get("dateTime", ""),
        end_at=event.get("end", {}).get("dateTime", ""),
    )


def build_booking_event_body(settings: Settings, booking: CalendarBookingInfo) -> dict[str, Any]:
    """Build a Google Calendar event body for a confirmed booking."""
    tz = ZoneInfo(settings.tz)
    start_at = booking.start_at
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=UTC)
    start_local = start_at.astimezone(tz)
    duration = max(booking.duration_min, 30)
    end_local = start_local + timedelta(minutes=duration)
    addon_suffix = f" + {', '.join(booking.addon_names)}" if booking.addon_names else ""

    description_lines = [
        *build_client_description_lines(booking.client),
        "",
        f"Услуга: {booking.base_service_name}{addon_suffix}",
    ]
    if booking.design_comment:
        description_lines.append(f"Комментарий к дизайну: {booking.design_comment}")

    return {
        "summary": f"Ногти {build_calendar_summary_client_label(booking.client)}",
        "description": "\n".join(description_lines),
        "start": {
            "dateTime": start_local.isoformat(),
            "timeZone": settings.tz,
        },
        "end": {
            "dateTime": end_local.isoformat(),
            "timeZone": settings.tz,
        },
        "extendedProperties": {
            "private": {
                "bot_booking_id": str(booking.booking_id),
            }
        },
    }


def parse_google_event_datetime(value: dict[str, Any], *, fallback_tz_name: str) -> datetime | None:
    """Parse a Google Calendar event start/end field into UTC."""
    date_time_raw = value.get("dateTime")
    if date_time_raw:
        parsed = datetime.fromisoformat(date_time_raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(value.get("timeZone") or fallback_tz_name))
        return parsed.astimezone(UTC)

    date_raw = value.get("date")
    if date_raw:
        parsed = datetime.fromisoformat(date_raw).replace(
            tzinfo=ZoneInfo(value.get("timeZone") or fallback_tz_name)
        )
        return parsed.astimezone(UTC)

    return None


def is_bot_managed_event(event: dict[str, Any]) -> bool:
    """Return whether the calendar event was created by the bot."""
    private = (event.get("extendedProperties") or {}).get("private") or {}
    return bool(private.get("bot_booking_id"))


def should_treat_as_external_block(event: dict[str, Any]) -> bool:
    """Return whether the event should block client booking slots."""
    if event.get("status") == "cancelled":
        return False
    if is_bot_managed_event(event):
        return False
    if event.get("transparency") == "transparent":
        return False
    return True


def build_external_block_ranges(
    events: list[dict[str, Any]],
    *,
    fallback_tz_name: str,
) -> list[CalendarBlockRange]:
    """Convert Google Calendar events into blocking UTC ranges."""
    ranges: list[CalendarBlockRange] = []
    for event in events:
        if not should_treat_as_external_block(event):
            continue

        start_at = parse_google_event_datetime(
            event.get("start") or {}, fallback_tz_name=fallback_tz_name
        )
        end_at = parse_google_event_datetime(
            event.get("end") or {}, fallback_tz_name=fallback_tz_name
        )
        if start_at is None or end_at is None or end_at <= start_at:
            continue

        ranges.append(
            CalendarBlockRange(
                start_at=start_at,
                end_at=end_at,
                event_id=str(event.get("id") or ""),
            )
        )
    return ranges


def list_calendar_events(
    settings: Settings,
    *,
    time_min: datetime,
    time_max: datetime,
) -> list[dict[str, Any]]:
    """Fetch Google Calendar events for the given time range."""
    if not settings.gcal_enabled:
        return []
    if not settings.gcal_calendar_id:
        raise RuntimeError("GCAL_CALENDAR_ID is empty in .env")

    service = build_calendar_service(settings)
    response = _execute_google_request(
        "calendar_list_events",
        lambda: (
            service.events()
            .list(
                calendarId=settings.gcal_calendar_id,
                timeMin=time_min.astimezone(UTC).isoformat(),
                timeMax=time_max.astimezone(UTC).isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        ),
    )
    return list(response.get("items", []))


def slot_is_blocked_by_ranges(
    slot_start_at: datetime, block_ranges: list[CalendarBlockRange]
) -> bool:
    """Return whether the slot start falls inside any blocking calendar range."""
    normalized_start = (
        slot_start_at if slot_start_at.tzinfo is not None else slot_start_at.replace(tzinfo=UTC)
    )
    return any(block.start_at <= normalized_start < block.end_at for block in block_ranges)


async def sync_external_calendar_blocks(bot: Bot, settings: Settings) -> None:
    """Sync external Google Calendar busy events into local slot blocks."""
    del bot
    if not settings.gcal_enabled:
        return

    now_utc = datetime.now(UTC)
    async with session_scope(settings) as session:
        slot_repository = SlotRepository(session)
        future_slots = await slot_repository.list_future(now_utc=now_utc)
        if not future_slots:
            return

        range_start = future_slots[0].start_at
        range_end = future_slots[-1].start_at + timedelta(days=1)
        try:
            events = list_calendar_events(
                settings,
                time_min=range_start,
                time_max=range_end,
            )
        except Exception:
            logger.exception("Failed to pull external Google Calendar blocks")
            raise

        block_ranges = build_external_block_ranges(events, fallback_tz_name=settings.tz)

        changed = False
        for slot in future_slots:
            should_block = slot_is_blocked_by_ranges(slot.start_at, block_ranges)
            if should_block and slot.status == SlotStatus.FREE:
                slot.status = SlotStatus.BLOCKED
                slot.blocked_by_gcal = True
                changed = True
                continue

            if not should_block and slot.status == SlotStatus.BLOCKED and slot.blocked_by_gcal:
                slot.status = SlotStatus.FREE
                slot.blocked_by_gcal = False
                changed = True

        if changed:
            await session.commit()


def create_booking_event(settings: Settings, booking: CalendarBookingInfo) -> str | None:
    """Create a Google Calendar event for a confirmed booking."""
    if not settings.gcal_enabled:
        return None
    if not settings.gcal_calendar_id:
        raise RuntimeError("GCAL_CALENDAR_ID is empty in .env")

    service = build_calendar_service(settings)
    event = _execute_google_request(
        "calendar_create_booking_event",
        lambda: (
            service.events()
            .insert(
                calendarId=settings.gcal_calendar_id,
                body=build_booking_event_body(settings, booking),
            )
            .execute()
        ),
    )
    return event.get("id")


def update_booking_event(
    settings: Settings,
    *,
    event_id: str,
    booking: CalendarBookingInfo,
) -> None:
    """Patch an existing Google Calendar event after a booking change."""
    if not settings.gcal_enabled or not event_id:
        return
    if not settings.gcal_calendar_id:
        raise RuntimeError("GCAL_CALENDAR_ID is empty in .env")

    service = build_calendar_service(settings)
    _execute_google_request(
        "calendar_update_booking_event",
        lambda: (
            service.events()
            .patch(
                calendarId=settings.gcal_calendar_id,
                eventId=event_id,
                body=build_booking_event_body(settings, booking),
            )
            .execute()
        ),
    )


def delete_booking_event(settings: Settings, *, event_id: str) -> None:
    """Delete a Google Calendar event linked to a booking."""
    if not settings.gcal_enabled or not event_id:
        return
    if not settings.gcal_calendar_id:
        raise RuntimeError("GCAL_CALENDAR_ID is empty in .env")

    service = build_calendar_service(settings)
    _execute_google_request(
        "calendar_delete_booking_event",
        lambda: service.events().delete(
            calendarId=settings.gcal_calendar_id,
            eventId=event_id,
        ).execute(),
    )


def _execute_google_request(action: str, request: Callable[[], Any]) -> Any:
    """Run one Google API request with exponential backoff and structured logs."""
    last_error: Exception | None = None
    for attempt, delay in enumerate((*GOOGLE_RETRY_DELAYS_SEC, None), start=1):
        try:
            return request()
        except Exception as exc:
            last_error = exc
            log_event(
                logger,
                logging.WARNING if delay is not None else logging.ERROR,
                "google_request_failed",
                action=action,
                attempt=attempt,
                error_type=exc.__class__.__name__,
                error=str(exc),
                retry_delay_sec=delay,
            )
            if delay is None:
                break
            time.sleep(delay)
    assert last_error is not None
    raise last_error
