from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import Settings
from src.db.models import SystemAlertEvent, utcnow
from src.db.repositories.settings import SettingRepository
from src.db.repositories.system_alert_events import SystemAlertEventRepository
from src.db.repositories.system_job_statuses import SystemJobStatusRepository
from src.services.notifications import send_text_to_admins

SYSTEM_ALERT_SUPPRESSION_MINUTES = 60


def _coerce_utc(dt: datetime | None) -> datetime | None:
    """Normalize SQLite-returned naive timestamps into explicit UTC datetimes."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _normalize_field(value: Any) -> Any:
    """Return one JSON-serializable logging field."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dict):
        return {str(key): _normalize_field(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_normalize_field(item) for item in value]
    return str(value)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    /,
    **fields: Any,
) -> None:
    """Emit one structured logging event using standard-library logging."""
    extra = {"event": event}
    for key, value in fields.items():
        extra[key] = _normalize_field(value)
    logger.log(level, event, extra=extra)


class JsonLogFormatter(logging.Formatter):
    """Render log records as one-line JSON objects."""

    _reserved = {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": getattr(record, "event", record.getMessage()),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in self._reserved or key.startswith("_"):
                continue
            if key in {"event"}:
                continue
            payload[key] = _normalize_field(value)
        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exc_text"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


async def record_job_started(
    session: AsyncSession,
    *,
    job_name: str,
    started_at: datetime,
) -> None:
    """Mark one job execution as started."""
    repository = SystemJobStatusRepository(session)
    status = await repository.get_or_create(job_name)
    status.last_started_at = started_at
    status.last_outcome = "running"
    status.updated_at = started_at
    status.last_error_type = None
    status.last_error_message = None
    await session.flush()


async def record_job_success(
    session: AsyncSession,
    *,
    job_name: str,
    finished_at: datetime,
) -> int:
    """Mark one job execution as successful and return previous failure streak."""
    repository = SystemJobStatusRepository(session)
    status = await repository.get_or_create(job_name)
    previous_failures = status.consecutive_failures
    status.last_succeeded_at = finished_at
    status.last_outcome = "success"
    status.consecutive_failures = 0
    status.last_error_type = None
    status.last_error_message = None
    status.updated_at = finished_at
    await session.flush()
    return previous_failures


async def record_job_failure(
    session: AsyncSession,
    *,
    job_name: str,
    failed_at: datetime,
    error: Exception,
) -> int:
    """Mark one job execution as failed and return the new failure streak."""
    repository = SystemJobStatusRepository(session)
    status = await repository.get_or_create(job_name)
    status.last_failed_at = failed_at
    status.last_outcome = "failure"
    status.consecutive_failures += 1
    status.last_error_type = error.__class__.__name__
    status.last_error_message = str(error)[:1000]
    status.updated_at = failed_at
    await session.flush()
    return status.consecutive_failures


async def maybe_send_system_alert(
    session: AsyncSession,
    *,
    bot: Bot,
    settings: Settings,
    kind: str,
    signature: str,
    text: str,
    now_utc: datetime | None = None,
) -> bool:
    """Persist and optionally send one deduplicated critical system alert."""
    current_utc = now_utc or utcnow()
    repository = SystemAlertEventRepository(session)
    alert = await repository.get_open_by_kind_signature(kind=kind, signature=signature)
    if alert is None:
        # No *open* alert with this signature, but a previously resolved one
        # may still exist — the UNIQUE constraint on (kind, signature) ignores
        # ``resolved_at``, so a fresh INSERT would clash. Reopen the existing
        # row instead.
        existing = await repository.get_any_by_kind_signature(kind=kind, signature=signature)
        if existing is None:
            alert = SystemAlertEvent(
                kind=kind,
                signature=signature,
                first_seen_at=current_utc,
                last_seen_at=current_utc,
                repeat_count=1,
            )
            session.add(alert)
        else:
            alert = existing
            alert.resolved_at = None
            alert.last_seen_at = current_utc
            alert.repeat_count = (alert.repeat_count or 0) + 1
        should_send = True
    else:
        alert.last_seen_at = current_utc
        alert.repeat_count += 1
        last_sent_at = _coerce_utc(alert.last_sent_at)
        should_send = (
            last_sent_at is None
            or (current_utc - last_sent_at).total_seconds()
            >= SYSTEM_ALERT_SUPPRESSION_MINUTES * 60
        )
    if should_send:
        await send_text_to_admins(
            bot,
            admin_tg_ids=settings.admin_tg_id_set,
            text=text,
        )
        alert.last_sent_at = current_utc
    await session.flush()
    return should_send


async def resolve_system_alert(
    session: AsyncSession,
    *,
    bot: Bot,
    settings: Settings,
    kind: str,
    signature: str,
    text: str,
    now_utc: datetime | None = None,
) -> bool:
    """Resolve one previously open system alert and optionally notify admins."""
    current_utc = now_utc or utcnow()
    repository = SystemAlertEventRepository(session)
    alert = await repository.get_open_by_kind_signature(kind=kind, signature=signature)
    if alert is None:
        return False
    alert.resolved_at = current_utc
    await send_text_to_admins(
        bot,
        admin_tg_ids=settings.admin_tg_id_set,
        text=text,
    )
    await session.flush()
    return True


async def update_system_timestamp(
    session: AsyncSession,
    *,
    key: str,
    value: datetime,
) -> None:
    """Persist one operational timestamp under the settings table."""
    await SettingRepository(session).upsert(key=key, value=value.astimezone(UTC).isoformat())
    await session.flush()
