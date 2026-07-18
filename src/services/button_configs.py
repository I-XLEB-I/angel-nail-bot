from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote

from aiogram.enums import ButtonStyle

from src.db.repositories.settings import SettingRepository

MASTER_TELEGRAM_USERNAME_SETTING_KEY = "master_telegram_username"
DEFAULT_MASTER_TELEGRAM_USERNAME = "ny_pip"
ANGELA_CHAT_DEFAULT_TEXT = "Здравствуйте, хочу уточнить по поводу записи на Маникюр 🌸"
PORTFOLIO_CUSTOM_EMOJI_ID = "5370607250731718891"
DEFAULT_PORTFOLIO_CHANNEL_URL = "https://t.me/angelsnailspace"
LEGACY_DEFAULT_ADDRESS_MAP_URL = (
    "https://yandex.ru/maps/213/moscow/house/ochakovskoye_shosse_5k3/"
    "Z04YcgFhTkEFQFtvfXp4dXtqbQ==/?indoorLevel=1&ll=37.461811%2C55.694677&z=17.96"
)
PREVIOUS_DEFAULT_ADDRESS_MAP_URL = (
    "https://yandex.ru/maps/213/moscow/search/"
    "%D0%9E%D1%87%D0%B0%D0%BA%D0%BE%D0%B2%D1%81%D0%BA%D0%BE%D0%B5%20"
    "%D1%88%D0%BE%D1%81%D1%81%D0%B5%205%D0%BA4/"
)
DEFAULT_ADDRESS_MAP_URL = "https://yandex.ru/maps/-/CTRpjUkQ"

BUTTON_STYLE_DEFAULT = "default"
BUTTON_STYLE_PRIMARY = "primary"
BUTTON_STYLE_SUCCESS = "success"
BUTTON_STYLE_DANGER = "danger"

BUTTON_STYLE_VALUES = {
    BUTTON_STYLE_DEFAULT,
    BUTTON_STYLE_PRIMARY,
    BUTTON_STYLE_SUCCESS,
    BUTTON_STYLE_DANGER,
}
BUTTON_STYLE_LABELS = {
    BUTTON_STYLE_DEFAULT: "Обычный",
    BUTTON_STYLE_PRIMARY: "Синий",
    BUTTON_STYLE_SUCCESS: "Зелёный",
    BUTTON_STYLE_DANGER: "Красный",
}


def build_angela_chat_url(username: str | None = None) -> str:
    """Build the direct Telegram-chat URL for the current master username."""
    normalized_username = (username or DEFAULT_MASTER_TELEGRAM_USERNAME).strip().lstrip("@")
    if not normalized_username:
        normalized_username = DEFAULT_MASTER_TELEGRAM_USERNAME
    return (
        f"tg://resolve?domain={quote(normalized_username, safe='')}"
        f"&text={quote(ANGELA_CHAT_DEFAULT_TEXT, safe='')}"
    )


ANGELA_CHAT_URL = build_angela_chat_url()


@dataclass(frozen=True, slots=True)
class ButtonEditorCategory:
    """Presentation metadata for a button-editor category."""

    key: str
    title: str


@dataclass(frozen=True, slots=True)
class EditableButtonDefinition:
    """Editable button metadata for runtime-configured labels/icons/styles."""

    key: str
    category_key: str
    title: str
    setting_key: str
    default_text: str
    default_style_name: str
    default_icon_custom_emoji_id: str | None
    callback_data: str | None = None
    url: str | None = None
    requires_visible_bookings: bool = False

    @property
    def editor_id(self) -> str:
        return f"{self.category_key}.{self.key}"


@dataclass(frozen=True, slots=True)
class ClientMenuButtonConfig:
    """Stored, editable button config."""

    text: str
    style_name: str = BUTTON_STYLE_DEFAULT
    icon_custom_emoji_id: str | None = None
    url: str | None = None

    def normalized(self) -> ClientMenuButtonConfig:
        style_name = (
            self.style_name if self.style_name in BUTTON_STYLE_VALUES else BUTTON_STYLE_DEFAULT
        )
        icon = self.icon_custom_emoji_id or None
        url = (self.url or "").strip() or None
        return ClientMenuButtonConfig(
            text=self.text.strip() or self.text,
            style_name=style_name,
            icon_custom_emoji_id=icon,
            url=url,
        )


BUTTON_EDITOR_CATEGORIES: tuple[ButtonEditorCategory, ...] = (
    ButtonEditorCategory(key="client_main_menu", title="🙋‍♀️ Клиент · Главное меню"),
    ButtonEditorCategory(key="common", title="🧩 Общие"),
    ButtonEditorCategory(key="client_my_bookings", title="📖 Клиент · Мои записи"),
    ButtonEditorCategory(key="client_repeated", title="🔁 Клиент · Повторяющиеся"),
)

