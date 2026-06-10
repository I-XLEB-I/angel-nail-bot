from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import RateLimitEvent


class RateLimitEventRepository:
    """Repository for anti-abuse and throttling audit events."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        *,
        user_id: int,
        kind: str,
        metadata: dict[str, object] | None = None,
        created_at: datetime | None = None,
    ) -> RateLimitEvent:
        """Persist one audit event."""
        payload = RateLimitEvent(
            user_id=user_id,
            kind=kind,
            metadata_json=metadata or {},
        )
        if created_at is not None:
            payload.created_at = created_at
        self.session.add(payload)
        await self.session.flush()
        return payload

    async def count_since(
        self,
        *,
        user_id: int,
        kind: str,
        since: datetime,
    ) -> int:
        """Count events of one kind for a user since a cutoff."""
        result = await self.session.execute(
            select(func.count(RateLimitEvent.id)).where(
                RateLimitEvent.user_id == user_id,
                RateLimitEvent.kind == kind,
                RateLimitEvent.created_at >= since,
            )
        )
        return int(result.scalar_one() or 0)

    async def has_since(
        self,
        *,
        user_id: int,
        kind: str,
        since: datetime,
    ) -> bool:
        """Return whether an event of one kind exists since a cutoff."""
        return await self.count_since(user_id=user_id, kind=kind, since=since) > 0

    async def get_latest_since(
        self,
        *,
        user_id: int,
        kind: str,
        since: datetime,
    ) -> RateLimitEvent | None:
        """Return the latest event of one kind for a user since a cutoff."""
        result = await self.session.execute(
            select(RateLimitEvent)
            .where(
                RateLimitEvent.user_id == user_id,
                RateLimitEvent.kind == kind,
                RateLimitEvent.created_at >= since,
            )
            .order_by(RateLimitEvent.created_at.desc(), RateLimitEvent.id.desc())
            .limit(1)
        )
        return result.scalars().first()
