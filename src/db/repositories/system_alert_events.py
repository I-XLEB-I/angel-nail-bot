from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import SystemAlertEvent


class SystemAlertEventRepository:
    """Repository for deduplicated critical operational alerts."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_open_by_kind_signature(
        self,
        *,
        kind: str,
        signature: str,
    ) -> SystemAlertEvent | None:
        """Return one unresolved alert event by its identity."""
        result = await self.session.execute(
            select(SystemAlertEvent).where(
                SystemAlertEvent.kind == kind,
                SystemAlertEvent.signature == signature,
                SystemAlertEvent.resolved_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_any_by_kind_signature(
        self,
        *,
        kind: str,
        signature: str,
    ) -> SystemAlertEvent | None:
        """Return any alert event (open or resolved) by its identity.

        Useful for reopening a previously resolved alert that fires again — the
        unique constraint on (kind, signature) would otherwise block a fresh INSERT.
        """
        result = await self.session.execute(
            select(SystemAlertEvent).where(
                SystemAlertEvent.kind == kind,
                SystemAlertEvent.signature == signature,
            )
        )
        return result.scalar_one_or_none()

    async def list_open(self) -> list[SystemAlertEvent]:
        """Return all unresolved alert events ordered by recency."""
        result = await self.session.execute(
            select(SystemAlertEvent)
            .where(SystemAlertEvent.resolved_at.is_(None))
            .order_by(SystemAlertEvent.last_seen_at.desc())
        )
        return list(result.scalars().all())

