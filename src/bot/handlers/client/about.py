from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.bot.handlers.client.portfolio import show_portfolio

router = Router(name="client_about")


@router.callback_query(F.data == "client_menu:about")
async def show_about(
    callback: CallbackQuery,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Open the combined master-profile screen from the legacy about callback."""
    await show_portfolio(
        callback,
        db_session=db_session,
        settings=settings,
    )
