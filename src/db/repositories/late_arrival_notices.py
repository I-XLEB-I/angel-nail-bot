from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.db.models import Booking, LateArrivalNotice, LateArrivalNoticeStatus


class LateArrivalNoticeRepository:
    """Repository for booking-bound late-arrival notices."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, notice_id: int) -> LateArrivalNotice | None:
        """Return one notice with related booking/client preloaded."""
        result = await self.session.execute(
            select(LateArrivalNotice)
            .options(
                selectinload(LateArrivalNotice.booking).selectinload(Booking.slot),
                selectinload(LateArrivalNotice.booking).selectinload(Booking.base_service),
                selectinload(LateArrivalNotice.client),
            )
            .where(LateArrivalNotice.id == notice_id)
        )
        return result.scalar_one_or_none()

    async def get_active_for_booking(self, booking_id: int) -> LateArrivalNotice | None:
        """Return the current active notice for one booking, if any."""
        result = await self.session.execute(
            select(LateArrivalNotice)
            .where(
                LateArrivalNotice.booking_id == booking_id,
                LateArrivalNotice.status == LateArrivalNoticeStatus.ACTIVE,
            )
            .order_by(LateArrivalNotice.id.desc())
        )
        return result.scalars().first()

    async def create(
        self,
        *,
        booking_id: int,
        client_id: int,
        minutes: int,
        reason_code: str | None,
        comment: str | None,
        status: LateArrivalNoticeStatus = LateArrivalNoticeStatus.ACTIVE,
    ) -> LateArrivalNotice:
        """Create one late-arrival notice."""
        notice = LateArrivalNotice(
            booking_id=booking_id,
            client_id=client_id,
            minutes=minutes,
            reason_code=reason_code,
            comment=(comment or "").strip() or None,
            status=status,
        )
        self.session.add(notice)
        await self.session.flush()
        return notice

    async def update(self, notice: LateArrivalNotice, **fields: object) -> LateArrivalNotice:
        """Update editable notice fields."""
        for field_name, value in fields.items():
            setattr(notice, field_name, value)
        await self.session.flush()
        return notice
