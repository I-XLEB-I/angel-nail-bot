from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import (
    ApprovalRequest,
    ApprovalRequestKind,
    Booking,
    BookingCreatedVia,
    RateLimitEvent,
    User,
    utcnow,
)
from src.db.repositories.approvals import ApprovalRequestRepository
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.rate_limit_events import RateLimitEventRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.slots import SlotRepository
from src.services.booking import (
    ConfirmBookingResult,
    RescheduleBookingResult,
    confirm_booking,
    format_local_datetime,
    format_local_day_label,
    reschedule_booking,
)
from src.services.runtime_settings import get_int_setting

FREQUENT_BYPASS_VISITS = 5
REPEAT_CANCEL_COOLDOWN_MINUTES = 60
REPEAT_CANCEL_LOOKBACK_DAYS = 30
"""Minimum number of completed visits to bypass the FREQUENT_BOOKING approval gate.

Soло-мастеру не нужно вручную одобрять каждую повторную запись постоянной клиентки.
Strikes / cooldown / shadow_ban / pending_limit / requires_manual_approval gates
остаются и работают для всех — этот обход применяется только к
`min_days_between_bookings` правилу.
"""


@dataclass(slots=True)
class BookingAttemptResult:
    """Outcome of a client booking attempt after anti-abuse rules."""

    outcome: str
    confirm_result: ConfirmBookingResult | None = None
    approval: ApprovalRequest | None = None
    cooldown_minutes: int | None = None


@dataclass(slots=True)
class RescheduleAttemptResult:
    """Outcome of a client reschedule attempt after anti-abuse rules."""

    outcome: str
    reschedule_result: RescheduleBookingResult | None = None
    approval: ApprovalRequest | None = None


