from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from src.config import Settings

logger = logging.getLogger(__name__)

CLIENT_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="book", description="Записаться"),
    BotCommand(command="mybookings", description="Мои записи"),
    BotCommand(command="admin", description="Режим администратора"),
]

ADMIN_COMMANDS = [
    BotCommand(command="start", description="Главное меню"),
    BotCommand(command="schedule", description="Расписание"),
    BotCommand(command="today", description="Статусы на сегодня"),
    BotCommand(command="requests", description="Запросы"),
    BotCommand(command="clients", description="Клиенты"),
    BotCommand(command="diag", description="Диагностика"),
    BotCommand(command="admin", description="Режим администратора"),
]


async def register_bot_commands(bot: Bot, settings: Settings) -> None:
    """Register Telegram command menus for clients and admins.

    Telegram may intermittently timeout during startup. Command registration is
    helpful, but the bot should still start polling when this API call flakes.
    """
    try:
        await bot.set_my_commands(
            CLIENT_COMMANDS,
            scope=BotCommandScopeAllPrivateChats(),
        )
    except TelegramAPIError:
        logger.warning("Failed to register client bot commands; continuing startup", exc_info=True)
    for admin_tg_id in settings.admin_tg_ids:
        try:
            await bot.set_my_commands(
                ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=admin_tg_id),
            )
        except TelegramAPIError:
            logger.warning(
                "Failed to register admin bot commands for chat_id=%s; continuing startup",
                admin_tg_id,
                exc_info=True,
            )
