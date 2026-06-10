from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ReminderAdminAlertDelivery


class ReminderAdminAlertDeliveryRepository:
    """Repository for admin-side reminder alert message deliveries."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_booking_admin_kind(
        self,
        *,
        booking_id: int,
        admin_tg_id: int,
        reminder_kind: str,
    ) -> ReminderAdminAlertDelivery | None:
        """Return one delivery identity for the given booking/admin/stage."""
        result = await self.session.execute(
            select(ReminderAdminAlertDelivery).where(
                ReminderAdminAlertDelivery.booking_id == booking_id,
                ReminderAdminAlertDelivery.admin_tg_id == admin_tg_id,
                ReminderAdminAlertDelivery.reminder_kind == reminder_kind,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        booking_id: int,
        admin_tg_id: int,
        reminder_kind: str,
        chat_id: int,
        message_id: int,
        sent_at,
    ) -> ReminderAdminAlertDelivery:
        """Create or refresh one admin alert delivery row."""
        delivery = await self.get_by_booking_admin_kind(
            booking_id=booking_id,
            admin_tg_id=admin_tg_id,
            reminder_kind=reminder_kind,
        )
        if delivery is None:
            delivery = ReminderAdminAlertDelivery(
                booking_id=booking_id,
                admin_tg_id=admin_tg_id,
                reminder_kind=reminder_kind,
                chat_id=chat_id,
                message_id=message_id,
                sent_at=sent_at,
            )
            self.session.add(delivery)
            return delivery

        delivery.chat_id = chat_id
        delivery.message_id = message_id
        delivery.sent_at = sent_at
        delivery.resolved_at = None
        return delivery

    async def list_open_by_booking_kind(
        self,
        *,
        booking_id: int,
        reminder_kind: str,
    ) -> list[ReminderAdminAlertDelivery]:
        """Return unresolved admin alert messages for one booking and stage."""
        result = await self.session.execute(
            select(ReminderAdminAlertDelivery).where(
                ReminderAdminAlertDelivery.booking_id == booking_id,
                ReminderAdminAlertDelivery.reminder_kind == reminder_kind,
                ReminderAdminAlertDelivery.resolved_at.is_(None),
            )
        )
        return list(result.scalars().all())