EDITABLE_BUTTON_DEFINITIONS: tuple[EditableButtonDefinition, ...] = (
    EditableButtonDefinition(
        key="book",
        category_key="client_main_menu",
        title="📅 Записаться",
        setting_key="button_config.client_main_menu.book",
        default_text="📅 Записаться",
        default_style_name=BUTTON_STYLE_SUCCESS,
        default_icon_custom_emoji_id=None,
        callback_data="client_menu:book",
    ),
    EditableButtonDefinition(
        key="my_bookings",
        category_key="client_main_menu",
        title="🙋‍♀️ Мои записи",
        setting_key="button_config.client_main_menu.my_bookings",
        default_text="🙋‍♀️ Мои записи",
        default_style_name=BUTTON_STYLE_PRIMARY,
        default_icon_custom_emoji_id=None,
        callback_data="client_menu:my_bookings",
        requires_visible_bookings=True,
    ),
    EditableButtonDefinition(
        key="browse",
        category_key="client_main_menu",
        title="🗓 Свободные окошки",
        setting_key="button_config.client_main_menu.browse",
        default_text="🗓 Свободные окошки",
        default_style_name=BUTTON_STYLE_PRIMARY,
        default_icon_custom_emoji_id=None,
        callback_data="client_menu:browse",
    ),
    EditableButtonDefinition(
        key="services",
        category_key="client_main_menu",
        title="💅 Услуги и цены",
        setting_key="button_config.client_main_menu.services",
        default_text="💅 Услуги и цены",
        default_style_name=BUTTON_STYLE_PRIMARY,
        default_icon_custom_emoji_id=None,
        callback_data="client_menu:services",
    ),
    EditableButtonDefinition(
        key="portfolio",
        category_key="client_main_menu",
        title="🌸 О Ангеле и работы",
        setting_key="button_config.client_main_menu.portfolio",
        default_text="🌸 О Ангеле и работы",
        default_style_name=BUTTON_STYLE_DEFAULT,
        default_icon_custom_emoji_id=PORTFOLIO_CUSTOM_EMOJI_ID,
        url=DEFAULT_PORTFOLIO_CHANNEL_URL,
    ),
    EditableButtonDefinition(
        key="address",
        category_key="client_main_menu",
        title="📍 Адрес и как добраться",
        setting_key="button_config.client_main_menu.address",
        default_text="📍 Адрес и как добраться",
        default_style_name=BUTTON_STYLE_DEFAULT,
        default_icon_custom_emoji_id=None,
        callback_data="client_menu:address",
    ),
    EditableButtonDefinition(
        key="contact",
        category_key="client_main_menu",
        title="✉️ Написать Ангеле напрямую",
        setting_key="button_config.client_main_menu.contact",
        default_text="✉️ Написать Ангеле напрямую",
        default_style_name=BUTTON_STYLE_DEFAULT,
        default_icon_custom_emoji_id=None,
        url=ANGELA_CHAT_URL,
    ),
    EditableButtonDefinition(
        key="back",
        category_key="common",
        title="⬅️ Назад",
        setting_key="button_config.common.back",
        default_text="⬅️ Назад",
        default_style_name=BUTTON_STYLE_DANGER,
        default_icon_custom_emoji_id=None,
    ),
    EditableButtonDefinition(
        key="done",
        category_key="common",
        title="✅ Готово",
        setting_key="button_config.common.done",
        default_text="✅ Готово",
        default_style_name=BUTTON_STYLE_SUCCESS,
        default_icon_custom_emoji_id=None,
    ),
    EditableButtonDefinition(
        key="cancel_back",
        category_key="common",
        title="⬅️ Отмена",
        setting_key="button_config.common.cancel_back",
        default_text="⬅️ Отмена",
        default_style_name=BUTTON_STYLE_DANGER,
        default_icon_custom_emoji_id=None,
    ),
    EditableButtonDefinition(
        key="cancel_action",
        category_key="common",
        title="❌ Отменить",
        setting_key="button_config.common.cancel_action",
        default_text="❌ Отменить",
        default_style_name=BUTTON_STYLE_DANGER,
        default_icon_custom_emoji_id=None,
    ),
    EditableButtonDefinition(
        key="reschedule",
        category_key="client_my_bookings",
        title="✏️ Перенести",
        setting_key="button_config.client_my_bookings.reschedule",
        default_text="✏️ Перенести",
        default_style_name=BUTTON_STYLE_PRIMARY,
        default_icon_custom_emoji_id=None,
    ),
    EditableButtonDefinition(
        key="late",
        category_key="client_my_bookings",
        title="⏰ Опаздываю",
        setting_key="button_config.client_my_bookings.late",
        default_text="⏰ Опаздываю",
        default_style_name=BUTTON_STYLE_PRIMARY,
        default_icon_custom_emoji_id=None,
    ),
    EditableButtonDefinition(
        key="repair",
        category_key="client_my_bookings",
        title="🛠 Ремонт / гарантия",
        setting_key="button_config.client_my_bookings.repair",
        default_text="🛠 Ремонт / гарантия",
        default_style_name=BUTTON_STYLE_PRIMARY,
        default_icon_custom_emoji_id=None,
    ),
    EditableButtonDefinition(
        key="payment_cash",
        category_key="client_repeated",
        title="💵 Наличными",
        setting_key="button_config.client_repeated.payment_cash",
        default_text="💵 Наличными (предпочтительно)",
        default_style_name=BUTTON_STYLE_SUCCESS,
        default_icon_custom_emoji_id=None,
    ),
    EditableButtonDefinition(
        key="payment_transfer",
        category_key="client_repeated",
        title="💳 Переводом",
        setting_key="button_config.client_repeated.payment_transfer",
        default_text="💳 Переводом",
        default_style_name=BUTTON_STYLE_PRIMARY,
        default_icon_custom_emoji_id=None,
    ),
    EditableButtonDefinition(
        key="other_day",
        category_key="client_repeated",
        title="❓ Нужна другая дата",
        setting_key="button_config.client_repeated.other_day",
        default_text="❓ Нужна другая дата",
        default_style_name=BUTTON_STYLE_DEFAULT,
        default_icon_custom_emoji_id=None,
    ),
    EditableButtonDefinition(
        key="other_time",
        category_key="client_repeated",
        title="⏰ Хочу другое время",
        setting_key="button_config.client_repeated.other_time",
        default_text="⏰ Хочу другое время в этот день",
        default_style_name=BUTTON_STYLE_DEFAULT,
        default_icon_custom_emoji_id=None,
    ),
    EditableButtonDefinition(
        key="open_map",
        category_key="client_repeated",
        title="🗺 Открыть в Яндекс Картах",
        setting_key="button_config.client_repeated.open_map",
        default_text="🗺 Открыть в Яндекс Картах",
        default_style_name=BUTTON_STYLE_PRIMARY,
        default_icon_custom_emoji_id=None,
        url=DEFAULT_ADDRESS_MAP_URL,
    ),
)


