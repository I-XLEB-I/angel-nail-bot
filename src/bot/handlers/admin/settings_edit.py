from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import remember_admin_panel, send_admin_panel
from src.bot.keyboards.admin import (
    ADMIN_SETTINGS_SECTIONS,
    build_admin_settings_diagnostics_keyboard,
    build_admin_settings_edit_keyboard,
    build_admin_settings_keyboard,
    build_admin_settings_section_keyboard,
)
from src.bot.states import AdminSettingsEdit
from src.bot.ui_utils import replace_inline_message_text, upsert_inline_panel
from src.config import Settings
from src.db.base import get_sqlite_runtime_pragmas, make_database_url
from src.db.repositories.settings import SettingRepository
from src.db.repositories.system_job_statuses import SystemJobStatusRepository
from src.db.repositories.templates import TemplateRepository
from src.services.admin_defaults import editable_setting_definitions
from src.services.runtime_settings import get_bool_setting, get_int_setting, get_runtime_tz
from src.services.studio_address import DEFAULT_STUDIO_ADDRESS_COPY_TEXT

router = Router(name="admin_settings_edit")

SETTING_TITLES = {
    "tz": "Часовой пояс",
    "master_telegram_username": "Telegram username Ангелы",
    "studio_address_copy_text": "Адрес для кнопки «Скопировать»",
    "repeat_prompt_weeks": "Repeat-prompt (недели)",
    "min_days_between_bookings": "Интервал между записями (дни)",
    "max_active_bookings_per_user": "Макс. активных записей на клиента",
    "frequent_booking_bypass_visits": "Постоянная клиентка после визитов",
    "reschedule_min_hours_before": "Перенос минимум за часов",
    "max_reschedules_per_booking": "Макс. переносов одной записи",
    "cancel_cooldown_minutes": "Пауза после отмены (мин)",
    "late_cancel_hours": "Поздняя отмена от часов",
    "late_cancel_strike_limit": "Порог late-cancel strikes",
    "no_show_strike_limit": "Порог no-show strikes",
    "proxy_messages_per_hour": "Proxy-сообщений в час",
    "ask_master_per_day": "Вопросов мастеру в день",
    "max_pending_approvals_per_user": "Макс. pending approvals",
    "booking_attempt_limit_window_minutes": "Окно антиспама записи",
    "booking_attempt_limit_count": "Попыток записи в окне",
    "booking_attempt_pause_minutes": "Пауза за спам записи",
    "late_notice_warning_minutes": "Порог предупреждения об опоздании",
    "unconfirmed_alert_before_minutes": "Алерт мастеру за сколько минут до записи",
    "unconfirmed_alert_after_minutes": "Пауза после напоминания (мин)",
    "repair_warranty_days": "Гарантия на ремонт (дни)",
    "repair_warranty_nails_limit": "Гарантия на ремонт (ногтей)",
    "repair_request_window_days": "Окно заявки на ремонт (дни)",
    "repair_default_duration_min": "Длительность гарантийного ремонта",
}

SETTING_PROMPTS = {
    "tz": "Пришли новый часовой пояс. Пример: Europe/Moscow.",
    "master_telegram_username": "Пришли username без @ или со знаком @.",
    "studio_address_copy_text": (
        "Пришли короткий адрес одним сообщением. Именно его клиентка получит "
        "по кнопке «Скопировать адрес»."
    ),
    "repeat_prompt_weeks": "Пришли целое число больше нуля.",
    "min_days_between_bookings": "Пришли целое число больше нуля.",
    "max_active_bookings_per_user": "Пришли целое число больше нуля.",
    "frequent_booking_bypass_visits": "Пришли целое число больше нуля.",
    "reschedule_min_hours_before": "Пришли целое число больше нуля.",
    "max_reschedules_per_booking": "Пришли целое число 0 или больше.",
    "cancel_cooldown_minutes": "Пришли целое число 0 или больше.",
    "late_cancel_hours": "Пришли целое число больше нуля.",
    "late_cancel_strike_limit": "Пришли целое число больше нуля.",
    "no_show_strike_limit": "Пришли целое число больше нуля.",
    "proxy_messages_per_hour": "Пришли целое число больше нуля.",
    "ask_master_per_day": "Пришли целое число больше нуля.",
    "max_pending_approvals_per_user": "Пришли целое число больше нуля.",
    "booking_attempt_limit_window_minutes": "Пришли целое число больше нуля.",
    "booking_attempt_limit_count": "Пришли целое число больше нуля.",
    "booking_attempt_pause_minutes": "Пришли целое число больше нуля.",
    "late_notice_warning_minutes": "Пришли целое число больше нуля.",
    "unconfirmed_alert_before_minutes": "Пришли целое число больше нуля.",
    "unconfirmed_alert_after_minutes": "Пришли целое число 0 или больше.",
    "repair_warranty_days": "Пришли целое число больше нуля.",
    "repair_warranty_nails_limit": "Пришли целое число больше нуля.",
    "repair_request_window_days": "Пришли целое число больше нуля.",
    "repair_default_duration_min": "Пришли целое число больше нуля.",
}


