from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from aiogram import Bot
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from src.bot import texts
from src.bot.keyboards.admin import build_open_client_card_keyboard
from src.config import Settings
from src.db.base import session_scope
from src.db.models import RateLimitEvent, User, utcnow
from src.db.repositories.settings import SettingRepository
from src.services.notifications import send_text_to_admins

ALERT_SETTING_KEY = "rate_limit_alert_last_sent_at"
RATE_LIMIT_ALERT_KINDS = {"ask_master", "proxy_message"}


def _parse_iso_datetime(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _render_user_label(user: User) -> str:
    if user.tg_username:
        return f"@{user.tg_username}"
    return user.display_name or f"#{user.id}"


async def send_rate_limit_alerts(bot: Bot, settings: Settings) -> None:
    """Send one aggregated hourly alert if several users hit silent rate limits."""
    current_time = utcnow()
    since = current_time - timedelta(hours=1)

    async with session_scope(settings) as session:
        settings_repository = SettingRepository(session)
        last_sent_at = _parse_iso_datetime(await settings_repository.get_value(ALERT_SETTING_KEY))
        if last_sent_at is not None and current_time - last_sent_at < timedelta(hours=1):
            return

        result = await session.execute(
            select(RateLimitEvent)
            .options(selectinload(RateLimitEvent.user))
            .where(
                RateLimitEvent.kind.in_(RATE_LIMIT_ALERT_KINDS),
                RateLimitEvent.created_at >= since,
            )
        )
        blocked_events = [
            event
            for event in result.scalars().all()
            if event.metadata_json.get("blocked") is True and event.user is not None
        ]
        user_counts = Counter(event.user for event in blocked_events)
        if len(user_counts) < 3:
            return

        top_users = user_counts.most_common(5)
        lines = "\n".join(f"• {_render_user_label(user)} — {count}" for user, count in top_users)
        top_user = top_users[0][0]
        await send_text_to_admins(
            bot,
            admin_tg_ids=settings.admin_tg_id_set,
            text=texts.ADMIN_RATE_LIMIT_ALERT_TEXT.format(lines=lines),
            reply_markup=build_open_client_card_keyboard(top_user.id),
        )
        await settings_repository.upsert(key=ALERT_SETTING_KEY, value=current_time.isoformat())
        await session.commit()
