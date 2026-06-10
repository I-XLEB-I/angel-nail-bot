from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import send_admin_panel
from src.bot.keyboards.admin import build_admin_stats_period_keyboard
from src.bot.ui_utils import replace_inline_message_text
from src.config import Settings
from src.db.repositories.bookings import BookingPeriodStats, BookingRepository
from src.db.repositories.settings import SettingRepository
from src.services.runtime_settings import get_runtime_tz

router = Router(name="admin_stats")


def build_period_bounds(
    period: str,
    *,
    now_local: datetime,
) -> tuple[str, datetime | None, datetime | None]:
    """Return the display label and UTC bounds for a stats period."""
    tz = now_local.tzinfo
    if period == "all":
        return "за всё время", None, None

    if period == "previous":
        year = now_local.year
        month = now_local.month - 1
        if month == 0:
            month = 12
            year -= 1
        start_local = datetime(year, month, 1, 0, 0, 0, tzinfo=tz)
        if month == 12:
            end_local = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=tz)
        else:
            end_local = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=tz)
        return (
            start_local.strftime("%m.%Y"),
            start_local.astimezone(UTC),
            end_local.astimezone(UTC),
        )

    start_local = datetime(now_local.year, now_local.month, 1, 0, 0, 0, tzinfo=tz)
    if now_local.month == 12:
        end_local = datetime(now_local.year + 1, 1, 1, 0, 0, 0, tzinfo=tz)
    else:
        end_local = datetime(now_local.year, now_local.month + 1, 1, 0, 0, 0, tzinfo=tz)
    return (
        start_local.strftime("%m.%Y"),
        start_local.astimezone(UTC),
        end_local.astimezone(UTC),
    )


def render_stats_text(period_label: str, stats: BookingPeriodStats) -> str:
    """Render the admin statistics dashboard."""
    top_services_lines = (
        [
            f"{index}. {name} — {count}"
            for index, (name, count) in enumerate(stats.top_services, start=1)
        ]
        if stats.top_services
        else ["1. —", "2. —", "3. —"]
    )
    lines = [
        f"{texts.ADMIN_STATS_TITLE_TEXT} — {period_label}",
        "",
        f"Записей всего: {stats.total_bookings}",
        "",
        f"Завершено: {stats.completed_count}",
        "",
        f"Отменено клиенткой: {stats.cancelled_by_client_count}",
        f"🤒 Плохо: {stats.cancel_reason_counts.get('sick', 0)}",
        f"📅 Не успела: {stats.cancel_reason_counts.get('busy', 0)}",
        f"🚨 Форс-мажор: {stats.cancel_reason_counts.get('force_majeure', 0)}",
        f"💅 Позже: {stats.cancel_reason_counts.get('later', 0)}",
        f"🚫 Не планирует: {stats.cancel_reason_counts.get('not_planning', 0)}",
        f"✏️ Другое: {stats.cancel_reason_counts.get('other', 0)}",
        "",
        f"Отменено мастером: {stats.cancelled_by_master_count}",
        f"No-show: {stats.no_show_count}",
        "",
        f"Выручка: {stats.revenue}₽",
        "",
        f"Новых клиенток: {stats.new_clients}",
        "",
        "Топ-3 услуг:",
        *top_services_lines,
    ]
    return "\n".join(lines)


async def show_stats(
    message: Message,
    *,
    db_session: AsyncSession,
    settings: Settings,
    period: str,
    state: FSMContext | None = None,
    edit: bool = False,
) -> None:
    """Show admin statistics for a selected period."""
    settings_repository = SettingRepository(db_session)
    tz_name = await get_runtime_tz(settings_repository, settings=settings)
    now_local = datetime.now(ZoneInfo(tz_name))
    period_label, start_utc, end_utc = build_period_bounds(period, now_local=now_local)
    repository = BookingRepository(db_session)
    stats = await repository.get_period_stats(start_utc=start_utc, end_utc=end_utc)
    text = render_stats_text(period_label, stats)
    reply_markup = build_admin_stats_period_keyboard(period)
    if state is not None:
        await send_admin_panel(message, state, text=text, reply_markup=reply_markup)
        return
    if edit:
        await replace_inline_message_text(message, text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


@router.message(lambda message: message.text == "📊 Статистика")
async def open_stats(
    message: Message,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Open admin statistics."""
    if not is_admin:
        return
    await show_stats(
        message,
        db_session=db_session,
        settings=settings,
        period="current",
        state=state,
    )


@router.callback_query(F.data.startswith("admin_stats:period:"))
async def switch_stats_period(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Switch the displayed admin statistics period."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    period = callback.data.rsplit(":", 1)[-1]
    if callback.message is not None:
        await show_stats(
            callback.message,
            db_session=db_session,
            settings=settings,
            period=period,
            edit=True,
            state=state,
        )
