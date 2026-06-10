from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot

logger = logging.getLogger(__name__)


async def send_text_to_user(
    bot: Bot,
    *,
    tg_id: int,
    text: str,
    reply_markup: Any | None = None,
) -> None:
    """Send a text message to a single Telegram user."""
    try:
        await bot.send_message(chat_id=tg_id, text=text, reply_markup=reply_markup)
    except Exception:
        logger.exception("Failed to send a message to user %s", tg_id)


async def send_text_to_admins(
    bot: Bot,
    *,
    admin_tg_ids: set[int],
    text: str,
    reply_markup: Any | None = None,
) -> None:
    """Send the same text message to all configured admins."""
    for admin_tg_id in admin_tg_ids:
        try:
            await bot.send_message(
                chat_id=admin_tg_id,
                text=text,
                reply_markup=reply_markup,
            )
        except Exception:
            logger.exception("Failed to send a message to admin %s", admin_tg_id)


async def send_photo_to_admins(
    bot: Bot,
    *,
    admin_tg_ids: set[int],
    photo: str,
    caption: str | None = None,
    reply_markup: Any | None = None,
) -> None:
    """Send the same photo message to all configured admins."""
    for admin_tg_id in admin_tg_ids:
        try:
            await bot.send_photo(
                chat_id=admin_tg_id,
                photo=photo,
                caption=caption,
                reply_markup=reply_markup,
            )
        except Exception:
            logger.exception("Failed to send a photo to admin %s", admin_tg_id)


async def send_voice_to_admins(
    bot: Bot,
    *,
    admin_tg_ids: set[int],
    voice: str,
    caption: str | None = None,
    reply_markup: Any | None = None,
) -> None:
    """Send the same voice message to all configured admins."""
    for admin_tg_id in admin_tg_ids:
        try:
            await bot.send_voice(
                chat_id=admin_tg_id,
                voice=voice,
                caption=caption,
                reply_markup=reply_markup,
            )
        except Exception:
            logger.exception("Failed to send a voice message to admin %s", admin_tg_id)
