from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import MorningSummaryDelivery


class MorningSummaryDeliveryRepository:
    """Repository for live-updatable admin morning summary messages."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_admin_tg_id(self, *, admin_tg_id: int) -> MorningSummaryDelivery | None:
        """Return the stored morning-summary delivery for one admin."""
        result = await self.session.execute(
            select(MorningSummaryDelivery).where(
                MorningSummaryDelivery.admin_tg_id == admin_tg_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        admin_tg_id: int,
        chat_id: int,
        message_id: int,
        summary_local_date: date,
        sent_at,
    ) -> MorningSummaryDelivery:
        """Create or refresh one admin morning-summary delivery row."""
        delivery = await self.get_by_admin_tg_id(admin_tg_id=admin_tg_id)
        if delivery is None:
            max_id = await self.session.scalar(select(func.max(MorningSummaryDelivery.id)))
            delivery = MorningSummaryDelivery(
                id=int(max_id or 0) + 1,
                admin_tg_id=admin_tg_id,
                chat_id=chat_id,
                message_id=message_id,
                summary_local_date=summary_local_date,
                sent_at=sent_at,
                updated_at=sent_at,
            )
            self.session.add(delivery)
            return delivery

        delivery.chat_id = chat_id
        delivery.message_id = message_id
        delivery.summary_local_date = summary_local_date
        delivery.sent_at = sent_at
        delivery.updated_at = sent_at
        return delivery

    async def list_for_local_date(
        self,
        *,
        summary_local_date: date,
    ) -> list[MorningSummaryDelivery]:
        """Return stored morning summaries for one local date."""
        result = await self.session.execute(
            select(MorningSummaryDelivery).where(
                MorningSummaryDelivery.summary_local_date == summary_local_date,
            )
        )
        return list(result.scalars().all())

    async def delete_by_admin_tg_id(self, *, admin_tg_id: int) -> None:
        """Delete the stored morning-summary delivery for one admin."""
        delivery = await self.get_by_admin_tg_id(admin_tg_id=admin_tg_id)
        if delivery is not None:
            await self.session.delete(delivery)