def humanize_bool(value: bool) -> str:
    """Render a boolean setting as a human-friendly checkmark."""
    return "✅" if value else "❌"


async def ensure_editable_settings(db_session: AsyncSession, settings: Settings) -> None:
    """Seed missing editable settings with defaults."""
    repository = SettingRepository(db_session)
    for definition in editable_setting_definitions(settings):
        if await repository.get_by_key(definition.key) is None:
            await repository.upsert(key=definition.key, value=definition.default_value)
    await db_session.commit()


async def render_settings_text(db_session: AsyncSession, settings: Settings) -> str:
    """Build the admin settings summary."""
    repository = SettingRepository(db_session)
    tz_name = await get_runtime_tz(repository, settings=settings)
    reminder_24h_enabled = await get_bool_setting(
        repository,
        key="reminder_24h_enabled",
        default=True,
    )
    master_telegram_username = await repository.get_value_or_default(
        "master_telegram_username",
        "ny_pip",
    )
    studio_address_copy_text = await repository.get_value_or_default(
        "studio_address_copy_text",
        DEFAULT_STUDIO_ADDRESS_COPY_TEXT,
    )
    reminder_2h_enabled = await get_bool_setting(
        repository,
        key="reminder_2h_enabled",
        default=settings.feature_reminder_2h,
    )
    unconfirmed_alert_enabled = await get_bool_setting(
        repository,
        key="unconfirmed_alert_enabled",
        default=True,
    )
    unconfirmed_alert_before_minutes = await get_int_setting(
        repository,
        key="unconfirmed_alert_before_minutes",
        default=90,
    )
    unconfirmed_alert_after_minutes = await get_int_setting(
        repository,
        key="unconfirmed_alert_after_minutes",
        default=20,
    )
    postvisit_enabled = await get_bool_setting(
        repository,
        key="postvisit_enabled",
        default=settings.feature_postvisit_feedback,
    )
    repeat_prompt_weeks = await get_int_setting(
        repository,
        key="repeat_prompt_weeks",
        default=3,
    )
    vacation_mode = await get_bool_setting(
        repository,
        key="vacation_mode",
        default=False,
    )
    schedule_image_enabled = await get_bool_setting(
        repository,
        key="schedule_image_enabled",
        default=False,
    )
    min_days_between_bookings = await get_int_setting(
        repository,
        key="min_days_between_bookings",
        default=17,
    )
    max_active_bookings_per_user = await get_int_setting(
        repository,
        key="max_active_bookings_per_user",
        default=1,
    )
    frequent_booking_bypass_visits = await get_int_setting(
        repository,
        key="frequent_booking_bypass_visits",
        default=5,
    )
    reschedule_min_hours_before = await get_int_setting(
        repository,
        key="reschedule_min_hours_before",
        default=48,
    )
    max_reschedules_per_booking = await get_int_setting(
        repository,
        key="max_reschedules_per_booking",
        default=2,
    )
    cancel_cooldown_minutes = await get_int_setting(
        repository,
        key="cancel_cooldown_minutes",
        default=30,
    )
    late_cancel_hours = await get_int_setting(
        repository,
        key="late_cancel_hours",
        default=4,
    )
    late_cancel_strike_limit = await get_int_setting(
        repository,
        key="late_cancel_strike_limit",
        default=3,
    )
    no_show_strike_limit = await get_int_setting(
        repository,
        key="no_show_strike_limit",
        default=2,
    )
    proxy_messages_per_hour = await get_int_setting(
        repository,
        key="proxy_messages_per_hour",
        default=5,
    )
    ask_master_per_day = await get_int_setting(
        repository,
        key="ask_master_per_day",
        default=3,
    )
    max_pending_approvals_per_user = await get_int_setting(
        repository,
        key="max_pending_approvals_per_user",
        default=5,
    )
    booking_attempt_limit_window_minutes = await get_int_setting(
        repository,
        key="booking_attempt_limit_window_minutes",
        default=10,
    )
    booking_attempt_limit_count = await get_int_setting(
        repository,
        key="booking_attempt_limit_count",
        default=5,
    )
    booking_attempt_pause_minutes = await get_int_setting(
        repository,
        key="booking_attempt_pause_minutes",
        default=30,
    )
    late_notice_warning_minutes = await get_int_setting(
        repository,
        key="late_notice_warning_minutes",
        default=15,
    )
    repair_warranty_days = await get_int_setting(
        repository,
        key="repair_warranty_days",
        default=14,
    )
    repair_warranty_nails_limit = await get_int_setting(
        repository,
        key="repair_warranty_nails_limit",
        default=2,
    )
    repair_request_window_days = await get_int_setting(
        repository,
        key="repair_request_window_days",
        default=30,
    )
    repair_default_duration_min = await get_int_setting(
        repository,
        key="repair_default_duration_min",
        default=30,
    )

    return "\n".join(
        [
            texts.ADMIN_SETTINGS_HEADER_TEXT,
            "",
            "🌐 Основное",
            f"  Часовой пояс: {tz_name}",
            f"  Telegram username: @{master_telegram_username.lstrip('@')}",
            f"  Адрес для копирования: {studio_address_copy_text}",
            f"  Режим отпуска: {humanize_bool(vacation_mode)}",
            "",
            "⏰ Уведомления",
            f"  Напоминание за 24h: {humanize_bool(reminder_24h_enabled)}",
            f"  Напоминание за 2h: {humanize_bool(reminder_2h_enabled)}",
            f"  Алерт мастеру без ответа: {humanize_bool(unconfirmed_alert_enabled)}",
            f"  Алерт мастеру за: {unconfirmed_alert_before_minutes} мин до записи",
            f"  Пауза после напоминания: {unconfirmed_alert_after_minutes} мин",
            f"  Пост-визитный опрос: {humanize_bool(postvisit_enabled)}",
            f"  Repeat-prompt через: {repeat_prompt_weeks} нед",
            f"  Картинка расписания: {humanize_bool(schedule_image_enabled)}",
            f"  Порог опоздания: {late_notice_warning_minutes} мин",
            "",
            "🛡 Anti-abuse",
            f"  Интервал между записями: {min_days_between_bookings} дн",
            f"  Активных записей на клиента: {max_active_bookings_per_user}",
            f"  Постоянная клиентка после: {frequent_booking_bypass_visits} визитов",
            f"  Перенос минимум за: {reschedule_min_hours_before} ч",
            f"  Макс. переносов: {max_reschedules_per_booking}",
            f"  Пауза после отмены: {cancel_cooldown_minutes} мин",
            f"  Поздняя отмена от: {late_cancel_hours} ч",
            f"  Порог late-cancel: {late_cancel_strike_limit} ударов",
            f"  Порог no-show: {no_show_strike_limit} ударов",
            "",
            "🔒 Лимиты",
            f"  Proxy-сообщений в час: {proxy_messages_per_hour}",
            f"  Вопросов мастеру в день: {ask_master_per_day}",
            f"  Макс. pending approvals: {max_pending_approvals_per_user}",
            (
                "  Антиспам записи: "
                f"{booking_attempt_limit_count} попыток / "
                f"{booking_attempt_limit_window_minutes} мин"
            ),
            f"  Пауза за спам: {booking_attempt_pause_minutes} мин",
            "",
            "🛠 Ремонт / гарантия",
            f"  Гарантия: {repair_warranty_days} дн / {repair_warranty_nails_limit} ногтя(ей)",
            f"  Окно заявки: {repair_request_window_days} дн",
            f"  Длительность ремонта: {repair_default_duration_min} мин",
        ]
    )


