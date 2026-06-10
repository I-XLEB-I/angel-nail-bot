from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Setting


class SettingRepository:
    """Repository for key-value settings."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_key(self, key: str) -> Setting | None:
        """Return a setting by key."""
        result = await self.session.execute(select(Setting).where(Setting.key == key))
        return result.scalar_one_or_none()

    async def get_value(self, key: str) -> str | None:
        """Return a setting value by key."""
        setting = await self.get_by_key(key)
        return setting.value if setting is not None else None

    async def get_value_or_default(self, key: str, default: str) -> str:
        """Return a setting value or a fallback."""
        value = await self.get_value(key)
        return value if value else default

    async def list_all(self) -> list[Setting]:
        """Return all settings ordered by key."""
        result = await self.session.execute(select(Setting).order_by(Setting.key))
        return list(result.scalars().all())

    async def upsert(self, *, key: str, value: str) -> Setting:
        """Create or update a setting."""
        setting = await self.get_by_key(key)
        if setting is None:
            setting = Setting(key=key, value=value)
            self.session.add(setting)
        else:
            setting.value = value
        await self.session.flush()
        return setting
