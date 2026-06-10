from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.db.models import User
from src.services.anti_abuse import BookingAttemptResult, attempt_booking_with_anti_abuse
from src.services.booking_completion import (
    ConfirmedBookingCompletionResult,
    finalize_confirmed_booking,
)


@dataclass(slots=True)
class DirectBookingFinalizeResult:
    """Outcome of a direct client booking confirmation flow."""

    attempt: BookingAttemptResult
    completion: ConfirmedBookingCompletionResult | None = None


async def finalize_direct_booking_attempt(
    db_session: AsyncSession,
    *,
    slot_id: int,
    base_service_id: int,
    user: User,
    addon_ids: list[int],
    design_photos: list[str],
    design_comment: str | None,
    payment_method: str | None,
    settings: Settings,
) -> DirectBookingFinalizeResult:
    """Run the shared orchestration for the final direct-booking step."""
    attempt = await attempt_booking_with_anti_abuse(
        db_session,
        slot_id=slot_id,
        base_service_id=base_service_id,
        user=user,
        addon_ids=addon_ids,
        design_photos=design_photos,
        design_comment=design_comment,
        payment_method=payment_method,
        tz_name=settings.tz,
    )

    if attempt.approval is not None:
        user.repeat_prompt_snoozed_until = None
        await db_session.commit()
        return DirectBookingFinalizeResult(attempt=attempt)

    result = attempt.confirm_result
    if (
        result is None
        or not result.ok
        or result.booking is None
        or result.slot is None
        or result.base_service is None
    ):
        return DirectBookingFinalizeResult(attempt=attempt)

    completion = await finalize_confirmed_booking(
        db_session,
        booking=result.booking,
        slot=result.slot,
        base_service=result.base_service,
        addons=result.addons,
        user=user,
        settings=settings,
        origin="direct",
        notify_client=True,
        sync_calendar=True,
    )
    return DirectBookingFinalizeResult(
        attempt=attempt,
        completion=completion,
    )
