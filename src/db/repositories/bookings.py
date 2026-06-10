from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import Integer, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import (
    ApprovalRequest,
    Booking,
    BookingStatus,
    LateArrivalNotice,
    Service,
    Slot,
    SlotStatus,
    User,
)


@dataclass(slots=True)
class ClientBookingStats:
    """Aggregated booking stats for one client card."""

    total_visits: int
    total_cancels: int
    no_shows: int
    average_check: int
    total_spent: int = 0
    favorite_service_name: str | None = None


@dataclass(slots=True)
class BookingPeriodStats:
    """Aggregated booking stats for the admin dashboard."""

    total_bookings: int
    completed_count: int
    cancelled_by_client_count: int
    cancelled_by_master_count: int
    no_show_count: int
    revenue: int
    new_clients: int
    cancel_reason_counts: dict[str, int]
    top_services: list[tuple[str, int]]


class BookingRepository:
    """Repository for bookings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def has_visible_bookings(self, client_id: int) -> bool:
        """Return whether the client has bookings that should unlock the menu item."""
        visible_statuses = [
            BookingStatus.PENDING_MASTER,
            BookingStatus.CONFIRMED,
            BookingStatus.COMPLETED,
        ]
        result = await self.session.execute(
            select(func.count(Booking.id)).where(
                Booking.client_id == client_id,
                Booking.status.in_(visible_statuses),
            )
        )
        return bool(result.scalar_one())

    async def list_active_for_client(self, client_id: int) -> list[Booking]:
        """Return active client bookings ordered by their ближайшее время."""
        result = await self.session.execute(
            select(Booking)
            .outerjoin(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
            )
            .where(
                Booking.client_id == client_id,
                Booking.status.in_(
                    [
                        BookingStatus.PENDING_MASTER,
                        BookingStatus.CONFIRMED,
                    ]
                ),
            )
            .order_by(Slot.start_at.is_(None), Slot.start_at, Booking.id)
        )
        bookings = list(result.scalars().unique().all())
        now_utc = datetime.now(UTC)

        def booking_sort_key(booking: Booking) -> tuple[int, float, int]:
            if booking.slot is None or booking.slot.start_at is None:
                return (2, float("inf"), booking.id)
            start_at = booking.slot.start_at
            if start_at.tzinfo is None:
                start_at = start_at.replace(tzinfo=UTC)
            timestamp = start_at.timestamp()
            if start_at >= now_utc:
                return (0, timestamp, booking.id)
            return (1, -timestamp, booking.id)

        return sorted(bookings, key=booking_sort_key)

    async def count_upcoming_active_for_client(
        self,
        client_id: int,
        *,
        now_utc: datetime,
    ) -> int:
        """Return the number of upcoming active bookings for one client."""
        result = await self.session.execute(
            select(func.count(Booking.id))
            .join(Slot, Slot.id == Booking.slot_id)
            .where(
                Booking.client_id == client_id,
                Booking.status.in_(
                    [
                        BookingStatus.PENDING_MASTER,
                        BookingStatus.CONFIRMED,
                    ]
                ),
                Slot.start_at >= now_utc,
            )
        )
        return int(result.scalar_one() or 0)

    async def list_recent_completed_for_client(
        self,
        client_id: int,
        *,
        limit: int = 3,
    ) -> list[Booking]:
        """Return the most recent completed client bookings."""
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
            )
            .where(
                Booking.client_id == client_id,
                Booking.status == BookingStatus.COMPLETED,
            )
            .order_by(Slot.start_at.desc(), Booking.id.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def get_client_booking(self, booking_id: int, client_id: int) -> Booking | None:
        """Return one booking that belongs to the given client."""
        result = await self.session.execute(
            select(Booking)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
            )
            .where(
                Booking.id == booking_id,
                Booking.client_id == client_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, booking_id: int) -> Booking | None:
        """Return a booking with its main relationships."""
        result = await self.session.execute(
            select(Booking)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
                selectinload(Booking.client),
            )
            .where(Booking.id == booking_id)
        )
        return result.scalar_one_or_none()

    async def get_by_slot_id(self, slot_id: int) -> Booking | None:
        """Return the booking currently attached to a slot."""
        result = await self.session.execute(
            select(Booking)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
                selectinload(Booking.client),
            )
            .where(Booking.slot_id == slot_id)
            .order_by(Booking.id.desc())
        )
        return result.scalars().first()

    async def list_for_range(
        self,
        start_utc: datetime,
        end_utc: datetime,
        *,
        include_cancelled: bool = False,
    ) -> list[Booking]:
        """Return bookings whose slots are inside a UTC datetime range."""
        statuses = [
            BookingStatus.PENDING_MASTER,
            BookingStatus.CONFIRMED,
            BookingStatus.COMPLETED,
            BookingStatus.NO_SHOW,
        ]
        if include_cancelled:
            statuses.extend(
                [
                    BookingStatus.CANCELLED_BY_CLIENT,
                    BookingStatus.CANCELLED_BY_MASTER,
                ]
            )
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
                selectinload(Booking.client),
            )
            .where(
                Booking.status.in_(statuses),
                Slot.start_at >= start_utc,
                Slot.start_at <= end_utc,
            )
            .order_by(Slot.start_at, Booking.id)
        )
        return list(result.scalars().unique().all())

    async def delete_bookings(self, bookings: list[Booking]) -> int:
        """Delete concrete bookings and clean up their dependent rows."""
        booking_ids = [booking.id for booking in bookings]
        if not booking_ids:
            return 0

        slot_ids = [booking.slot_id for booking in bookings if booking.slot_id is not None]

        await self.session.execute(
            delete(LateArrivalNotice).where(LateArrivalNotice.booking_id.in_(booking_ids))
        )
        await self.session.execute(
            delete(ApprovalRequest).where(ApprovalRequest.related_booking_id.in_(booking_ids))
        )
        if slot_ids:
            await self.session.execute(
                update(Slot).where(Slot.id.in_(slot_ids)).values(status=SlotStatus.FREE)
            )
        await self.session.execute(delete(Booking).where(Booking.id.in_(booking_ids)))
        await self.session.flush()
        return len(booking_ids)

    async def list_recent_for_client_card(
        self,
        client_id: int,
        *,
        limit: int = 5,
    ) -> list[Booking]:
        """Return recent bookings for the admin client card."""
        result = await self.session.execute(
            select(Booking)
            .outerjoin(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
            )
            .where(Booking.client_id == client_id)
            .order_by(func.coalesce(Slot.start_at, Booking.created_at).desc(), Booking.id.desc())
            .limit(limit)
        )
        return list(result.scalars().unique().all())

    async def get_client_card_stats(self, client_id: int) -> ClientBookingStats:
        """Return the aggregated stats shown on the admin client card."""
        total_visits = await self.session.scalar(
            select(func.count(Booking.id)).where(
                Booking.client_id == client_id,
                Booking.status == BookingStatus.COMPLETED,
            )
        )
        total_cancels = await self.session.scalar(
            select(func.count(Booking.id)).where(
                Booking.client_id == client_id,
                Booking.status.in_(
                    [
                        BookingStatus.CANCELLED_BY_CLIENT,
                        BookingStatus.CANCELLED_BY_MASTER,
                    ]
                ),
            )
        )
        no_shows = await self.session.scalar(
            select(func.count(Booking.id)).where(
                Booking.client_id == client_id,
                Booking.status == BookingStatus.NO_SHOW,
            )
        )
        average_check_raw = await self.session.scalar(
            select(func.avg(Booking.fixed_price)).where(
                Booking.client_id == client_id,
                Booking.status == BookingStatus.COMPLETED,
            )
        )
        total_spent_raw = await self.session.scalar(
            select(func.sum(Booking.fixed_price)).where(
                Booking.client_id == client_id,
                Booking.status == BookingStatus.COMPLETED,
            )
        )
        favorite_service_result = await self.session.execute(
            select(Service.name, func.count(Booking.id))
            .join(Booking, Booking.base_service_id == Service.id)
            .where(
                Booking.client_id == client_id,
                Booking.status == BookingStatus.COMPLETED,
            )
            .group_by(Service.id, Service.name)
            .order_by(func.count(Booking.id).desc(), Service.name)
            .limit(1)
        )
        favorite_service_row = favorite_service_result.first()
        return ClientBookingStats(
            total_visits=int(total_visits or 0),
            total_cancels=int(total_cancels or 0),
            no_shows=int(no_shows or 0),
            average_check=int(round(float(average_check_raw or 0))),
            total_spent=int(total_spent_raw or 0),
            favorite_service_name=str(favorite_service_row[0]) if favorite_service_row else None,
        )

    async def get_completed_booking_for_client(
        self,
        booking_id: int,
        client_id: int,
    ) -> Booking | None:
        """Return one completed booking that belongs to the given client."""
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
                selectinload(Booking.client),
            )
            .where(
                Booking.id == booking_id,
                Booking.client_id == client_id,
                Booking.status == BookingStatus.COMPLETED,
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_completed_for_client(self, client_id: int) -> Booking | None:
        """Return the latest completed booking for a client."""
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
                selectinload(Booking.client),
            )
            .where(
                Booking.client_id == client_id,
                Booking.status == BookingStatus.COMPLETED,
            )
            .order_by(Slot.start_at.desc(), Booking.id.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_client_confirmation_stats(self, client_id: int) -> tuple[int, int]:
        """Return (confirmed_reminders, total_reminders) for one client."""
        result = await self.session.execute(
            select(
                func.count(Booking.id),
                func.sum(
                    (
                        Booking.reminder_24h_confirmed_at.is_not(None)
                        | Booking.reminder_2h_confirmed_at.is_not(None)
                    ).cast(Integer)
                ),
            ).where(
                Booking.client_id == client_id,
                (
                    Booking.reminder_24h_sent_at.is_not(None)
                    | Booking.reminder_2h_sent_at.is_not(None)
                ),
            )
        )
        total_raw, confirmed_raw = result.one()
        return int(confirmed_raw or 0), int(total_raw or 0)

    async def count_completed_for_client(self, client_id: int) -> int:
        """Return the number of completed visits for the client.

        Used by anti-abuse rules to let regular clients (with several past visits)
        bypass the frequent-booking approval gate.
        """
        result = await self.session.scalar(
            select(func.count(Booking.id)).where(
                Booking.client_id == client_id,
                Booking.status == BookingStatus.COMPLETED,
            )
        )
        return int(result or 0)

    async def has_relevant_booking_within_window(
        self,
        client_id: int,
        *,
        target_start_at: datetime,
        window_days: int,
    ) -> bool:
        """Return whether a client-owned booking exists close to the target datetime."""
        window = timedelta(days=window_days)
        result = await self.session.execute(
            select(func.count(Booking.id))
            .join(Slot, Slot.id == Booking.slot_id)
            .where(
                Booking.client_id == client_id,
                Booking.status.in_(
                    [
                        BookingStatus.CONFIRMED,
                        BookingStatus.COMPLETED,
                        BookingStatus.CANCELLED_BY_CLIENT,
                    ]
                ),
                Slot.start_at >= target_start_at - window,
                Slot.start_at <= target_start_at + window,
            )
        )
        return bool(result.scalar_one())

    async def list_due_24h_reminders(self, *, now_utc: datetime) -> list[Booking]:
        """Return confirmed bookings that should receive the 24h reminder."""
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
                selectinload(Booking.client),
            )
            .where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.reminder_24h_sent_at.is_(None),
                Slot.start_at >= now_utc + timedelta(hours=23),
                Slot.start_at <= now_utc + timedelta(hours=25),
            )
            .order_by(Slot.start_at, Booking.id)
        )
        return list(result.scalars().unique().all())

    async def list_due_2h_reminders(self, *, now_utc: datetime) -> list[Booking]:
        """Return confirmed bookings that should receive the 2h reminder.

        The scheduler runs every 5 minutes, so we use a tight window around the
        2-hour mark instead of a wide 1-3 hour bucket. This keeps the "2h"
        reminder honest for both clients and the live admin status.
        """
        target_start_at = now_utc + timedelta(hours=2)
        window = timedelta(minutes=5)
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
                selectinload(Booking.client),
            )
            .where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.reminder_2h_sent_at.is_(None),
                Slot.start_at >= target_start_at - window,
                Slot.start_at <= target_start_at + window,
            )
            .order_by(Slot.start_at, Booking.id)
        )
        return list(result.scalars().unique().all())

    async def list_due_24h_unconfirmed_alerts(
        self,
        *,
        now_utc: datetime,
        alert_delay_minutes: int,
    ) -> list[Booking]:
        """Return bookings whose 24h reminder still has no client confirmation.

        This is an early-warning signal for the master. It fires once after the
        configured grace period, only before the 2h reminder stage begins.
        """
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
                selectinload(Booking.client),
            )
            .where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.reminder_24h_sent_at.is_not(None),
                Booking.reminder_24h_sent_at <= now_utc - timedelta(minutes=alert_delay_minutes),
                Booking.reminder_24h_confirmed_at.is_(None),
                Booking.reminder_24h_unconfirmed_alert_sent_at.is_(None),
                Booking.reminder_2h_sent_at.is_(None),
                Slot.start_at > now_utc + timedelta(hours=3),
            )
            .order_by(Slot.start_at, Booking.id)
        )
        return list(result.scalars().unique().all())

    async def list_due_2h_unconfirmed_alerts(
        self,
        *,
        now_utc: datetime,
        alert_delay_minutes: int,
        alert_before_minutes: int,
    ) -> list[Booking]:
        """Return confirmed bookings whose 2h reminder went unanswered.

        Selects bookings where:
        - the visit is already inside the final `alert_before_minutes` window,
        - 2h reminder was sent at least `alert_delay_minutes` minutes ago,
        - client still hasn't confirmed the fresh 2h reminder,
        - admin alert hasn't been dispatched yet,
        - booking is still confirmed and the slot hasn't started.
        """
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
                selectinload(Booking.client),
            )
            .where(
                Booking.status == BookingStatus.CONFIRMED,
                Booking.reminder_2h_sent_at.is_not(None),
                Booking.reminder_2h_sent_at <= now_utc - timedelta(minutes=alert_delay_minutes),
                Booking.reminder_2h_confirmed_at.is_(None),
                Booking.reminder_2h_unconfirmed_alert_sent_at.is_(None),
                Slot.start_at <= now_utc + timedelta(minutes=alert_before_minutes),
                Slot.start_at > now_utc,
            )
            .order_by(Slot.start_at, Booking.id)
        )
        return list(result.scalars().unique().all())

    async def list_due_postvisit(
        self,
        *,
        now_utc: datetime,
        delay_hours: int,
    ) -> list[Booking]:
        """Return completed bookings that should receive the post-visit prompt."""
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
                selectinload(Booking.client),
            )
            .where(
                Booking.status == BookingStatus.COMPLETED,
                Booking.postvisit_sent_at.is_(None),
                Slot.start_at <= now_utc - timedelta(hours=delay_hours),
            )
            .order_by(Slot.start_at, Booking.id)
        )
        return list(result.scalars().unique().all())

    async def list_due_repeat_prompts(
        self,
        *,
        now_utc: datetime,
        repeat_weeks: int,
    ) -> list[Booking]:
        """Return the latest eligible completed booking for each client."""
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .join(User, User.id == Booking.client_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.base_service),
                selectinload(Booking.client),
            )
            .where(
                Booking.status == BookingStatus.COMPLETED,
                User.is_blocked.is_(False),
                User.is_shadow_banned.is_(False),
            )
            .order_by(Booking.client_id, Slot.start_at.desc(), Booking.id.desc())
        )
        candidates = list(result.scalars().unique().all())

        latest_by_client: dict[int, Booking] = {}
        for booking in candidates:
            latest_by_client.setdefault(booking.client_id, booking)

        if not latest_by_client:
            return []

        active_client_ids_result = await self.session.execute(
            select(Booking.client_id)
            .where(Booking.client_id.in_(latest_by_client.keys()))
            .where(Booking.status.in_([BookingStatus.PENDING_MASTER, BookingStatus.CONFIRMED]))
            .group_by(Booking.client_id)
        )
        active_client_ids = set(active_client_ids_result.scalars().all())
        snoozed_client_ids_result = await self.session.execute(
            select(User.id).where(
                User.id.in_(latest_by_client.keys()),
                User.repeat_prompt_snoozed_until.is_not(None),
                User.repeat_prompt_snoozed_until > now_utc,
            )
        )
        snoozed_client_ids = set(snoozed_client_ids_result.scalars().all())
        cutoff = now_utc - timedelta(weeks=repeat_weeks)
        return [
            booking
            for client_id, booking in latest_by_client.items()
            if client_id not in active_client_ids
            and client_id not in snoozed_client_ids
            and booking.repeat_prompt_sent_at is None
            and booking.slot is not None
            and (
                booking.slot.start_at
                if booking.slot.start_at.tzinfo is not None
                else booking.slot.start_at.replace(tzinfo=UTC)
            )
            <= cutoff
        ]

    async def list_due_winback(
        self,
        *,
        now_utc: datetime,
        winback_days: int,
    ) -> list[User]:
        """Return users eligible for a win-back message.

        Criteria: has at least one completed booking, last completed booking was
        more than ``winback_days`` days ago, no active/pending bookings, and
        ``User.winback_sent_at`` is still NULL (one-shot per lifetime).
        """
        cutoff = now_utc - timedelta(days=winback_days)
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .join(User, User.id == Booking.client_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.client),
            )
            .where(
                Booking.status == BookingStatus.COMPLETED,
                User.is_blocked.is_(False),
                User.is_shadow_banned.is_(False),
            )
            .order_by(Booking.client_id, Slot.start_at.desc(), Booking.id.desc())
        )
        candidates = list(result.scalars().unique().all())

        latest_by_client: dict[int, Booking] = {}
        for booking in candidates:
            latest_by_client.setdefault(booking.client_id, booking)

        if not latest_by_client:
            return []

        active_client_ids_result = await self.session.execute(
            select(Booking.client_id)
            .where(Booking.client_id.in_(latest_by_client.keys()))
            .where(Booking.status.in_([BookingStatus.PENDING_MASTER, BookingStatus.CONFIRMED]))
            .group_by(Booking.client_id)
        )
        active_client_ids = set(active_client_ids_result.scalars().all())
        return [
            booking.client
            for client_id, booking in latest_by_client.items()
            if client_id not in active_client_ids
            and booking.client is not None
            and booking.client.winback_sent_at is None
            and booking.slot is not None
            and (
                booking.slot.start_at
                if booking.slot.start_at.tzinfo is not None
                else booking.slot.start_at.replace(tzinfo=UTC)
            )
            <= cutoff
        ]

    async def get_last_completed_slot_at(self, client_id: int) -> datetime | None:
        """Return the start time of the most recent completed booking for a client."""
        result = await self.session.execute(
            select(Slot.start_at)
            .join(Booking, Booking.slot_id == Slot.id)
            .where(
                Booking.client_id == client_id,
                Booking.status == BookingStatus.COMPLETED,
            )
            .order_by(Slot.start_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_upcoming_active_days(
        self,
        *,
        now_utc: datetime,
        tz_name: str,
        max_days: int = 14,
    ) -> list[date]:
        """Return local dates (up to max_days ahead) that have active bookings."""
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        tz = ZoneInfo(tz_name)
        result = await self.session.execute(
            select(Slot.start_at)
            .join(Booking, Booking.slot_id == Slot.id)
            .where(
                Booking.status.in_([BookingStatus.PENDING_MASTER, BookingStatus.CONFIRMED]),
                Slot.start_at >= now_utc,
                Slot.start_at <= now_utc + timedelta(days=max_days),
            )
            .order_by(Slot.start_at)
        )
        seen: set[date] = set()
        days: list[date] = []
        for (start_at,) in result:
            if start_at.tzinfo is None:
                start_at = start_at.replace(tzinfo=UTC)
            local_date = start_at.astimezone(tz).date()
            if local_date not in seen:
                seen.add(local_date)
                days.append(local_date)
        return days

    async def list_confirmed_for_day(
        self,
        *,
        local_day: date,
        tz_name: str,
    ) -> list[Booking]:
        """Return CONFIRMED bookings for a given local day, with client + service loaded."""
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        tz = ZoneInfo(tz_name)
        day_start = datetime.combine(local_day, time.min, tzinfo=tz).astimezone(UTC)
        day_end = datetime.combine(local_day, time.max, tzinfo=tz).astimezone(UTC)

        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.client),
                selectinload(Booking.base_service),
            )
            .where(
                Booking.status == BookingStatus.CONFIRMED,
                Slot.start_at >= day_start,
                Slot.start_at <= day_end,
            )
            .order_by(Slot.start_at)
        )
        return list(result.scalars().unique().all())

    async def list_active_for_day(
        self,
        *,
        local_day: date,
        tz_name: str,
    ) -> list[Booking]:
        """Return PENDING_MASTER + CONFIRMED bookings for a given local day."""
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        tz = ZoneInfo(tz_name)
        day_start = datetime.combine(local_day, time.min, tzinfo=tz).astimezone(UTC)
        day_end = datetime.combine(local_day, time.max, tzinfo=tz).astimezone(UTC)

        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.client),
                selectinload(Booking.base_service),
                selectinload(Booking.approval_requests),
            )
            .where(
                Booking.status.in_([BookingStatus.PENDING_MASTER, BookingStatus.CONFIRMED]),
                Slot.start_at >= day_start,
                Slot.start_at <= day_end,
            )
            .order_by(Slot.start_at)
        )
        return list(result.scalars().unique().all())

    async def list_force_majeure_unnotified_for_day(
        self,
        *,
        local_day: date,
        tz_name: str,
    ) -> list[Booking]:
        """Return force-majeure-cancelled bookings that still need client notice."""
        from zoneinfo import ZoneInfo  # noqa: PLC0415

        tz = ZoneInfo(tz_name)
        day_start = datetime.combine(local_day, time.min, tzinfo=tz).astimezone(UTC)
        day_end = datetime.combine(local_day, time.max, tzinfo=tz).astimezone(UTC)

        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.client),
                selectinload(Booking.base_service),
                selectinload(Booking.approval_requests),
            )
            .where(
                Booking.status == BookingStatus.CANCELLED_BY_MASTER,
                Booking.cancel_reason_code == "force_majeure",
                Booking.force_majeure_notice_sent_at.is_(None),
                Slot.start_at >= day_start,
                Slot.start_at <= day_end,
            )
            .order_by(Slot.start_at, Booking.id)
        )
        return list(result.scalars().unique().all())

    async def list_due_completion(self, *, now_utc: datetime) -> list[Booking]:
        """Return confirmed bookings that should become completed."""
        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(selectinload(Booking.slot))
            .where(
                Booking.status == BookingStatus.CONFIRMED,
                Slot.start_at <= now_utc - timedelta(minutes=30),
            )
            .order_by(Slot.start_at, Booking.id)
        )
        return list(result.scalars().unique().all())

    async def list_for_local_day(self, *, local_day: date, tz_name: str) -> list[Booking]:
        """Return today's bookings sorted by slot time for the morning summary."""
        tz = ZoneInfo(tz_name)
        day_start = datetime.combine(local_day, time.min, tzinfo=tz).astimezone(UTC)
        day_end = datetime.combine(local_day, time.max, tzinfo=tz).astimezone(UTC)

        result = await self.session.execute(
            select(Booking)
            .join(Slot, Slot.id == Booking.slot_id)
            .options(
                selectinload(Booking.slot),
                selectinload(Booking.client),
                selectinload(Booking.base_service),
            )
            .where(
                Booking.status.in_([BookingStatus.PENDING_MASTER, BookingStatus.CONFIRMED]),
                Slot.start_at >= day_start,
                Slot.start_at <= day_end,
            )
            .order_by(Slot.start_at)
        )
        return list(result.scalars().unique().all())

    async def count_for_local_day(self, *, local_day: date, tz_name: str) -> int:
        """Return the number of today's bookings for the admin dashboard."""
        tz = ZoneInfo(tz_name)
        day_start = datetime.combine(local_day, time.min, tzinfo=tz).astimezone(UTC)
        day_end = datetime.combine(local_day, time.max, tzinfo=tz).astimezone(UTC)

        result = await self.session.execute(
            select(func.count(Booking.id))
            .join(Slot, Slot.id == Booking.slot_id)
            .where(
                Booking.status.in_(
                    [
                        BookingStatus.PENDING_MASTER,
                        BookingStatus.CONFIRMED,
                        BookingStatus.COMPLETED,
                    ]
                ),
                Slot.start_at >= day_start,
                Slot.start_at <= day_end,
            )
        )
        return int(result.scalar_one())

    async def get_period_stats(
        self,
        *,
        start_utc: datetime | None,
        end_utc: datetime | None,
    ) -> BookingPeriodStats:
        """Return admin dashboard stats for a date range."""
        booking_filters = []
        if start_utc is not None:
            booking_filters.append(Slot.start_at >= start_utc)
        if end_utc is not None:
            booking_filters.append(Slot.start_at <= end_utc)

        bookings_result = await self.session.execute(
            select(
                Booking.status,
                Booking.cancel_reason_code,
                Booking.fixed_price,
            )
            .join(Slot, Slot.id == Booking.slot_id)
            .where(*booking_filters)
        )
        rows = list(bookings_result.all())

        cancel_reason_counts = {
            "sick": 0,
            "busy": 0,
            "force_majeure": 0,
            "later": 0,
            "not_planning": 0,
            "other": 0,
        }
        completed_count = 0
        cancelled_by_client_count = 0
        cancelled_by_master_count = 0
        no_show_count = 0
        revenue = 0

        for status, cancel_reason_code, fixed_price in rows:
            if status == BookingStatus.COMPLETED:
                completed_count += 1
                revenue += int(fixed_price)
            elif status == BookingStatus.CANCELLED_BY_CLIENT:
                cancelled_by_client_count += 1
                cancel_reason_counts[(cancel_reason_code or "other")] = (
                    cancel_reason_counts.get(cancel_reason_code or "other", 0) + 1
                )
            elif status == BookingStatus.CANCELLED_BY_MASTER:
                cancelled_by_master_count += 1
            elif status == BookingStatus.NO_SHOW:
                no_show_count += 1

        new_clients_filters = [User.is_admin.is_(False)]
        if start_utc is not None:
            new_clients_filters.append(User.created_at >= start_utc)
        if end_utc is not None:
            new_clients_filters.append(User.created_at <= end_utc)
        new_clients = int(
            await self.session.scalar(select(func.count(User.id)).where(*new_clients_filters)) or 0
        )

        top_services_result = await self.session.execute(
            select(Service.name, func.count(Booking.id))
            .join(Booking, Booking.base_service_id == Service.id)
            .join(Slot, Slot.id == Booking.slot_id)
            .where(*booking_filters)
            .group_by(Service.id, Service.name)
            .order_by(func.count(Booking.id).desc(), Service.name)
            .limit(3)
        )

        return BookingPeriodStats(
            total_bookings=len(rows),
            completed_count=completed_count,
            cancelled_by_client_count=cancelled_by_client_count,
            cancelled_by_master_count=cancelled_by_master_count,
            no_show_count=no_show_count,
            revenue=revenue,
            new_clients=new_clients,
            cancel_reason_counts=cancel_reason_counts,
            top_services=[(str(name), int(count)) for name, count in top_services_result.all()],
        )

    async def attach_design_photos(
        self,
        booking_id: int,
        client_id: int,
        photos: list[str],
        comment: str | None,
    ) -> bool:
        """Append reference photos and comment to an existing booking.

        Returns True if the booking was found and updated.
        """
        result = await self.session.execute(
            select(Booking).where(
                Booking.id == booking_id,
                Booking.client_id == client_id,
            )
        )
        booking = result.scalar_one_or_none()
        if booking is None:
            return False
        booking.design_photos = list(booking.design_photos or []) + photos
        if comment:
            booking.design_comment = comment
        return True
