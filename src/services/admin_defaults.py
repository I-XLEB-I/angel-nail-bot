from __future__ import annotations

from dataclasses import dataclass, field

from src.bot import texts
from src.config import Settings
from src.services.button_configs import DEFAULT_MASTER_TELEGRAM_USERNAME
from src.services.studio_address import DEFAULT_STUDIO_ADDRESS_COPY_TEXT


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    """Definition of an editable runtime setting."""

    key: str
    label: str
    kind: str
    default_value: str


@dataclass(frozen=True, slots=True)
class TemplateCategory:
    """Presentation metadata for a template category in the admin UI."""

    key: str
    title: str


@dataclass(frozen=True, slots=True)
class TemplateDefinition:
    """Definition of an editable text template."""

    key: str
    title: str
    description: str
    category_key: str
    default_content: str
    variables: tuple[str, ...] = field(default_factory=tuple)
    required_variables: tuple[str, ...] | None = None
    supports_media: bool = False


TEMPLATE_CATEGORIES: tuple[TemplateCategory, ...] = (
    TemplateCategory(key="clients", title="💌 Клиентам"),
    TemplateCategory(key="address", title="🏠 Адрес и навигация"),
    TemplateCategory(key="schedule", title="🗓 Расписание"),
    TemplateCategory(key="other", title="🌴 Другое"),
)


