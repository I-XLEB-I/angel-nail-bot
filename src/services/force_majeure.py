from __future__ import annotations

from src.bot import texts
from src.db.models import ApprovalRequestStatus, Booking, BookingStatus, utcnow


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
