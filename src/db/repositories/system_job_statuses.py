from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import SystemJobStatus


class SystemJobStatusRepository:
    """Repository for background-job health snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_job_name(self, job_name: str) -> SystemJobStatus | None:
        """Return one job status row by scheduler job id."""
        result = await self.session.execute(
            select(SystemJobStatus).where(SystemJobStatus.job_name == job_name)
        )
        return result.scalar_one_or_none()

    async def get_or_create(self, job_name: str) -> SystemJobStatus:
        """Return one job status row, creating it on first use."""
        existing = await self.get_by_job_name(job_name)
        if existing is not None:
            return existing
        status = SystemJobStatus(job_name=job_name)
        self.session.add(status)
        await self.session.flush()
        return status

    async def list_all(self) -> list[SystemJobStatus]:
        """Return all tracked job statuses ordered by job name."""
        result = await self.session.execute(
            select(SystemJobStatus).order_by(SystemJobStatus.job_name)
        )
        return list(result.scalars().all())

