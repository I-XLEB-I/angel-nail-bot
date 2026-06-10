from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.db.models import Booking, Service, Slot, User
from src.services.booking import remember_client_preference_hints
from src.services.calendar_sync import (
    CalendarBookingInfo,
    CalendarClientInfo,
    create_booking_event,
)

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BookingClientConfirmationPayload:
    """Data needed to render one unified client booking confirmation."""

    chat_id: int
    booking_id: int | None
    display_name: str
    start_at: datetime
    base_service_name: str
    payment_method: str | None


@dataclass(slots=True)
class ConfirmedBookingCompletionResult:
    """Outcome of post-confirmation side effects for a confirmed booking."""

    booking_id: int
    origin: str
    calendar_event_id: str | None
    client_confirmation: BookingClientConfirmationPayload | None


def build_booking_client_confirmation_payload(
    *,
    booking: Booking,
    slot: Slot,
    base_service: Service,
    user: User,
    notify_client: bool,
) -> BookingClientConfirmationPayload | None:
    """Build the unified client confirmation payload when delivery is allowed."""
    if not notify_client or user.tg_id <= 0:
        return None
    return BookingClientConfirmationPayload(
        chat_id=user.tg_id,
        booking_id=booking.id,
        display_name=user.display_name,
        start_at=slot.start_at,
        base_service_name=base_service.name,
        payment_method=booking.payment_method,
    )


async def finalize_confirmed_booking(
    db_session: AsyncSession,
    *,
    booking: Booking,
    slot: Slot,
    base_service: Service,
    addons: list[Service],
    user: User,
    settings: Settings,
    origin: str,
    notify_client: bool,
    sync_calendar: bool,
) -> ConfirmedBookingCompletionResult:
    """Run shared post-confirmation side effects for a confirmed booking."""
    remember_client_preference_hints(user, design_comment=booking.design_comment)
    user.repeat_prompt_snoozed_until = None
    await db_session.commit()

    event_id: str | None = None
    if sync_calendar:
        try:
            event_id = create_booking_event(
                settings,
                CalendarBookingInfo(
                    booking_id=booking.id,
                    start_at=slot.start_at,
                    duration_min=base_service.duration_min
                    + sum(addon.duration_min for addon in addons),
                    base_service_name=base_service.name,
                    addon_names=[addon.name for addon in addons],
                    client=CalendarClientInfo(
                        display_name=user.display_name,
                        tg_id=user.tg_id,
                        tg_username=user.tg_username,
                        phone=user.phone,
                        note=user.note,
                    ),
                    design_comment=booking.design_comment,
                ),
            )
            if event_id:
                booking.gcal_event_id = event_id
                await db_session.commit()
        except Exception:
            logger.exception(
                "Failed to create Google Calendar event for booking %s via %s",
                booking.id,
                origin,
            )

    return ConfirmedBookingCompletionResult(
        booking_id=booking.id,
        origin=origin,
        calendar_event_id=event_id,
        client_confirmation=build_booking_client_confirmation_payload(
            booking=booking,
            slot=slot,
            base_service=base_service,
            user=user,
            notify_client=notify_client,
        ),
    )
