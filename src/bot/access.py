from __future__ import annotations

import logging

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, TelegramObject

from src.bot import texts

logger = logging.getLogger(__name__)

ADMIN_CALLBACK_PREFIXES = (
    "admin_",
    "approval:",
    "force_majeure:",
    "late_notice:",
    "rescue_slot:",
)
CLIENT_APPROVAL_CALLBACK_PREFIXES = (
    "approval:accept_offer:",
    "approval:decline_offer:",
)


class AdminOnlyFilter(BaseFilter):
    """Allow an event into the protected admin router only for admins."""

    async def __call__(
        self,
        event: TelegramObject,
        *,
        is_admin: bool = False,
    ) -> bool:
        if is_admin:
            return True

        if (
            isinstance(event, CallbackQuery)
            and event.data is not None
            and event.data.startswith(ADMIN_CALLBACK_PREFIXES)
            and not event.data.startswith(CLIENT_APPROVAL_CALLBACK_PREFIXES)
        ):
            try:
                await event.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
            except Exception:
                logger.debug("Could not answer rejected admin callback", exc_info=True)
        return False
