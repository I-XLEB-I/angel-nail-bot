from __future__ import annotations

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.db.models import (
    ApprovalRequest,
    ApprovalRequestStatus,
    Booking,
    BookingStatus,
    Slot,
    utcnow,
)


def apply_force_majeure_cancellation(booking: Booking, *, reason: str) -> None:
    """Cancel one booking due to force-majeure and resolve its pending approvals."""
    booking.status = BookingStatus.CANCELLED_BY_MASTER
    booking.cancel_reason_code = "force_majeure"
    booking.cancel_reason_text = reason
    for approval in booking.approval_requests:
        if approval.status in {
            ApprovalRequestStatus.PENDING,
            ApprovalRequestStatus.OFFERED,
        }:
            approval.status = ApprovalRequestStatus.DECLINED
            approval.admin_response_text = reason
            approval.offered_slot_id = None
            approval.offered_start_at = None
            approval.resolved_at = utcnow()


def build_force_majeure_notice(reason: str) -> str:
    """Render the client-facing force-majeure cancellation notice."""
    return texts.FORCE_MAJEURE_CLIENT_NOTICE_PREFIX + reason


async def cancel_force_majeure_day(
    db_session: AsyncSession,
    *,
    local_day: date,
    tz_name: str,
    reason: str,
) -> list[int]:
    """Atomically cancel active bookings that still belong to the selected day."""
    tz = ZoneInfo(tz_name)
    day_start = datetime.combine(local_day, time.min, tzinfo=tz).astimezone(UTC)
    day_end = datetime.combine(local_day, time.max, tzinfo=tz).astimezone(UTC)
    current_slot_ids = select(Slot.id).where(
        Slot.start_at >= day_start,
        Slot.start_at <= day_end,
    )
    cancelled_at = utcnow()
    cancellation = await db_session.execute(
        update(Booking)
        .where(
            Booking.status.in_(
                [BookingStatus.PENDING_MASTER, BookingStatus.CONFIRMED]
            ),
            Booking.slot_id.in_(current_slot_ids),
        )
        .values(
            status=BookingStatus.CANCELLED_BY_MASTER,
            cancel_reason_code="force_majeure",
            cancel_reason_text=reason,
        )
        .returning(Booking.id)
        .execution_options(synchronize_session=False)
    )
    booking_ids = [int(booking_id) for booking_id in cancellation.scalars().all()]
    if booking_ids:
        await db_session.execute(
            update(ApprovalRequest)
            .where(
                ApprovalRequest.related_booking_id.in_(booking_ids),
                ApprovalRequest.status.in_(
                    [ApprovalRequestStatus.PENDING, ApprovalRequestStatus.OFFERED]
                ),
            )
            .values(
                status=ApprovalRequestStatus.DECLINED,
                admin_response_text=reason,
                offered_slot_id=None,
                offered_start_at=None,
                resolved_at=cancelled_at,
            )
            .execution_options(synchronize_session=False)
        )
    await db_session.commit()
    return booking_ids