def list_button_editor_categories() -> tuple[ButtonEditorCategory, ...]:
    """Return editor categories in the admin display order."""
    return BUTTON_EDITOR_CATEGORIES


def get_button_editor_category(key: str) -> ButtonEditorCategory:
    """Return one button-editor category by key."""
    for category in BUTTON_EDITOR_CATEGORIES:
        if category.key == key:
            return category
    raise KeyError(key)


def list_editable_button_definitions() -> tuple[EditableButtonDefinition, ...]:
    """Return all editable button definitions."""
    return EDITABLE_BUTTON_DEFINITIONS


def list_editable_button_definitions_for_category(
    category_key: str,
) -> tuple[EditableButtonDefinition, ...]:
    """Return button definitions that belong to one category."""
    return tuple(
        definition
        for definition in EDITABLE_BUTTON_DEFINITIONS
        if definition.category_key == category_key
    )


async def load_master_contact_url(
    repository: SettingRepository,
) -> str:
    """Return the current Telegram deep-link used for the «write to master» CTA."""
    username = await repository.get_value_or_default(
        MASTER_TELEGRAM_USERNAME_SETTING_KEY,
        DEFAULT_MASTER_TELEGRAM_USERNAME,
    )
    return build_angela_chat_url(username)


def get_editable_button_definition(editor_id: str) -> EditableButtonDefinition:
    """Return one editable button definition by its unique editor id."""
    for definition in EDITABLE_BUTTON_DEFINITIONS:
        if definition.editor_id == editor_id:
            return definition
    raise KeyError(editor_id)


def get_client_main_menu_button_definition(key: str) -> EditableButtonDefinition:
    """Return one client-main-menu definition by its local key."""
    for definition in list_editable_button_definitions_for_category("client_main_menu"):
        if definition.key == key:
            return definition
    raise KeyError(key)