TEMPLATE_DEFINITIONS: tuple[TemplateDefinition, ...] = (
    TemplateDefinition(
        key="booking_confirm",
        title="✅ Подтверждение записи",
        description=(
            "Сразу после записи клиентки; картинка статичная, поэтому адрес "
            "на ней меняется отдельно"
        ),
        category_key="clients",
        default_content=texts.DEFAULT_BOOKING_CONFIRM_TEMPLATE,
        variables=("name", "date", "time", "service", "payment", "address", "address_block"),
        required_variables=("date", "time", "service", "payment", "address_block"),
        supports_media=True,
    ),
    TemplateDefinition(
        key="reminder_24h",
        title="🔔 Напоминание за сутки",
        description="За 24 часа до визита",
        category_key="clients",
        default_content=texts.DEFAULT_REMINDER_24H_TEMPLATE,
        variables=(
            "name",
            "display_name",
            "date",
            "time",
            "service",
            "service_name",
            "address",
            "address_short",
            "address_text",
        ),
        required_variables=("date", "time", "service", "address_short"),
        supports_media=True,
    ),
    TemplateDefinition(
        key="reminder_2h",
        title="⏰ Напоминание за 2 часа",
        description="За 2 часа до визита",
        category_key="clients",
        default_content=texts.DEFAULT_REMINDER_2H_TEMPLATE,
        variables=("name", "date", "time", "service", "service_name"),
        required_variables=("time",),
        supports_media=True,
    ),
    TemplateDefinition(
        key="postvisit",
        title="🌷 После визита",
        description="Через несколько часов после визита",
        category_key="clients",
        default_content=texts.DEFAULT_POSTVISIT_TEMPLATE,
        variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="postvisit_rating_5",
        title="⭐⭐⭐⭐⭐ Ответ на 5 звёзд",
        description="Сообщение после оценки 5 звёзд",
        category_key="clients",
        default_content=texts.DEFAULT_POSTVISIT_RATING_5_TEMPLATE,
        variables=(),
    ),
    TemplateDefinition(
        key="postvisit_rating_mid",
        title="⭐⭐⭐ Ответ на 3-4 звезды",
        description="Сообщение после оценки 3-4 звёзд + просьба фидбека",
        category_key="clients",
        default_content=texts.DEFAULT_POSTVISIT_RATING_MID_TEMPLATE,
        variables=(),
    ),
    TemplateDefinition(
        key="postvisit_rating_low",
        title="⭐ Ответ на 1-2 звезды",
        description="Сообщение после оценки 1-2 звёзд + переход в чат с мастером",
        category_key="clients",
        default_content=texts.DEFAULT_POSTVISIT_RATING_LOW_TEMPLATE,
        variables=(),
    ),
    TemplateDefinition(
        key="repeat_prompt",
        title="🔄 Приглашение повторить",
        description="Через несколько недель после визита",
        category_key="clients",
        default_content=texts.DEFAULT_REPEAT_PROMPT_TEMPLATE,
        variables=("name", "display_name"),
        required_variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="winback_lapsed",
        title="🌸 Возврат давних клиентов",
        description="Клиент не приходил дольше N дней (по умолчанию 60)",
        category_key="clients",
        default_content=texts.DEFAULT_WINBACK_TEMPLATE,
        variables=("display_name",),
        required_variables=("display_name",),
        supports_media=True,
    ),
    TemplateDefinition(
        key="late_notice_intro",
        title="⏰ Опоздание — интро",
        description="Экран, где клиентка предупреждает об опоздании",
        category_key="clients",
        default_content=texts.DEFAULT_LATE_NOTICE_INTRO_TEMPLATE,
        variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="late_notice_client_sent",
        title="⏰ Опоздание — отправлено",
        description="Сообщение клиентке после обычного предупреждения об опоздании",
        category_key="clients",
        default_content=texts.LATE_NOTICE_CLIENT_SENT_DEFAULT_TEXT,
        variables=("minutes", "date", "time", "service", "reason", "comment"),
        required_variables=("minutes",),
    ),
    TemplateDefinition(
        key="late_notice_client_risky",
        title="⏰ Опоздание — риск",
        description="Сообщение клиентке при заметном опоздании",
        category_key="clients",
        default_content=texts.LATE_NOTICE_CLIENT_RISKY_DEFAULT_TEXT,
        variables=("minutes", "date", "time", "service", "reason", "comment"),
        required_variables=("minutes",),
    ),
    TemplateDefinition(
        key="repair_intro",
        title="🛠 Ремонт / гарантия — интро",
        description="Экран подачи заявки на ремонт после завершённой записи",
        category_key="clients",
        default_content=texts.DEFAULT_REPAIR_INTRO_TEMPLATE,
        variables=("date", "service", "warranty_days", "nails_limit"),
        required_variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="repair_request_received",
        title="🛠 Ремонт / гарантия — заявка принята",
        description="Подтверждение клиентке, что заявка на ремонт ушла Ангеле",
        category_key="clients",
        default_content=texts.DEFAULT_REPAIR_REQUEST_RECEIVED_TEMPLATE,
        variables=("date", "service", "issue", "nails_count"),
        required_variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="repair_warranty_offer",
        title="🛠 Ремонт / гарантия — предложение времени",
        description="Сообщение клиентке, когда Ангела предлагает время для гарантийного ремонта",
        category_key="clients",
        default_content=texts.DEFAULT_REPAIR_WARRANTY_OFFER_TEMPLATE,
        variables=("date", "time", "service"),
        required_variables=("date", "time", "service"),
    ),
    TemplateDefinition(
        key="repair_not_warranty",
        title="🛠 Ремонт / гарантия — не гарантия",
        description=(
            "Мягкий текст, когда случай не попадает под гарантию "
            "и требует ручного согласования"
        ),
        category_key="clients",
        default_content=texts.DEFAULT_REPAIR_NOT_WARRANTY_TEMPLATE,
        variables=(),
    ),
    TemplateDefinition(
        key="repair_declined",
        title="🛠 Ремонт / гарантия — отказ",
        description="Текст, когда Ангела пока не может принять заявку на ремонт",
        category_key="clients",
        default_content=texts.DEFAULT_REPAIR_DECLINED_TEMPLATE,
        variables=(),
    ),
    TemplateDefinition(
        key="decline_repeat_booking_reason",
        title="🔁 Отказ: повторная запись",
        description="Готовая мягкая причина отказа для повторной записи",
        category_key="clients",
        default_content=texts.DEFAULT_REPEAT_BOOKING_DECLINE_REASON,
        variables=(),
    ),
    TemplateDefinition(
        key="navigation",
        title="📍 Адрес (после записи)",
        description=(
            "Скрытый legacy-шаблон адреса после записи; клиенткам обычно "
            "не показывается напрямую"
        ),
        category_key="address",
        default_content=texts.DEFAULT_ADDRESS_POST_CONFIRM,
        variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="navigation_public",
        title="📍 Публичный адрес + картинка",
        description=(
            "Показывается до записи: отдельный экран с публичным текстом и картинкой"
        ),
        category_key="address",
        default_content=texts.DEFAULT_ADDRESS_PUBLIC_TEMPLATE,
        variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="address_post_confirm",
        title="🔐 Полный адрес — только текст",
        description=(
            "Текст полного адреса для подтверждения и напоминания; картинка "
            "редактируется в шаблоне «Подтверждение записи»"
        ),
        category_key="address",
        default_content=texts.DEFAULT_ADDRESS_POST_CONFIRM,
        variables=(),
    ),
    TemplateDefinition(
        key="schedule_caption_text",
        title="Подпись картинки расписания",
        description="Короткая подпись внизу 9:16 картинки со свободными окнами",
        category_key="schedule",
        default_content=texts.DEFAULT_SCHEDULE_CAPTION_TEXT,
        variables=(),
    ),
    TemplateDefinition(
        key="price",
        title="💰 Прайс",
        description=(
            "Раздел «Услуги и цены» с текстом и картинкой; картинка статичная "
            "и не меняется автоматически вместе с ценами услуг"
        ),
        category_key="clients",
        default_content=texts.DEFAULT_PRICE_TEMPLATE,
        variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="greeting_header",
        title="Приветствие",
        description="Текст и картинка главной страницы клиентки",
        category_key="other",
        default_content=texts.MENU_HEADER,
        variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="admin_menu_text",
        title="Текст админ-меню",
        description="Главная админ-панель с краткой сводкой",
        category_key="other",
        default_content=texts.ADMIN_MENU_TEXT,
        variables=("pending_approvals", "today_bookings"),
    ),
    TemplateDefinition(
        key="vacation_notice",
        title="Отпуск",
        description="Показывается, когда включён режим отпуска",
        category_key="other",
        default_content=texts.DEFAULT_VACATION_NOTICE,
        variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="rules",
        title="Правила визита",
        description="Вспомогательный шаблон правил визита",
        category_key="other",
        default_content=texts.DEFAULT_RULES,
        variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="portfolio_intro",
        title="Портфолио",
        description="Текст на объединённом экране «О Ангеле»; картинка задаётся соседним шаблоном",
        category_key="other",
        default_content=texts.PORTFOLIO_INTRO,
        variables=(),
    ),
    TemplateDefinition(
        key="about_master",
        title="🌷 О Ангеле",
        description="Раздел «О Ангеле» в главном меню — короткое знакомство с мастером",
        category_key="other",
        default_content=texts.DEFAULT_ABOUT_MASTER_TEMPLATE,
        variables=(),
        supports_media=True,
    ),
    TemplateDefinition(
        key="force_majeure_notice",
        title="🌷 Форс-мажор (шаблон по умолчанию)",
        description="Текст уведомления клиенту при массовой отмене дня",
        category_key="clients",
        default_content=texts.DEFAULT_FORCE_MAJEURE_TEMPLATE,
        variables=(),
    ),
)


