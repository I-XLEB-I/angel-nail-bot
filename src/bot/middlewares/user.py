from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.config import Settings
from src.db.repositories.users import UserRepository


class UserContextMiddleware(BaseMiddleware):
    """Create or update a user record for every update with a Telegram sender."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.settings = settings

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        from_user = data.get("event_from_user")
        if from_user is None:
            return await handler(event, data)

        async with self.session_factory() as session:
            repository = UserRepository(session)
            user = await repository.upsert_from_telegram(
                tg_id=from_user.id,
                username=from_user.username,
                first_name=from_user.first_name,
                is_admin=from_user.id in self.settings.admin_tg_id_set,
            )
            await session.commit()

            data["db_session"] = session
            data["user"] = user
            data["is_admin"] = user.is_admin
            data["settings"] = self.settings

            return await handler(event, data)
