from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramNetworkError
from aiogram.types import ErrorEvent

from src.bot import texts
from src.bot.fsm_storage import JsonFsmStorage
from src.bot.handlers.admin.all_bookings import router as admin_all_bookings_router
from src.bot.handlers.admin.approvals import router as admin_approvals_router
from src.bot.handlers.admin.booking_cards import router as admin_booking_cards_router
from src.bot.handlers.admin.broadcast import router as admin_broadcast_router
from src.bot.handlers.admin.button_edit import router as admin_button_edit_router
from src.bot.handlers.admin.clients import router as admin_clients_router
from src.bot.handlers.admin.custom_emoji import router as admin_custom_emoji_router
from src.bot.handlers.admin.force_majeure import router as admin_force_majeure_router
from src.bot.handlers.admin.late_notices import router as admin_late_notices_router
from src.bot.handlers.admin.manual_booking import router as admin_manual_booking_router
from src.bot.handlers.admin.menu import router as admin_menu_router
from src.bot.handlers.admin.proxy_chat import router as admin_proxy_chat_router
from src.bot.handlers.admin.rescue_slots import router as admin_rescue_slots_router
from src.bot.handlers.admin.schedule import router as admin_schedule_router
from src.bot.handlers.admin.services_crud import router as admin_services_router
from src.bot.handlers.admin.settings_edit import router as admin_settings_router
from src.bot.handlers.admin.stats import router as admin_stats_router
from src.bot.handlers.admin.templates_edit import router as admin_templates_router
from src.bot.handlers.admin.unconfirmed_alerts import router as admin_unconfirmed_alerts_router
from src.bot.handlers.client.about import router as client_about_router
from src.bot.handlers.client.address import router as client_address_router
from src.bot.handlers.client.aftercare import router as client_aftercare_router
from src.bot.handlers.client.ask_master import router as client_ask_master_router
from src.bot.handlers.client.booking_flow import router as client_booking_router
from src.bot.handlers.client.design_photo import router as client_design_photo_router
from src.bot.handlers.client.fallback import router as client_fallback_router
from src.bot.handlers.client.menu import router as client_menu_router
from src.bot.handlers.client.my_bookings import router as client_my_bookings_router
from src.bot.handlers.client.offer_confirm import router as client_offer_confirm_router
from src.bot.handlers.client.portfolio import router as client_portfolio_router
from src.bot.handlers.client.postvisit import router as client_postvisit_router
from src.bot.handlers.client.reminders import router as client_reminders_router
from src.bot.handlers.client.services_list import router as client_services_router
from src.bot.handlers.common import router as common_router
from src.bot.middlewares.throttle import ThrottleMiddleware
from src.bot.middlewares.user import UserContextMiddleware
from src.config import Settings
from src.db.base import get_session_factory
from src.services.observability import log_event

logger = logging.getLogger(__name__)


def _build_session() -> AiohttpSession:
    # Hosting (TimeWeb) periodically drops the IPv4 route to Telegram's
    # 149.154.166.0/24 pool; without happy-eyeballs aiohttp waits the full
    # timeout on the bad v4 before trying v6, freezing handlers for ~60s.
    session = AiohttpSession()
    session._connector_init["happy_eyeballs_delay"] = 0.25
    return session


def build_application(settings: Settings) -> tuple[Bot, Dispatcher]:
    """Build the bot and dispatcher."""
    bot = Bot(token=settings.bot_token, session=_build_session())
    dispatcher = Dispatcher(storage=JsonFsmStorage())

    session_factory = get_session_factory(settings)
    dispatcher.update.outer_middleware(
        UserContextMiddleware(session_factory=session_factory, settings=settings)
    )
    dispatcher.update.outer_middleware(ThrottleMiddleware())
    dispatcher.include_router(common_router)
    dispatcher.include_router(admin_menu_router)
    dispatcher.include_router(admin_all_bookings_router)
    dispatcher.include_router(admin_booking_cards_router)
    dispatcher.include_router(admin_approvals_router)
    dispatcher.include_router(admin_stats_router)
    dispatcher.include_router(admin_broadcast_router)
    dispatcher.include_router(admin_templates_router)
    dispatcher.include_router(admin_settings_router)
    dispatcher.include_router(admin_proxy_chat_router)
    dispatcher.include_router(admin_rescue_slots_router)
    dispatcher.include_router(admin_schedule_router)
    dispatcher.include_router(admin_services_router)
    dispatcher.include_router(admin_clients_router)
    dispatcher.include_router(admin_button_edit_router)
    dispatcher.include_router(admin_custom_emoji_router)
    dispatcher.include_router(admin_unconfirmed_alerts_router)
    dispatcher.include_router(admin_force_majeure_router)
    dispatcher.include_router(admin_late_notices_router)
    dispatcher.include_router(admin_manual_booking_router)
    dispatcher.include_router(client_menu_router)
    dispatcher.include_router(client_services_router)
    dispatcher.include_router(client_portfolio_router)
    dispatcher.include_router(client_address_router)
    dispatcher.include_router(client_about_router)
    dispatcher.include_router(client_design_photo_router)
    dispatcher.include_router(client_booking_router)
    dispatcher.include_router(client_my_bookings_router)
    dispatcher.include_router(client_aftercare_router)
    dispatcher.include_router(client_offer_confirm_router)
    dispatcher.include_router(client_postvisit_router)
    dispatcher.include_router(client_reminders_router)
    dispatcher.include_router(client_ask_master_router)
    # Fallback MUST be last — it catches text out of FSM state and would otherwise
    # swallow legitimate input that should reach earlier routers.
    dispatcher.include_router(client_fallback_router)

    @dispatcher.error()
    async def global_error_handler(event: ErrorEvent) -> None:
        if isinstance(event.exception, TelegramNetworkError):
            log_event(
                logger,
                logging.WARNING,
                "telegram_network_error",
                error_type=event.exception.__class__.__name__,
                error=str(event.exception),
            )
            return
        update = event.update
        update_id = getattr(update, "update_id", None)
        user_id = None
        if getattr(update, "message", None) is not None and update.message.from_user is not None:
            user_id = update.message.from_user.id
        elif (
            getattr(update, "callback_query", None) is not None
            and update.callback_query.from_user is not None
        ):
            user_id = update.callback_query.from_user.id
        log_event(
            logger,
            logging.ERROR,
            "unhandled_bot_error",
            update_id=update_id,
            user_id=user_id,
            error_type=event.exception.__class__.__name__,
            error=str(event.exception),
        )
        logger.exception("Unhandled bot error", exc_info=event.exception)
        try:
            if update.callback_query is not None:
                try:
                    await update.callback_query.answer()
                except Exception:
                    pass
                if update.callback_query.message is not None:
                    await update.callback_query.message.answer(texts.GENERIC_ERROR_TEXT)
            elif update.message is not None:
                await update.message.answer(texts.GENERIC_ERROR_TEXT)
        except Exception:
            pass

    return bot, dispatcher
