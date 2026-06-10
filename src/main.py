from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.bot.app import build_application
from src.bot.commands import register_bot_commands
from src.config import get_settings
from src.db.base import get_engine, make_database_url
from src.logger import configure_logging
from src.scheduler import build_scheduler
from src.services.observability import log_event

logger = logging.getLogger(__name__)


def ensure_sqlite_parent_dir() -> None:
    """Create the SQLite directory if the configured database uses a file path."""
    database_url = make_database_url()
    if not database_url.drivername.startswith("sqlite"):
        return
    database_path = database_url.database
    if not database_path or database_path == ":memory:":
        return
    Path(database_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


async def main() -> None:
    """Run the Telegram bot with the scheduler."""
    settings = get_settings()
    configure_logging(settings.log_level)
    ensure_sqlite_parent_dir()
    if not settings.bot_token:
        raise RuntimeError("BOT_TOKEN is not configured. Fill it in .env before starting the bot.")

    bot, dispatcher = build_application(settings)
    await register_bot_commands(bot, settings)
    scheduler = build_scheduler(settings, bot=bot)

    log_event(
        logger,
        logging.INFO,
        "bot_starting",
        tz=settings.tz,
        database_url=str(make_database_url(settings)),
        gcal_enabled=settings.gcal_enabled,
        admin_count=len(settings.admin_tg_ids),
    )
    scheduler.start()

    try:
        await dispatcher.start_polling(bot)
    finally:
        log_event(logger, logging.INFO, "bot_shutting_down")
        scheduler.shutdown(wait=False)
        await bot.session.close()
        await get_engine(settings).dispose()


if __name__ == "__main__":
    asyncio.run(main())
