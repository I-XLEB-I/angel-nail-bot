from __future__ import annotations

import asyncio
import logging

from sqlalchemy.exc import OperationalError

from src.config import get_settings
from src.db.base import session_scope
from src.db.models import ServiceKind
from src.db.repositories.services import ServiceRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.admin_defaults import required_template_defaults

logger = logging.getLogger(__name__)


SERVICE_SEED = [
    {
        "name": "Маникюр комбинированный без покрытия",
        "price": 1400,
        "price_variable": False,
        "duration_min": 90,
        "kind": ServiceKind.BASE,
        "display_order": 10,
    },
    {
        "name": "Покрытие гель-лак",
        "price": 2400,
        "price_variable": False,
        "duration_min": 120,
        "kind": ServiceKind.BASE,
        "display_order": 20,
    },
    {
        "name": "Гелевая коррекция / укрепление",
        "price": 2800,
        "price_variable": False,
        "duration_min": 150,
        "kind": ServiceKind.BASE,
        "display_order": 30,
    },
    {
        "name": "Наращивание ногтей",
        "price": 3500,
        "price_variable": False,
        "duration_min": 180,
        "kind": ServiceKind.BASE,
        "display_order": 40,
    },
    {
        "name": "Дизайн",
        "price": 250,
        "price_variable": True,
        "duration_min": 0,
        "kind": ServiceKind.ADDON,
        "display_order": 50,
    },
    {
        "name": "Доплата за длину (от 2)",
        "price": 200,
        "price_variable": True,
        "duration_min": 0,
        "kind": ServiceKind.ADDON,
        "display_order": 60,
    },
]


def build_template_seed() -> dict[str, str]:
    """Return default editable templates."""
    return required_template_defaults()


def build_setting_seed() -> dict[str, str]:
    """Return default key-value settings."""
    settings = get_settings()
    return {
        "tz": settings.tz,
        "reminder_24h_enabled": "true",
        "reminder_2h_enabled": str(settings.feature_reminder_2h).lower(),
        "postvisit_delay_hours": "2",
        "repeat_prompt_weeks": "3",
        "vacation_mode": "false",
        "schedule_image_enabled": "false",
        "min_days_between_bookings": "17",
        "reschedule_min_hours_before": "48",
        "max_reschedules_per_booking": "2",
        "cancel_cooldown_minutes": "30",
        "late_cancel_hours": "4",
        "late_cancel_strike_limit": "3",
        "no_show_strike_limit": "2",
        "proxy_messages_per_hour": "5",
        "ask_master_per_day": "3",
        "max_pending_approvals_per_user": "5",
        "portfolio_channel_url": settings.portfolio_channel_url,
    }


async def seed() -> None:
    """Seed services, templates and settings."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    try:
        async with session_scope() as session:
            service_repository = ServiceRepository(session)
            template_repository = TemplateRepository(session)
            setting_repository = SettingRepository(session)

            for service in SERVICE_SEED:
                await service_repository.upsert_seed_service(**service)

            for key, content in build_template_seed().items():
                await template_repository.upsert(key=key, content=content)

            for key, value in build_setting_seed().items():
                await setting_repository.upsert(key=key, value=value)

            await session.commit()
    except OperationalError as exc:
        raise RuntimeError(
            "Database schema is missing. Run `alembic upgrade head` before "
            "`python scripts/seed.py`."
        ) from exc

    logger.info("Seed completed successfully")


if __name__ == "__main__":
    asyncio.run(seed())
