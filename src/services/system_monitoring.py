from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from time import monotonic

from aiogram import Bot
from sqlalchemy import text

from src.config import Settings
from src.db.base import get_engine, make_database_url, session_scope
from src.services.notifications import send_text_to_admins
from src.services.observability import (
    log_event,
    maybe_send_system_alert,
    record_job_failure,
    record_job_started,
    record_job_success,
    resolve_system_alert,
    update_system_timestamp,
)

logger = logging.getLogger(__name__)

_db_alert_last_sent_at: datetime | None = None


async def _send_database_unavailable_alert(
    bot: Bot,
    settings: Settings,
    *,
    error: Exception,
) -> None:
    """Send a rate-limited direct alert when the DB is unavailable."""
    global _db_alert_last_sent_at
    now_utc = datetime.now(UTC)
    if (
        _db_alert_last_sent_at is not None
        and (now_utc - _db_alert_last_sent_at).total_seconds() < 3600
    ):
        return
    _db_alert_last_sent_at = now_utc
    await send_text_to_admins(
        bot,
        admin_tg_ids=settings.admin_tg_id_set,
        text=(
            "🚨 База данных недоступна\n\n"
            f"Ошибка: {error.__class__.__name__}: {error}"
        ),
    )


async def run_monitored_job(
    *,
    job_name: str,
    bot: Bot,
    settings: Settings,
    job: Callable[[Bot, Settings], Awaitable[None]],
) -> None:
    """Run one scheduler job with structured logs, health state, and alerts."""
    started_at = datetime.now(UTC)
    start_clock = monotonic()
    log_event(logger, logging.INFO, "job_started", job_name=job_name, started_at=started_at)

    try:
        async with session_scope(settings) as session:
            await record_job_started(session, job_name=job_name, started_at=started_at)
            await session.commit()
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "job_db_unavailable_on_start",
            job_name=job_name,
            error_type=exc.__class__.__name__,
            error=str(exc),
        )
        await _send_database_unavailable_alert(bot, settings, error=exc)

    try:
        await job(bot, settings)
    except Exception as exc:
        duration_ms = int((monotonic() - start_clock) * 1000)
        log_event(
            logger,
            logging.ERROR,
            "job_failed",
            job_name=job_name,
            duration_ms=duration_ms,
            error_type=exc.__class__.__name__,
            error=str(exc),
        )
        try:
            async with session_scope(settings) as session:
                streak = await record_job_failure(
                    session,
                    job_name=job_name,
                    failed_at=datetime.now(UTC),
                    error=exc,
                )
                if streak >= 3:
                    await maybe_send_system_alert(
                        session,
                        bot=bot,
                        settings=settings,
                        kind="job_failure",
                        signature=job_name,
                        text=(
                            "🚨 Фоновая джоба падает подряд\n\n"
                            f"Job: {job_name}\n"
                            f"Ошибка: {exc.__class__.__name__}\n"
                            f"Текст: {exc}"
                        ),
                    )
                await session.commit()
        except Exception as db_exc:
            log_event(
                logger,
                logging.ERROR,
                "job_db_unavailable_on_failure",
                job_name=job_name,
                error_type=db_exc.__class__.__name__,
                error=str(db_exc),
            )
            await _send_database_unavailable_alert(bot, settings, error=db_exc)
        raise

    finished_at = datetime.now(UTC)
    duration_ms = int((monotonic() - start_clock) * 1000)
    log_event(
        logger,
        logging.INFO,
        "job_succeeded",
        job_name=job_name,
        duration_ms=duration_ms,
        finished_at=finished_at,
    )
    try:
        async with session_scope(settings) as session:
            previous_failures = await record_job_success(
                session,
                job_name=job_name,
                finished_at=finished_at,
            )
            if job_name == "sqlite_integrity_check":
                await update_system_timestamp(
                    session,
                    key="system.last_integrity_check_at",
                    value=finished_at,
                )
            if previous_failures >= 3:
                await resolve_system_alert(
                    session,
                    bot=bot,
                    settings=settings,
                    kind="job_failure",
                    signature=job_name,
                    text=f"✅ Джоба снова работает: {job_name}",
                )
            await session.commit()
    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "job_db_unavailable_on_success",
            job_name=job_name,
            error_type=exc.__class__.__name__,
            error=str(exc),
        )
        await _send_database_unavailable_alert(bot, settings, error=exc)


async def run_sqlite_integrity_check(bot: Bot, settings: Settings) -> None:
    """Run a nightly PRAGMA integrity_check for the configured SQLite DB."""
    if not make_database_url(settings).drivername.startswith("sqlite"):
        return
    engine = get_engine(settings)
    async with engine.connect() as connection:
        rows = list((await connection.execute(text("PRAGMA integrity_check"))).scalars().all())
    normalized = [str(item) for item in rows]
    if normalized != ["ok"]:
        details = "\n".join(normalized) or "unknown"
        async with session_scope(settings) as session:
            await maybe_send_system_alert(
                session,
                bot=bot,
                settings=settings,
                kind="sqlite_integrity_check",
                signature="sqlite_integrity_check",
                text=(
                    "🚨 SQLite integrity_check провалился\n\n"
                    f"Результат:\n{details}"
                ),
            )
            await session.commit()
        raise RuntimeError(f"SQLite integrity_check failed: {details}")