def normalize_start_at(value: datetime) -> datetime:
    """Normalize any datetime into timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def remaining_cooldown_minutes(
    *,
    event_created_at: datetime,
    now: datetime,
    cooldown_minutes: int,
) -> int:
    """Return the remaining cooldown in full client-facing minutes."""
    remaining = timedelta(minutes=cooldown_minutes) - (now - normalize_start_at(event_created_at))
    if remaining.total_seconds() <= 0:
        return 1
    return max(1, math.ceil(remaining.total_seconds() / 60))


async def resolve_cancel_cooldown(
    *,
    bookings: BookingRepository,
    events: RateLimitEventRepository,
    user_id: int,
    now: datetime,
    base_cooldown_minutes: int,
) -> tuple[RateLimitEvent | None, int]:
    """Return the active cancel cooldown event and its effective duration.

    The first recent cancellation keeps the regular pause. After the second
    cancellation within the recent booking cycle, the pause escalates to one hour.
    """
    cooldown_anchor = now - timedelta(days=REPEAT_CANCEL_LOOKBACK_DAYS)
    last_completed_at = await bookings.get_last_completed_slot_at(user_id)
    if last_completed_at is not None:
        cooldown_anchor = max(cooldown_anchor, normalize_start_at(last_completed_at))

    recent_cancel_count = await events.count_since(
        user_id=user_id,
        kind="cancel",
        since=cooldown_anchor,
    )
    effective_cooldown_minutes = (
        max(base_cooldown_minutes, REPEAT_CANCEL_COOLDOWN_MINUTES)
        if recent_cancel_count >= 2
        else base_cooldown_minutes
    )

    latest_cancel = await events.get_latest_since(
        user_id=user_id,
        kind="cancel",
        since=now - timedelta(minutes=effective_cooldown_minutes),
    )
    return latest_cancel, effective_cooldown_minutes


async def get_anti_abuse_settings(
    db_session: AsyncSession,
) -> dict[str, int]:
    """Load the integer runtime settings used by the anti-abuse rules."""
    repository = SettingRepository(db_session)
    return {
        "min_days_between_bookings": await get_int_setting(
            repository,
            key="min_days_between_bookings",
            default=17,
        ),
        "reschedule_min_hours_before": await get_int_setting(
            repository,
            key="reschedule_min_hours_before",
            default=48,
        ),
        "max_active_bookings_per_user": await get_int_setting(
            repository,
            key="max_active_bookings_per_user",
            default=1,
        ),
        "frequent_booking_bypass_visits": await get_int_setting(
            repository,
            key="frequent_booking_bypass_visits",
            default=FREQUENT_BYPASS_VISITS,
        ),
        "max_reschedules_per_booking": await get_int_setting(
            repository,
            key="max_reschedules_per_booking",
            default=2,
        ),
        "cancel_cooldown_minutes": await get_int_setting(
            repository,
            key="cancel_cooldown_minutes",
            default=30,
        ),
        "late_cancel_hours": await get_int_setting(
            repository,
            key="late_cancel_hours",
            default=4,
        ),
        "late_cancel_strike_limit": await get_int_setting(
            repository,
            key="late_cancel_strike_limit",
            default=3,
        ),
        "no_show_strike_limit": await get_int_setting(
            repository,
            key="no_show_strike_limit",
            default=2,
        ),
        "proxy_messages_per_hour": await get_int_setting(
            repository,
            key="proxy_messages_per_hour",
            default=5,
        ),
        "ask_master_per_day": await get_int_setting(
            repository,
            key="ask_master_per_day",
            default=3,
        ),
        "max_pending_approvals_per_user": await get_int_setting(
            repository,
            key="max_pending_approvals_per_user",
            default=5,
        ),
        "booking_attempt_limit_window_minutes": await get_int_setting(
            repository,
            key="booking_attempt_limit_window_minutes",
            default=10,
        ),
        "booking_attempt_limit_count": await get_int_setting(
            repository,
            key="booking_attempt_limit_count",
            default=5,
        ),
        "booking_attempt_pause_minutes": await get_int_setting(
            repository,
            key="booking_attempt_pause_minutes",
            default=30,
        ),
    }


def build_requested_slot_text(*, start_at: datetime, tz_name: str) -> tuple[str, datetime]:
    """Render a human-readable exact slot text for approval requests."""
    local_dt = format_local_datetime(start_at, tz_name)
    return (
        f"{format_local_day_label(local_dt.date())}, {local_dt.strftime('%H:%M')}",
        local_dt,
    )


async def record_rate_event(
    db_session: AsyncSession,
    *,
    user_id: int,
    kind: str,
    metadata: dict[str, object] | None = None,
    created_at: datetime | None = None,
) -> None:
    """Create one anti-abuse audit event."""
    await RateLimitEventRepository(db_session).create(
        user_id=user_id,
        kind=kind,
        metadata=metadata,
        created_at=created_at,
    )


async def attempt_booking_with_anti_abuse(
    db_session: AsyncSession,
    *,
    user: User,
    slot_id: int,
    base_service_id: int,
    addon_ids: list[int],
    design_photos: list[str],
    design_comment: str | None,
    tz_name: str,
    payment_method: str | None = None,
) -> BookingAttemptResult:
    """Apply anti-abuse rules before confirming a booking."""
    settings = await get_anti_abuse_settings(db_session)
    now = utcnow()
    approvals = ApprovalRequestRepository(db_session)
    events = RateLimitEventRepository(db_session)
    slots = SlotRepository(db_session)
    bookings = BookingRepository(db_session)
    slot = await slots.get_by_id(slot_id)
    if slot is None:
        return BookingAttemptResult(outcome="slot_unavailable")

    target_start_at = normalize_start_at(slot.start_at)

    if user.is_blocked:
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "blocked"},
            created_at=now,
        )
        await db_session.commit()
        return BookingAttemptResult(outcome="blocked")

    if user.is_shadow_banned:
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "shadow_banned"},
            created_at=now,
        )
        await db_session.commit()
        return BookingAttemptResult(outcome="shadow_banned")

    pause_since = now - timedelta(minutes=settings["booking_attempt_pause_minutes"])
    if await events.has_since(user_id=user.id, kind="booking_attempt_pause", since=pause_since):
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "attempt_limit"},
            created_at=now,
        )
        await db_session.commit()
        return BookingAttemptResult(outcome="attempt_limit")

    attempt_window_since = now - timedelta(minutes=settings["booking_attempt_limit_window_minutes"])
    recent_attempt_count = await events.count_since(
        user_id=user.id,
        kind="booking_attempt",
        since=attempt_window_since,
    )
    if recent_attempt_count >= settings["booking_attempt_limit_count"]:
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt_pause",
            metadata={
                "recent_attempts": recent_attempt_count,
                "window_minutes": settings["booking_attempt_limit_window_minutes"],
            },
            created_at=now,
        )
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "attempt_limit"},
            created_at=now,
        )
        await db_session.commit()
        return BookingAttemptResult(outcome="attempt_limit")

    latest_cancel, effective_cooldown_minutes = await resolve_cancel_cooldown(
        bookings=bookings,
        events=events,
        user_id=user.id,
        now=now,
        base_cooldown_minutes=settings["cancel_cooldown_minutes"],
    )
    if latest_cancel is not None:
        cooldown_minutes = remaining_cooldown_minutes(
            event_created_at=latest_cancel.created_at,
            now=now,
            cooldown_minutes=effective_cooldown_minutes,
        )
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "cooldown", "minutes_left": cooldown_minutes},
            created_at=now,
        )
        await db_session.commit()
        return BookingAttemptResult(outcome="cooldown", cooldown_minutes=cooldown_minutes)

    active_booking_count = await bookings.count_upcoming_active_for_client(user.id, now_utc=now)
    if active_booking_count >= settings["max_active_bookings_per_user"]:
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={
                "outcome": "active_limit",
                "active_booking_count": active_booking_count,
            },
            created_at=now,
        )
        await db_session.commit()
        return BookingAttemptResult(outcome="active_limit")

    pending_count = await approvals.count_pending_for_client(user.id)
    approval_kind: ApprovalRequestKind | None = None
    attempt_outcome: str | None = None
    if user.requires_manual_approval:
        approval_kind = ApprovalRequestKind.MANUAL_APPROVAL_REQUIRED
        attempt_outcome = "manual_approval"
    elif await bookings.has_relevant_booking_within_window(
        user.id,
        target_start_at=target_start_at,
        window_days=settings["min_days_between_bookings"],
    ):
        # Постоянные (>= FREQUENT_BYPASS_VISITS завершённых визитов) обходят
        # frequent-booking gate — для них повторная запись внутри окна
        # `min_days_between_bookings` подтверждается мгновенно. Новички и
        # пользователи с малым числом завершённых визитов всё ещё уходят в approval.
        completed_visits = await bookings.count_completed_for_client(user.id)
        if completed_visits < settings["frequent_booking_bypass_visits"]:
            approval_kind = ApprovalRequestKind.FREQUENT_BOOKING
            attempt_outcome = "frequent_booking"

    if approval_kind is not None:
        if pending_count >= settings["max_pending_approvals_per_user"]:
            await record_rate_event(
                db_session,
                user_id=user.id,
                kind="booking_attempt",
                metadata={"outcome": "pending_limit"},
                created_at=now,
            )
            await db_session.commit()
            return BookingAttemptResult(outcome="pending_limit")

        requested_text, local_dt = build_requested_slot_text(
            start_at=target_start_at, tz_name=tz_name
        )
        approval, approval_created = await approvals.create_or_reuse_pending(
            client_id=user.id,
            base_service_id=base_service_id,
            addons=addon_ids,
            design_photos=design_photos,
            design_comment=design_comment,
            payment_method=payment_method,
            requested_text=requested_text,
            preferred_day=local_dt.date(),
            kind=approval_kind,
        )
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="booking_attempt",
            metadata={
                "outcome": attempt_outcome,
                "approval_id": approval.id,
                "slot_id": slot_id,
            },
            created_at=now,
        )
        await db_session.commit()
        loaded_approval = await approvals.get_by_id(approval.id)
        return BookingAttemptResult(
            outcome=(attempt_outcome or "approval") if approval_created else "approval_existing",
            approval=loaded_approval,
        )

    result = await confirm_booking(
        db_session,
        client_id=user.id,
        slot_id=slot_id,
        base_service_id=base_service_id,
        addon_ids=addon_ids,
        design_photos=design_photos,
        design_comment=design_comment,
        payment_method=payment_method,
        created_via=BookingCreatedVia.BOT,
    )
    await record_rate_event(
        db_session,
        user_id=user.id,
        kind="booking_attempt",
        metadata={"outcome": "confirmed" if result.ok else (result.reason or "failed")},
        created_at=now,
    )
    await db_session.commit()
    return BookingAttemptResult(
        outcome="confirmed" if result.ok else (result.reason or "failed"),
        confirm_result=result,
    )


async def attempt_reschedule_with_anti_abuse(
    db_session: AsyncSession,
    *,
    user: User,
    booking: Booking,
    new_slot_id: int,
    tz_name: str,
) -> RescheduleAttemptResult:
    """Apply anti-abuse rules before directly rescheduling a booking."""
    settings = await get_anti_abuse_settings(db_session)
    now = utcnow()
    approvals = ApprovalRequestRepository(db_session)
    slots = SlotRepository(db_session)
    slot = await slots.get_by_id(new_slot_id)
    if slot is None:
        result = await reschedule_booking(db_session, booking=booking, new_slot_id=new_slot_id)
        return RescheduleAttemptResult(outcome="slot_unavailable", reschedule_result=result)

    target_start_at = normalize_start_at(slot.start_at)
    if user.is_shadow_banned:
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="reschedule_attempt",
            metadata={"outcome": "shadow_banned", "booking_id": booking.id},
            created_at=now,
        )
        await db_session.commit()
        return RescheduleAttemptResult(outcome="shadow_banned")

    if target_start_at - now < timedelta(hours=settings["reschedule_min_hours_before"]):
        approval_kind = ApprovalRequestKind.LATE_RESCHEDULE
        attempt_outcome = "late_reschedule"
    elif booking.reschedules_count >= settings["max_reschedules_per_booking"]:
        approval_kind = ApprovalRequestKind.MANUAL_APPROVAL_REQUIRED
        attempt_outcome = "too_many_reschedules"
    else:
        approval_kind = None
        attempt_outcome = None

    if approval_kind is not None:
        requested_text, local_dt = build_requested_slot_text(
            start_at=target_start_at, tz_name=tz_name
        )
        approval, approval_created = await approvals.create_or_reuse_pending(
            client_id=user.id,
            base_service_id=booking.base_service_id,
            addons=list(booking.addons),
            design_photos=list(booking.design_photos),
            design_comment=booking.design_comment,
            requested_text=requested_text,
            preferred_day=local_dt.date(),
            kind=approval_kind,
            related_booking_id=booking.id,
        )
        await record_rate_event(
            db_session,
            user_id=user.id,
            kind="reschedule_attempt",
            metadata={
                "outcome": attempt_outcome,
                "approval_id": approval.id,
                "booking_id": booking.id,
                "slot_id": new_slot_id,
            },
            created_at=now,
        )
        await db_session.commit()
        loaded_approval = await approvals.get_by_id(approval.id)
        return RescheduleAttemptResult(
            outcome=(attempt_outcome or "approval") if approval_created else "approval_existing",
            approval=loaded_approval,
        )

    result = await reschedule_booking(
        db_session,
        booking=booking,
        new_slot_id=new_slot_id,
    )
    await record_rate_event(
        db_session,
        user_id=user.id,
        kind="reschedule_attempt",
        metadata={
            "outcome": "rescheduled" if result.ok else (result.reason or "failed"),
            "booking_id": booking.id,
            "slot_id": new_slot_id,
        },
        created_at=now,
    )
    await db_session.commit()
    return RescheduleAttemptResult(
        outcome="rescheduled" if result.ok else (result.reason or "failed"),
        reschedule_result=result,
    )


def hours_before_booking(booking: Booking, *, now_utc: datetime | None = None) -> float | None:
    """Return the number of hours remaining before the booking start."""
    if booking.slot is None:
        return None
    current = normalize_start_at(now_utc or utcnow())
    start_at = normalize_start_at(booking.slot.start_at)
    return (start_at - current).total_seconds() / 3600