def list_template_categories() -> tuple[TemplateCategory, ...]:
    """Return editable template categories in UI order."""
    return TEMPLATE_CATEGORIES


def list_template_definitions(*, category_key: str | None = None) -> list[TemplateDefinition]:
    """Return editable template definitions, optionally filtered by category."""
    items = list(TEMPLATE_DEFINITIONS)
    if category_key is None:
        return items
    return [item for item in items if item.category_key == category_key]


def get_template_definition(key: str) -> TemplateDefinition | None:
    """Return template metadata by key."""
    for definition in TEMPLATE_DEFINITIONS:
        if definition.key == key:
            return definition
    return None


def required_template_defaults() -> dict[str, str]:
    """Return default contents for required editable templates."""
    return {definition.key: definition.default_content for definition in TEMPLATE_DEFINITIONS}


def editable_setting_definitions(settings: Settings) -> list[SettingDefinition]:
    """Return the settings managed from the admin panel."""
    return [
        SettingDefinition(
            key="tz",
            label="Часовой пояс",
            kind="text",
            default_value=settings.tz,
        ),
        SettingDefinition(
            key="master_telegram_username",
            label="Telegram username Ангелы",
            kind="text",
            default_value=DEFAULT_MASTER_TELEGRAM_USERNAME,
        ),
        SettingDefinition(
            key="studio_address_copy_text",
            label="Адрес для кнопки «Скопировать»",
            kind="text",
            default_value=DEFAULT_STUDIO_ADDRESS_COPY_TEXT,
        ),
        SettingDefinition(
            key="reminder_24h_enabled",
            label="Напоминание за 24 часа",
            kind="bool",
            default_value="true",
        ),
        SettingDefinition(
            key="reminder_2h_enabled",
            label="Напоминание за 2 часа",
            kind="bool",
            default_value="true" if settings.feature_reminder_2h else "false",
        ),
        SettingDefinition(
            key="unconfirmed_alert_enabled",
            label="Алерты мастеру по неподтверждённым напоминаниям",
            kind="bool",
            default_value="true",
        ),
        SettingDefinition(
            key="unconfirmed_alert_before_minutes",
            label="За сколько минут до записи слать алерт мастеру",
            kind="int",
            default_value="90",
        ),
        SettingDefinition(
            key="unconfirmed_alert_after_minutes",
            label="Минимальная пауза после напоминания",
            kind="int",
            default_value="20",
        ),
        SettingDefinition(
            key="postvisit_enabled",
            label="Пост-визитный опрос",
            kind="bool",
            default_value="true" if settings.feature_postvisit_feedback else "false",
        ),
        SettingDefinition(
            key="repeat_prompt_weeks",
            label="Repeat-prompt через недель",
            kind="int",
            default_value="3",
        ),
        SettingDefinition(
            key="winback_enabled",
            label="Win-back (возврат давних клиентов)",
            kind="bool",
            default_value="true",
        ),
        SettingDefinition(
            key="winback_days",
            label="Win-back через дней без визита",
            kind="int",
            default_value="60",
        ),
        SettingDefinition(
            key="morning_summary_enabled",
            label="Утренняя сводка (08:00)",
            kind="bool",
            default_value="true",
        ),
        SettingDefinition(
            key="vacation_mode",
            label="Режим отпуска",
            kind="bool",
            default_value="false",
        ),
        SettingDefinition(
            key="schedule_image_enabled",
            label="Картинка расписания",
            kind="bool",
            default_value="false",
        ),
        SettingDefinition(
            key="late_notice_warning_minutes",
            label="Порог предупреждения об опоздании (мин)",
            kind="int",
            default_value="15",
        ),
        SettingDefinition(
            key="min_days_between_bookings",
            label="Интервал между записями (дни)",
            kind="int",
            default_value="17",
        ),
        SettingDefinition(
            key="max_active_bookings_per_user",
            label="Макс. активных записей на клиента",
            kind="int",
            default_value="1",
        ),
        SettingDefinition(
            key="frequent_booking_bypass_visits",
            label="Постоянная клиентка после визитов",
            kind="int",
            default_value="5",
        ),
        SettingDefinition(
            key="reschedule_min_hours_before",
            label="Перенос минимум за часов",
            kind="int",
            default_value="48",
        ),
        SettingDefinition(
            key="max_reschedules_per_booking",
            label="Макс. переносов одной записи",
            kind="int",
            default_value="2",
        ),
        SettingDefinition(
            key="cancel_cooldown_minutes",
            label="Пауза после отмены (мин)",
            kind="int",
            default_value="30",
        ),
        SettingDefinition(
            key="late_cancel_hours",
            label="Поздняя отмена от часов",
            kind="int",
            default_value="4",
        ),
        SettingDefinition(
            key="late_cancel_strike_limit",
            label="Порог late-cancel strikes",
            kind="int",
            default_value="3",
        ),
        SettingDefinition(
            key="no_show_strike_limit",
            label="Порог no-show strikes",
            kind="int",
            default_value="2",
        ),
        SettingDefinition(
            key="proxy_messages_per_hour",
            label="Proxy-сообщений в час",
            kind="int",
            default_value="5",
        ),
        SettingDefinition(
            key="ask_master_per_day",
            label="Вопросов мастеру в день",
            kind="int",
            default_value="3",
        ),
        SettingDefinition(
            key="max_pending_approvals_per_user",
            label="Макс. pending approvals",
            kind="int",
            default_value="5",
        ),
        SettingDefinition(
            key="booking_attempt_limit_window_minutes",
            label="Окно антиспама записи (мин)",
            kind="int",
            default_value="10",
        ),
        SettingDefinition(
            key="booking_attempt_limit_count",
            label="Попыток записи в окне",
            kind="int",
            default_value="5",
        ),
        SettingDefinition(
            key="booking_attempt_pause_minutes",
            label="Пауза за спам записи (мин)",
            kind="int",
            default_value="30",
        ),
        SettingDefinition(
            key="repair_warranty_days",
            label="Гарантия на ремонт (дни)",
            kind="int",
            default_value="14",
        ),
        SettingDefinition(
            key="repair_warranty_nails_limit",
            label="Гарантия на ремонт (ногтей)",
            kind="int",
            default_value="2",
        ),
        SettingDefinition(
            key="repair_request_window_days",
            label="Окно заявки на ремонт (дни)",
            kind="int",
            default_value="30",
        ),
        SettingDefinition(
            key="repair_default_duration_min",
            label="Длительность гарантийного ремонта (мин)",
            kind="int",
            default_value="30",
        ),
    ]