async def render_settings_section_text(
    db_session: AsyncSession, settings: Settings, *, section_key: str
) -> str:
    """Build a short category-specific settings screen."""
    title = ADMIN_SETTINGS_SECTIONS.get(section_key, ("⚙️ Настройки", ()))[0]
    return "\n".join(
        [
            texts.ADMIN_SETTINGS_HEADER_TEXT,
            "",
            title,
            "",
            "Выбери параметр ниже — я открою редактирование или переключу настройку.",
            "",
            "Текущие значения можно сверить на главном экране настроек.",
        ]
    )


async def render_settings_diagnostics_text(
    db_session: AsyncSession, settings: Settings
) -> str:
    """Render diagnostics for runtime DB-backed text/button settings."""
    settings_repository = SettingRepository(db_session)
    template_repository = TemplateRepository(db_session)
    job_repository = SystemJobStatusRepository(db_session)
    all_settings = await settings_repository.list_all()
    button_config_count = sum(1 for item in all_settings if item.key.startswith("button_config."))
    setting_map = {item.key: item.value for item in all_settings}
    job_statuses = {item.job_name: item for item in await job_repository.list_all()}
    sqlite_pragmas = await get_sqlite_runtime_pragmas(settings)
    greeting_header = await template_repository.get_content_or_default(
        "greeting_header",
        texts.MENU_HEADER,
    )
    portfolio_intro = await template_repository.get_content_or_default(
        "portfolio_intro",
        texts.PORTFOLIO_INTRO,
    )
    about_master = await template_repository.get_content_or_default(
        "about_master",
        texts.DEFAULT_ABOUT_MASTER_TEMPLATE,
    )
    database_url = make_database_url(settings)
    db_location = database_url.database or settings.database_url
    greeting_preview = greeting_header.strip().replace("\n", " ")[:140]
    portfolio_preview = portfolio_intro.strip().replace("\n", " ")[:140]
    about_preview = about_master.strip().replace("\n", " ")[:140]
    backup_at = setting_map.get("system.last_backup_at", "—")
    restore_at = setting_map.get("system.last_restore_at", "—")
    integrity_at = setting_map.get("system.last_integrity_check_at", "—")
    tracked_jobs = [
        "reminder_24h_and_2h",
        "unconfirmed_alerts",
        "mark_completed",
        "postvisit",
        "repeat_prompt",
        "winback_prompts",
        "morning_summary",
        "gcal_pull",
        "sqlite_integrity_check",
    ]
    job_lines: list[str] = []
    for job_name in tracked_jobs:
        status = job_statuses.get(job_name)
        if status is None:
            job_lines.append(f"• {job_name}: —")
            continue
        if status.last_outcome == "failure":
            suffix = (
                "ошибка "
                f"{status.last_error_type or 'Unknown'} · подряд {status.consecutive_failures}"
            )
        elif status.last_succeeded_at is not None:
            suffix = f"ok · {status.last_succeeded_at.isoformat()}"
        elif status.last_started_at is not None:
            suffix = f"started · {status.last_started_at.isoformat()}"
        else:
            suffix = "—"
        job_lines.append(f"• {job_name}: {suffix}")
    return "\n".join(
        [
            "🧭 Диагностика бота",
            "",
            f"База: {db_location}",
            f"button_config.*: {button_config_count}",
            f"Google Calendar: {'вкл' if settings.gcal_enabled else 'выкл'}",
            (
                "SQLite runtime: "
                f"WAL={sqlite_pragmas.get('journal_mode') if sqlite_pragmas else '—'} · "
                f"busy_timeout={sqlite_pragmas.get('busy_timeout') if sqlite_pragmas else '—'} · "
                f"foreign_keys={sqlite_pragmas.get('foreign_keys') if sqlite_pragmas else '—'} · "
                f"synchronous={sqlite_pragmas.get('synchronous') if sqlite_pragmas else '—'}"
            ),
            "",
            f"Последний backup: {backup_at}",
            f"Последний restore: {restore_at}",
            f"Последний integrity_check: {integrity_at}",
            "",
            "Фоновые джобы:",
            *job_lines,
            "",
            "Эффективные шаблоны сейчас:",
            f"• greeting_header: {greeting_preview or '—'}",
            f"• portfolio_intro: {portfolio_preview or '—'}",
            f"• about_master: {about_preview or '—'}",
            "",
            "Если после обновления текст/emoji выглядят старыми, бот почти всегда "
            "запущен на другой БД или в БД сохранён старый шаблон.",
        ]
    )


