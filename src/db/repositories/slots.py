from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Slot, SlotStatus

PUBLIC_BOOKING_HORIZON_DAYS = 62


class SlotRepository:
    """Repository for booking slots."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, slot_id: int) -> Slot | None:
        """Return a slot by its primary key."""
        return await self.session.get(Slot, slot_id)

    async def get_by_start_at(self, start_at: datetime) -> Slot | None:
        """Return a slot by its UTC start datetime."""
        result = await self.session.execute(select(Slot).where(Slot.start_at == start_at))
        return result.scalar_one_or_none()

    async def create_if_missing(self, start_at: datetime) -> tuple[Slot, bool]:
        """Create a free slot unless it already exists."""
        slot = await self.get_by_start_at(start_at)
        if slot is not None:
            return slot, False

        slot = Slot(start_at=start_at, status=SlotStatus.FREE)
        self.session.add(slot)
        await self.session.flush()
        return slot, True

    async def list_free_future(
        self,
        *,
        now_utc: datetime | None = None,
        horizon_days: int | None = None,
    ) -> list[Slot]:
        """Return all future free slots ordered by start time."""
        current_utc = now_utc or datetime.now(UTC)
        conditions = [
            Slot.status == SlotStatus.FREE,
            Slot.start_at > current_utc,
        ]
        if horizon_days is not None:
            conditions.append(Slot.start_at <= current_utc + timedelta(days=horizon_days))
        query = select(Slot).where(*conditions).order_by(Slot.start_at)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_future(self, *, now_utc: datetime | None = None) -> list[Slot]:
        """Return all future slots ordered by start time."""
        current_utc = now_utc or datetime.now(UTC)
        result = await self.session.execute(
            select(Slot).where(Slot.start_at > current_utc).order_by(Slot.start_at)
        )
        return list(result.scalars().all())

    async def list_free_for_local_day(
        self,
        *,
        local_day: date,
        tz_name: str,
        now_utc: datetime | None = None,
    ) -> list[Slot]:
        """Return free slots that fall on the provided local date."""
        tz = ZoneInfo(tz_name)
        day_start_local = datetime.combine(local_day, time.min, tzinfo=tz)
        day_end_local = datetime.combine(local_day, time.max, tzinfo=tz)
        current_utc = now_utc or datetime.now(UTC)

        query = (
            select(Slot)
            .where(
                Slot.status == SlotStatus.FREE,
                Slot.start_at >= day_start_local.astimezone(UTC),
                Slot.start_at <= day_end_local.astimezone(UTC),
                Slot.start_at > current_utc,
            )
            .order_by(Slot.start_at)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_for_next_days(
        self,
        *,
        tz_name: str,
        days: int = 7,
        now_utc: datetime | None = None,
    ) -> list[Slot]:
        """Return all slots within the next N local days."""
        current_utc = now_utc or datetime.now(UTC)
        tz = ZoneInfo(tz_name)
        start_local = current_utc.astimezone(tz)
        range_start = datetime.combine(
            start_local.date(),
            time.min,
            tzinfo=tz,
        ).astimezone(UTC)
        range_end = datetime.combine(
            start_local.date() + timedelta(days=days - 1),
            time.max,
            tzinfo=tz,
        ).astimezone(UTC)

        result = await self.session.execute(
            select(Slot)
            .where(
                Slot.start_at >= range_start,
                Slot.start_at <= range_end,
            )
            .order_by(Slot.start_at)
        )
        return list(result.scalars().all())

    async def update_status(self, slot: Slot, status: SlotStatus) -> Slot:
        """Update a slot status."""
        slot.status = status
        await self.session.flush()
        return slot

    async def update_start_at(self, slot: Slot, start_at: datetime) -> Slot:
        """Move a slot to a new UTC start datetime."""
        slot.start_at = start_at
        await self.session.flush()
        return slot

    async def delete_slot(self, slot: Slot) -> None:
        """Delete a slot entity."""
        await self.session.delete(slot)
        await self.session.flush()