def default_button_config(definition: EditableButtonDefinition) -> ClientMenuButtonConfig:
    """Return the default config for a definition."""
    return ClientMenuButtonConfig(
        text=definition.default_text,
        style_name=definition.default_style_name,
        icon_custom_emoji_id=definition.default_icon_custom_emoji_id,
    )


def resolve_button_style(style_name: str) -> ButtonStyle | None:
    """Convert a stored style value into Telegram's button style enum."""
    if style_name == BUTTON_STYLE_PRIMARY:
        return ButtonStyle.PRIMARY
    if style_name == BUTTON_STYLE_SUCCESS:
        return ButtonStyle.SUCCESS
    if style_name == BUTTON_STYLE_DANGER:
        return ButtonStyle.DANGER
    return None


def _decode_button_config(
    raw_value: str | None,
    *,
    definition: EditableButtonDefinition,
) -> ClientMenuButtonConfig:
    default = default_button_config(definition)
    if not raw_value:
        return default
    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError:
        return default
    if not isinstance(payload, dict):
        return default
    text = str(payload.get("text") or default.text)
    style_name = str(payload.get("style_name") or default.style_name)
    icon = payload.get("icon_custom_emoji_id")
    if icon is not None:
        icon = str(icon).strip() or None
    url = payload.get("url")
    if url is not None:
        url = str(url).strip() or None
    if definition.key == "open_map" and url in {
        LEGACY_DEFAULT_ADDRESS_MAP_URL,
        PREVIOUS_DEFAULT_ADDRESS_MAP_URL,
    }:
        url = DEFAULT_ADDRESS_MAP_URL
    return ClientMenuButtonConfig(
        text=text,
        style_name=style_name,
        icon_custom_emoji_id=icon,
        url=url,
    ).normalized()


def encode_button_config(config: ClientMenuButtonConfig) -> str:
    """Serialize a button config for the settings table."""
    normalized = config.normalized()
    return json.dumps(
        {
            "text": normalized.text,
            "style_name": normalized.style_name,
            "icon_custom_emoji_id": normalized.icon_custom_emoji_id,
            "url": normalized.url,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def load_button_config(
    repository: SettingRepository,
    *,
    editor_id: str,
) -> ClientMenuButtonConfig:
    """Load one editable button config by editor id."""
    definition = get_editable_button_definition(editor_id)
    return _decode_button_config(
        await repository.get_value(definition.setting_key),
        definition=definition,
    )


async def load_button_configs_for_category(
    repository: SettingRepository,
    *,
    category_key: str,
) -> dict[str, ClientMenuButtonConfig]:
    """Load all button configs for one category keyed by local button key."""
    configs: dict[str, ClientMenuButtonConfig] = {}
    for definition in list_editable_button_definitions_for_category(category_key):
        configs[definition.key] = _decode_button_config(
            await repository.get_value(definition.setting_key),
            definition=definition,
        )
    return configs


async def load_all_button_configs(
    repository: SettingRepository,
) -> dict[str, ClientMenuButtonConfig]:
    """Load every editable button config keyed by unique editor id."""
    configs: dict[str, ClientMenuButtonConfig] = {}
    for definition in EDITABLE_BUTTON_DEFINITIONS:
        configs[definition.editor_id] = _decode_button_config(
            await repository.get_value(definition.setting_key),
            definition=definition,
        )
    return configs


async def load_client_main_menu_button_configs(
    repository: SettingRepository,
) -> dict[str, ClientMenuButtonConfig]:
    """Load main-menu button configs keyed by local main-menu key."""
    return await load_button_configs_for_category(
        repository,
        category_key="client_main_menu",
    )


async def load_client_main_menu_button_config(
    repository: SettingRepository,
    *,
    key: str,
) -> ClientMenuButtonConfig:
    """Load a single client-main-menu button config."""
    definition = get_client_main_menu_button_definition(key)
    return _decode_button_config(
        await repository.get_value(definition.setting_key),
        definition=definition,
    )


async def save_button_config(
    repository: SettingRepository,
    *,
    editor_id: str,
    config: ClientMenuButtonConfig,
) -> ClientMenuButtonConfig:
    """Persist one editable button config by editor id."""
    definition = get_editable_button_definition(editor_id)
    normalized = config.normalized()
    await repository.upsert(
        key=definition.setting_key,
        value=encode_button_config(normalized),
    )
    return normalized


async def save_client_main_menu_button_config(
    repository: SettingRepository,
    *,
    key: str,
    config: ClientMenuButtonConfig,
) -> ClientMenuButtonConfig:
    """Persist a single client-main-menu button config."""
    return await save_button_config(
        repository,
        editor_id=f"client_main_menu.{key}",
        config=config,
    )