def render_setting_edit_text(key: str, *, error_text: str | None = None) -> str:
    """Build the inline prompt while waiting for a new setting value."""
    title = SETTING_TITLES.get(key, key)
    prompt = SETTING_PROMPTS.get(key, texts.ADMIN_SETTINGS_VALUE_PROMPT_TEXT)
    lines = [texts.ADMIN_SETTINGS_EDIT_PROMPT_TEXT.format(title=title, prompt=prompt)]
    if error_text:
        lines.extend(["", error_text])
    return "\n".join(lines)


async def show_settings(
    message: Message,
    *,
    db_session: AsyncSession,
    settings: Settings,
    state: FSMContext | None = None,
    edit: bool = False,
) -> Message | None:
    """Show the runtime settings dashboard."""
    await ensure_editable_settings(db_session, settings)
    text = await render_settings_text(db_session, settings)
    if edit:
        await replace_inline_message_text(
            message,
            text,
            reply_markup=build_admin_settings_keyboard(),
        )
        if state is not None:
            await remember_admin_panel(state, message)
        return None
    if state is not None:
        return await send_admin_panel(
            message,
            state,
            text=text,
            reply_markup=build_admin_settings_keyboard(),
        )
    return await message.answer(
        text,
        reply_markup=build_admin_settings_keyboard(),
    )


