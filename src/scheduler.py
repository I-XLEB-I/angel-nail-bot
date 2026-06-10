from __future__ import annotations

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.config import Settings
from src.services.anti_abuse_alerts import send_rate_limit_alerts
from src.services.calendar_sync import sync_external_calendar_blocks
from src.services.morning_summary import send_morning_summary
from src.services.reminders import (
    mark_completed,
    send_due_reminders,
    send_postvisit,
    send_repeat_prompt,
    send_unconfirmed_alerts,
    send_winback_prompts,
)
from src.services.system_monitoring import run_monitored_job, run_sqlite_integrity_check


def build_scheduler(settings: Settings, *, bot: Bot) -> AsyncIOScheduler:
    """Build an application scheduler with all periodic jobs registered."""
    scheduler = AsyncIOScheduler(timezone=settings.tz)
    scheduler.add_job(
        run_monitored_job,
        IntervalTrigger(minutes=5),
        kwargs={
            "job_name": "reminder_24h_and_2h",
            "bot": bot,
            "settings": settings,
            "job": send_due_reminders,
        },
        id="reminder_24h_and_2h",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_monitored_job,
        IntervalTrigger(minutes=10),
        kwargs={
            "job_name": "mark_completed",
            "bot": bot,
            "settings": settings,
            "job": mark_completed,
        },
        id="mark_completed",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_monitored_job,
        IntervalTrigger(minutes=15),
        kwargs={
            "job_name": "postvisit",
            "bot": bot,
            "settings": settings,
            "job": send_postvisit,
        },
        id="postvisit",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_monitored_job,
        IntervalTrigger(hours=1),
        kwargs={
            "job_name": "repeat_prompt",
            "bot": bot,
            "settings": settings,
            "job": send_repeat_prompt,
        },
        id="repeat_prompt",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_monitored_job,
        IntervalTrigger(hours=1),
        kwargs={
            "job_name": "rate_limit_alerts",
            "bot": bot,
            "settings": settings,
            "job": send_rate_limit_alerts,
        },
        id="rate_limit_alerts",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_monitored_job,
        IntervalTrigger(hours=6),
        kwargs={
            "job_name": "winback_prompts",
            "bot": bot,
            "settings": settings,
            "job": send_winback_prompts,
        },
        id="winback_prompts",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_monitored_job,
        IntervalTrigger(minutes=5),
        kwargs={
            "job_name": "unconfirmed_alerts",
            "bot": bot,
            "settings": settings,
            "job": send_unconfirmed_alerts,
        },
        id="unconfirmed_alerts",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_monitored_job,
        CronTrigger(hour=8, minute=0, timezone=settings.tz),
        kwargs={
            "job_name": "morning_summary",
            "bot": bot,
            "settings": settings,
            "job": send_morning_summary,
        },
        id="morning_summary",
        max_instances=1,
        replace_existing=True,
    )
    scheduler.add_job(
        run_monitored_job,
        CronTrigger(hour=3, minute=20, timezone=settings.tz),
        kwargs={
            "job_name": "sqlite_integrity_check",
            "bot": bot,
            "settings": settings,
            "job": run_sqlite_integrity_check,
        },
        id="sqlite_integrity_check",
        max_instances=1,
        replace_existing=True,
    )
    if settings.gcal_enabled:
        scheduler.add_job(
            run_monitored_job,
            IntervalTrigger(minutes=15),
            kwargs={
                "job_name": "gcal_pull",
                "bot": bot,
                "settings": settings,
                "job": sync_external_calendar_blocks,
            },
            id="gcal_pull",
            max_instances=1,
            replace_existing=True,
        )
    return scheduler