@router.callback_query(F.data == "admin_settings:home")
async def settings_home(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Return to top-level settings categories."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await show_settings(
            callback.message,
            db_session=db_session,
            settings=settings,
            edit=True,
            state=state,
        )


@router.callback_query(F.data.startswith("admin_settings:section:"))
async def open_settings_section(
    callback: CallbackQuery,
    *,
    is_admin: bool,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Open one settings category."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    section_key = callback.data.rsplit(":", 1)[-1]
    await replace_inline_message_text(
        callback.message,
        await render_settings_section_text(db_session, settings, section_key=section_key),
        reply_markup=build_admin_settings_section_keyboard(section_key),
    )


@router.callback_query(F.data == "admin_settings:diagnostics")
async def open_settings_diagnostics(
    callback: CallbackQuery,
    *,
    is_admin: bool,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Show DB-backed runtime setting diagnostics."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await replace_inline_message_text(
            callback.message,
            await render_settings_diagnostics_text(db_session, settings),
            reply_markup=build_admin_settings_diagnostics_keyboard(),
        )


@router.message(lambda message: message.text == "⚙️ Настройки")
async def open_settings(
    message: Message,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Open the admin settings section."""
    if not is_admin:
        return
    await show_settings(message, db_session=db_session, settings=settings, state=state)


@router.callback_query(F.data.startswith("admin_settings:toggle:"))
async def toggle_setting(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Toggle a boolean runtime setting."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    key = callback.data.rsplit(":", 1)[-1]
    repository = SettingRepository(db_session)
    current_value = await get_bool_setting(repository, key=key, default=False)
    await repository.upsert(key=key, value="false" if current_value else "true")
    await db_session.commit()
    if callback.message is not None:
        await show_settings(
            callback.message,
            db_session=db_session,
            settings=settings,
            edit=True,
            state=state,
        )


@router.callback_query(F.data.startswith("admin_settings:edit:"))
async def prompt_setting_edit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Prompt for a text/integer runtime setting value."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    key = callback.data.rsplit(":", 1)[-1]
    await state.set_state(AdminSettingsEdit.input_value)
    if callback.message is not None:
        await state.update_data(
            admin_settings_key=key,
            admin_settings_panel_chat_id=callback.message.chat.id,
            admin_settings_panel_message_id=callback.message.message_id,
        )
        await replace_inline_message_text(
            callback.message,
            render_setting_edit_text(key),
            reply_markup=build_admin_settings_edit_keyboard(),
        )


@router.callback_query(F.data == "admin_settings:cancel_edit")
async def cancel_setting_edit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Cancel one settings edit and restore the dashboard."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await show_settings(
            callback.message,
            db_session=db_session,
            settings=settings,
            edit=True,
            state=state,
        )


@router.message(StateFilter(AdminSettingsEdit.input_value))
async def save_setting_value(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    """Persist a manually entered runtime setting."""
    data = await state.get_data()
    key = str(data.get("admin_settings_key"))
    panel_chat_id = int(data.get("admin_settings_panel_chat_id"))
    panel_message_id = int(data.get("admin_settings_panel_message_id"))
    raw_value = (message.text or "").strip()
    repository = SettingRepository(db_session)

    if key == "tz":
        try:
            ZoneInfo(raw_value)
        except ZoneInfoNotFoundError:
            await upsert_inline_panel(
                message.bot,
                chat_id=panel_chat_id,
                message_id=panel_message_id,
                text=render_setting_edit_text(key, error_text=texts.ADMIN_SETTINGS_INVALID_TZ_TEXT),
                reply_markup=build_admin_settings_edit_keyboard(),
            )
            return
        value = raw_value
    elif key == "master_telegram_username":
        normalized = raw_value.lstrip("@").strip()
        if not normalized or any(char.isspace() for char in normalized):
            await upsert_inline_panel(
                message.bot,
                chat_id=panel_chat_id,
                message_id=panel_message_id,
                text=render_setting_edit_text(
                    key,
                    error_text="Нужен Telegram username без пробелов. Пример: angelsnailspace",
                ),
                reply_markup=build_admin_settings_edit_keyboard(),
            )
            return
        value = normalized
    elif key == "studio_address_copy_text":
        if len(raw_value) < 5 or len(raw_value) > 200:
            await upsert_inline_panel(
                message.bot,
                chat_id=panel_chat_id,
                message_id=panel_message_id,
                text=render_setting_edit_text(
                    key,
                    error_text="Нужен адрес длиной от 5 до 200 символов.",
                ),
                reply_markup=build_admin_settings_edit_keyboard(),
            )
            return
        value = raw_value
    elif key in {
        "repeat_prompt_weeks",
        "min_days_between_bookings",
        "max_active_bookings_per_user",
        "frequent_booking_bypass_visits",
        "reschedule_min_hours_before",
        "max_reschedules_per_booking",
        "cancel_cooldown_minutes",
        "late_cancel_hours",
        "late_cancel_strike_limit",
        "no_show_strike_limit",
        "proxy_messages_per_hour",
        "ask_master_per_day",
        "max_pending_approvals_per_user",
        "booking_attempt_limit_window_minutes",
        "booking_attempt_limit_count",
        "booking_attempt_pause_minutes",
        "late_notice_warning_minutes",
        "repair_warranty_days",
        "repair_warranty_nails_limit",
        "repair_request_window_days",
        "repair_default_duration_min",
    }:
        try:
            parsed = int(raw_value)
            if key in {"max_reschedules_per_booking", "cancel_cooldown_minutes"}:
                if parsed < 0:
                    raise ValueError
            elif parsed <= 0:
                raise ValueError
        except ValueError:
            await upsert_inline_panel(
                message.bot,
                chat_id=panel_chat_id,
                message_id=panel_message_id,
                text=render_setting_edit_text(
                    key,
                    error_text=texts.ADMIN_SETTINGS_INVALID_INT_TEXT,
                ),
                reply_markup=build_admin_settings_edit_keyboard(),
            )
            return
        value = str(parsed)
    else:
        value = raw_value

    await repository.upsert(key=key, value=value)
    await db_session.commit()
    await state.clear()
    await upsert_inline_panel(
        message.bot,
        chat_id=panel_chat_id,
        message_id=panel_message_id,
        text=await render_settings_text(db_session, settings),
        reply_markup=build_admin_settings_keyboard(),
    )
