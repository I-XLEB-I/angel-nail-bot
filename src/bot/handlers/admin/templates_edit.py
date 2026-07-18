from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import (
    clear_state_preserving_admin_panel,
    remember_admin_panel,
    send_admin_aux_photo,
    send_admin_panel,
    send_admin_photo_panel,
)
from src.bot.handlers.admin.approvals import show_pending_approvals
from src.bot.handlers.admin.broadcast import open_broadcast
from src.bot.handlers.admin.clients import open_clients_section
from src.bot.handlers.admin.menu import show_admin_menu
from src.bot.handlers.admin.schedule import show_schedule_menu
from src.bot.handlers.admin.services_crud import show_services_list
from src.bot.handlers.admin.settings_edit import show_settings
from src.bot.handlers.admin.stats import show_stats
from src.bot.keyboards.admin import (
    build_admin_template_categories_keyboard,
    build_admin_template_category_keyboard,
    build_admin_template_detail_keyboard,
    build_admin_template_edit_cancel_keyboard,
    build_admin_template_group_keyboard,
    build_admin_template_media_cancel_keyboard,
    build_admin_template_warning_keyboard,
)
from src.bot.states import AdminTemplateEdit
from src.bot.ui_utils import replace_inline_message_text, upsert_inline_panel
from src.config import Settings
from src.db.models import User
from src.db.repositories.templates import TemplateRepository
from src.services.admin_defaults import (
    TemplateDefinition,
    get_template_definition,
    list_template_categories,
    list_template_definitions,
    required_template_defaults,
)
from src.services.template_media import (
    has_bundled_template_media,
    has_template_media,
    remove_template_media,
    restore_bundled_template_media,
    save_template_media,
    template_media_path,
    template_media_source,
)

router = Router(name="admin_templates_edit")
logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_MIME_TYPES = frozenset(
    {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}
)
SUPPORTED_IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
)
PLACEHOLDER_PATTERN = re.compile(r"\{([^{}\n\r]+)\}")
REQUESTS_MENU_PATTERN = re.compile(r"^📥 Запросы \(\d+\)$")
MAX_TEMPLATE_IMAGE_BYTES = 5 * 1024 * 1024
DETAIL_CAPTION_SAFE_LIMIT = 950
TEMPLATE_PENDING_CONTENT_KEY = "admin_template_pending_content"
HIDDEN_TEMPLATE_KEYS = frozenset({"rules", "navigation", "repair_declined"})

TEMPLATE_CATEGORY_SUMMARIES: dict[str, str] = {
    "clients": (
        "Сообщения клиентке на разных этапах: запись, напоминания, "
        "aftercare и исключения 🌸"
    ),
    "address": "Публичный адрес до записи и полный адрес после подтверждения.",
    "schedule": "Короткие подписи и витринные тексты для расписания.",
    "other": "Главная, портфолио, отпуск и прочие служебные экраны.",
}

@dataclass(frozen=True, slots=True)
class TemplateGroup:
    """One second-level template group inside an admin category."""

    key: str
    title: str
    summary: str
    template_keys: tuple[str, ...]


TEMPLATE_GROUPS_BY_CATEGORY: dict[str, tuple[TemplateGroup, ...]] = {
    "clients": (
        TemplateGroup(
            key="booking",
            title="🌿 Запись",
            summary="Подтверждение записи и мягкие отказы по записи.",
            template_keys=("booking_confirm", "decline_repeat_booking_reason"),
        ),
        TemplateGroup(
            key="price",
            title="💰 Прайс",
            summary="Текст и картинка клиентского раздела «Услуги и цены».",
            template_keys=("price",),
        ),
        TemplateGroup(
            key="reminders",
            title="🔔 Напоминания",
            summary="Напоминания за сутки и за 2 часа до визита.",
            template_keys=("reminder_24h", "reminder_2h"),
        ),
        TemplateGroup(
            key="postvisit",
            title="🫶 После визита",
            summary="После визита, ответы на оценки и мягкий follow-up.",
            template_keys=(
                "postvisit",
                "postvisit_rating_5",
                "postvisit_rating_mid",
                "postvisit_rating_low",
            ),
        ),
        TemplateGroup(
            key="repeat",
            title="🔁 Повторный визит",
            summary="Приглашение вернуться и возврат давних клиенток.",
            template_keys=("repeat_prompt", "winback_lapsed"),
        ),
        TemplateGroup(
            key="late",
            title="⏰ Опоздание",
            summary="Экран опоздания и тексты после предупреждения.",
            template_keys=(
                "late_notice_intro",
                "late_notice_client_sent",
                "late_notice_client_risky",
            ),
        ),
        TemplateGroup(
            key="repair",
            title="🛠 Ремонт и гарантия",
            summary="Вся логика ремонта и гарантийных кейсов в одном месте.",
            template_keys=(
                "repair_intro",
                "repair_request_received",
                "repair_warranty_offer",
                "repair_not_warranty",
                "repair_declined",
            ),
        ),
        TemplateGroup(
            key="exceptions",
            title="🌤 Нештатные сценарии",
            summary="Массовые отмены и редкие исключения.",
            template_keys=("force_majeure_notice",),
        ),
    ),
    "address": (
        TemplateGroup(
            key="navigation",
            title="📍 Адрес и навигация",
            summary=(
                "Картинка меняется в пункте публичного адреса. Полный адрес "
                "подставляется текстом в подтверждения и напоминания."
            ),
            template_keys=("navigation_public", "navigation", "address_post_confirm"),
        ),
    ),
    "schedule": (
        TemplateGroup(
            key="showcase",
            title="🗓 Витрина расписания",
            summary="Подпись под картинкой со свободными окошками.",
            template_keys=("schedule_caption_text",),
        ),
    ),
    "other": (
        TemplateGroup(
            key="showcase",
            title="🌷 Главная и витрина",
            summary="Главный экран, портфолио и блок про Ангелу.",
            template_keys=("greeting_header", "portfolio_intro", "about_master"),
        ),
        TemplateGroup(
            key="rules_vacation",
            title="🌴 Отпуск",
            summary="Текст, который клиентки видят во время отпускного режима.",
            template_keys=("rules", "vacation_notice"),
        ),
        TemplateGroup(
            key="service",
            title="⚙️ Служебное",
            summary="Внутренний текст админ-меню.",
            template_keys=("admin_menu_text",),
        ),
    ),
}


async def ensure_required_templates(db_session: AsyncSession) -> None:
    """Seed required editable templates when they are missing."""
    repository = TemplateRepository(db_session)
    for key, default_content in required_template_defaults().items():
        if await repository.get_by_key(key) is None:
            await repository.upsert(key=key, content=default_content)
    await db_session.commit()


def build_template_variables_block(template_key: str) -> str:
    """Render a variable-help block for one template."""
    definition = get_template_definition(template_key)
    if definition is None or not definition.variables:
        return "🔤 Переменные\nнет"
    variables = "\n".join(f"• {{{item}}}" for item in definition.variables)
    return f"🔤 Переменные\n{variables}"


def build_template_image_block(template_key: str) -> str:
    """Render the image-attachment state block for one template."""
    definition = get_template_definition(template_key)
    if definition is None or not definition.supports_media:
        return "🖼 Картинка: не используется"
    source = template_media_source(template_key)
    if source == "uploaded":
        return "🖼 Картинка: своя, загружена через админку"
    if source == "bundled":
        return "🖼 Картинка: стандартная, уже показывается клиенткам"
    if has_bundled_template_media(template_key):
        return "🖼 Картинка: отключена · стандартную можно вернуть"
    return "🖼 Картинка: можно добавить"


def list_template_groups(category_key: str) -> tuple[TemplateGroup, ...]:
    """Return second-level groups for one template category."""
    return TEMPLATE_GROUPS_BY_CATEGORY.get(category_key, ())


def _is_template_visible(definition: TemplateDefinition) -> bool:
    """Return whether a template should be visible in the admin picker."""
    return definition.key not in HIDDEN_TEMPLATE_KEYS


def _list_visible_template_groups(category_key: str) -> tuple[TemplateGroup, ...]:
    """Return only those groups that still contain visible templates."""
    return tuple(
        group
        for group in list_template_groups(category_key)
        if any(
            key not in HIDDEN_TEMPLATE_KEYS
            for key in group.template_keys
        )
    )


def get_template_group(category_key: str, group_key: str) -> TemplateGroup | None:
    """Return one group by category + key."""
    for group in list_template_groups(category_key):
        if group.key == group_key:
            return group
    return None


def resolve_template_group_key(category_key: str, template_key: str) -> str | None:
    """Return the subgroup key that contains a template."""
    for group in list_template_groups(category_key):
        if template_key in group.template_keys:
            return group.key
    return None


def get_single_group_for_category(category_key: str) -> TemplateGroup | None:
    """Return the only visible subgroup when a category has exactly one."""
    groups = _list_visible_template_groups(category_key)
    if len(groups) != 1:
        return None
    return groups[0]


def list_template_definitions_for_group(
    *,
    category_key: str,
    group_key: str,
) -> list[TemplateDefinition]:
    """Return template definitions belonging to one visible subgroup."""
    group = get_template_group(category_key, group_key)
    if group is None:
        return []
    definitions_by_key = {
        definition.key: definition
        for definition in list_template_definitions(category_key=category_key)
    }
    return [
        definitions_by_key[key]
        for key in group.template_keys
        if key in definitions_by_key and _is_template_visible(definitions_by_key[key])
    ]


def _find_template_placeholder_tokens(content: str) -> list[str]:
    """Extract placeholder-like tokens from one template body."""
    return [match.strip() for match in PLACEHOLDER_PATTERN.findall(content)]


def _collect_template_placeholder_warnings(
    template_key: str,
    content: str,
) -> tuple[list[str], list[str]]:
    """Return missing and unknown placeholders for one template draft."""
    definition = get_template_definition(template_key)
    if definition is None:
        return [], []
    found_tokens = {
        token
        for token in _find_template_placeholder_tokens(content)
        if token
    }
    required_tokens = set(
        definition.variables
        if definition.required_variables is None
        else definition.required_variables
    )
    allowed_tokens = set(definition.variables)
    missing = sorted(required_tokens - found_tokens)
    unknown = sorted(found_tokens - allowed_tokens)
    return missing, unknown


def _build_placeholder_warning_text(
    template_key: str,
    *,
    missing: list[str],
    unknown: list[str],
) -> str:
    """Render the warning shown before saving a risky template draft."""
    definition = get_template_definition(template_key)
    title = definition.title if definition is not None else "Шаблон"
    lines = [
        f"⚠️ {title}",
        "",
        "Я нашла потенциальную проблему в тексте шаблона.",
    ]
    if missing:
        lines.extend(
            [
                "",
                "Не вижу обязательные переменные:",
                ", ".join(f"{{{item}}}" for item in missing),
            ]
        )
    if unknown:
        lines.extend(
            [
                "",
                "Неизвестные переменные останутся клиентке буквальным текстом:",
                ", ".join(f"{{{item}}}" for item in unknown),
            ]
        )
    lines.extend(
        [
            "",
            "Можно сохранить всё равно или вернуться и поправить текст.",
        ]
    )
    return "\n".join(lines)


def _format_template_preview(content: str, *, limit: int = 500) -> str:
    """Render a compact source preview for edit prompts."""
    preview = content.strip() or "— пусто —"
    if len(preview) <= limit:
        return preview
    return preview[: limit - 1].rstrip() + "…"


def _should_split_template_detail_media(text: str) -> bool:
    """Return whether the detail text is too long for a photo caption."""
    return len(text) > DETAIL_CAPTION_SAFE_LIMIT


def get_single_template_for_group(
    *,
    category_key: str,
    group_key: str,
) -> TemplateDefinition | None:
    """Return the only template inside a group when no picker screen is needed."""
    definitions = list_template_definitions_for_group(
        category_key=category_key,
        group_key=group_key,
    )
    if len(definitions) != 1:
        return None
    return definitions[0]


def resolve_template_group_back_callback(category_key: str) -> str:
    """Return the closest meaningful back target for a group screen."""
    if get_single_group_for_category(category_key) is not None:
        return "admin_templates:home"
    return f"admin_templates:category:{category_key}"


def resolve_template_detail_back_callback(template_key: str) -> str:
    """Return the closest meaningful back target for one template detail screen."""
    definition = get_template_definition(template_key)
    if definition is None:
        return "admin_templates:home"
    group_key = resolve_template_group_key(definition.category_key, definition.key)
    if group_key is None:
        return "admin_templates:home"
    if len(
        list_template_definitions_for_group(
            category_key=definition.category_key,
            group_key=group_key,
        )
    ) > 1:
        return f"admin_templates:group:{definition.category_key}:{group_key}"
    return resolve_template_group_back_callback(definition.category_key)


def build_template_meta_line(
    *,
    current_content: str,
    default_content: str,
    variable_count: int,
    supports_media: bool,
    media_source: str | None,
    has_bundled_media: bool,
) -> str:
    """Build one compact metadata line for category and detail screens."""
    status_label = (
        "свой текст"
        if current_content.strip() != default_content.strip()
        else "по умолчанию"
    )
    variable_label = (
        f"{variable_count} перем."
        if variable_count
        else "без переменных"
    )
    if not supports_media:
        media_label = "только текст"
    elif media_source == "uploaded":
        media_label = "своя картинка"
    elif media_source == "bundled":
        media_label = "стандартная картинка"
    elif has_bundled_media:
        media_label = "картинка отключена"
    else:
        media_label = "без картинки"
    return f"{status_label} · {variable_label} · {media_label}"


def build_templates_home_text() -> str:
    """Render the structured templates home screen."""
    lines = [
        "📝 ШАБЛОНЫ",
        "",
        "Здесь собраны основные тексты и картинки, которые можно менять через бота.",
        "Сначала выбери раздел 👇",
        "",
    ]
    for category in list_template_categories():
        summary = TEMPLATE_CATEGORY_SUMMARIES.get(category.key, "")
        lines.append(f"{category.title}")
        if summary:
            lines.append(summary)
        lines.append("")
    return "\n".join(lines).rstrip()


def build_template_category_text(category_key: str) -> str:
    """Render a category screen that lists subgroup blocks instead of raw templates."""
    category = next((item for item in list_template_categories() if item.key == category_key), None)
    if category is None:
        return texts.ADMIN_TEMPLATES_HOME_TEXT

    lines = [f"📝 ШАБЛОНЫ · {category.title}", ""]
    summary = TEMPLATE_CATEGORY_SUMMARIES.get(category.key)
    if summary:
        lines.extend([summary, ""])
    lines.append("Выбери блок ниже 👇")
    lines.append("")
    for group in _list_visible_template_groups(category_key):
        lines.append(group.title)
        lines.append(group.summary)
        lines.append("")
    return "\n".join(lines).rstrip()


async def build_template_group_text(
    db_session: AsyncSession,
    *,
    category_key: str,
    group_key: str,
) -> str | None:
    """Render one subgroup screen with its concrete templates."""
    category = next((item for item in list_template_categories() if item.key == category_key), None)
    group = get_template_group(category_key, group_key)
    if category is None or group is None:
        return None

    repository = TemplateRepository(db_session)
    lines = [
        f"📝 ШАБЛОНЫ · {category.title}",
        "",
        group.title,
        group.summary,
        "",
    ]
    definitions = list_template_definitions_for_group(
        category_key=category_key,
        group_key=group_key,
    )
    for index, definition in enumerate(definitions, start=1):
        current_content = await repository.get_content_or_default(
            definition.key,
            definition.default_content,
        )
        meta_line = build_template_meta_line(
            current_content=current_content,
            default_content=definition.default_content,
            variable_count=len(definition.variables),
            supports_media=definition.supports_media,
            media_source=template_media_source(definition.key),
            has_bundled_media=has_bundled_template_media(definition.key),
        )
        lines.extend(
            [
                f"{index}. {definition.title}",
                f"   ┣ {definition.description}",
                f"   ┗ {meta_line}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


async def build_template_detail_text(
    db_session: AsyncSession,
    *,
    template_key: str,
) -> tuple[str, object] | None:
    """Build one template detail text with the current media state."""
    definition = get_template_definition(template_key)
    if definition is None:
        return None

    repository = TemplateRepository(db_session)
    content = await repository.get_content_or_default(
        definition.key,
        definition.default_content,
    )
    meta_line = build_template_meta_line(
        current_content=content,
        default_content=definition.default_content,
        variable_count=len(definition.variables),
        supports_media=definition.supports_media,
        media_source=template_media_source(definition.key),
        has_bundled_media=has_bundled_template_media(definition.key),
    )
    text = texts.ADMIN_TEMPLATE_DETAIL_TEXT.format(
        title=definition.title,
        description=definition.description,
        meta_line=meta_line,
        content=content or "— пусто —",
        variables_block=build_template_variables_block(definition.key),
        image_block=build_template_image_block(definition.key),
    )
    reply_markup = build_admin_template_detail_keyboard(
        definition.key,
        resolve_template_detail_back_callback(definition.key),
        supports_media=definition.supports_media,
        has_media=has_template_media(definition.key),
        has_bundled_media=has_bundled_template_media(definition.key),
        uses_bundled_media=template_media_source(definition.key) == "bundled",
        has_custom_text=content.strip() != definition.default_content.strip(),
    )
    return text, reply_markup


def build_template_detail_media(template_key: str) -> tuple[bytes, str] | None:
    """Return the attached image bytes for a template detail card."""
    if not has_template_media(template_key):
        return None
    path = template_media_path(template_key)
    return path.read_bytes(), path.name


def _document_is_supported_image(document) -> bool:
    """Return whether the incoming Telegram document looks like an image."""
    mime_type = (getattr(document, "mime_type", None) or "").lower()
    if mime_type in SUPPORTED_IMAGE_MIME_TYPES or mime_type.startswith("image/"):
        return True
    filename = (getattr(document, "file_name", None) or "").lower()
    return Path(filename).suffix in SUPPORTED_IMAGE_EXTENSIONS


async def refresh_template_detail_panel(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    template_key: str,
    notice_text: str | None = None,
    panel_chat_id: int | None = None,
    panel_message_id: int | None = None,
) -> bool:
    """Re-render the current template detail card, preserving photo mode."""
    detail = await build_template_detail_text(db_session, template_key=template_key)
    if detail is None:
        return False

    text, reply_markup = detail
    if notice_text:
        text = f"{notice_text}\n\n{text}"
    media = build_template_detail_media(template_key)

    if panel_chat_id is not None and panel_message_id is not None:
        if media is not None and not _should_split_template_detail_media(text):
            photo_bytes, filename = media
            panel = await upsert_inline_panel(
                message.bot,
                chat_id=panel_chat_id,
                message_id=panel_message_id,
                text=text,
                reply_markup=reply_markup,
                photo_bytes=photo_bytes,
                filename=filename,
                caption=text,
            )
        else:
            panel = await upsert_inline_panel(
                message.bot,
                chat_id=panel_chat_id,
                message_id=panel_message_id,
                text=text,
                reply_markup=reply_markup,
            )
        await remember_admin_panel(state, panel)
        if media is not None and _should_split_template_detail_media(text):
            photo_bytes, filename = media
            await send_admin_aux_photo(
                message,
                state,
                photo_bytes=photo_bytes,
                filename=filename,
                caption="🖼 Превью картинки шаблона",
            )
        return True

    await show_template_detail(
        message,
        db_session=db_session,
        template_key=template_key,
        edit=False,
        state=state,
    )
    return True


async def build_template_edit_prompt_text(
    db_session: AsyncSession,
    template_key: str,
    *,
    draft_content: str | None = None,
) -> str:
    """Render a contextual prompt for editing one template."""
    definition = get_template_definition(template_key)
    title = definition.title if definition is not None else "Шаблон"
    repository = TemplateRepository(db_session)
    current_content = draft_content
    if current_content is None:
        current_content = await repository.get_content_or_default(
            template_key,
            definition.default_content if definition is not None else "",
        )
    preview = _format_template_preview(current_content)
    preview_label = "Черновик сейчас" if draft_content is not None else "Текущий текст"
    preview_note = (
        "\n\nПолный текст остаётся в карточке шаблона выше."
        if preview != (current_content.strip() or "— пусто —")
        else ""
    )
    variables_block = build_template_variables_block(template_key)
    return (
        f"✏️ {title}\n\n"
        "Пришли новый текст одним сообщением 🌸\n\n"
        f"{preview_label}\n"
        "━━━━━━━━━━━━━━\n"
        f"{preview}\n"
        f"━━━━━━━━━━━━━━{preview_note}\n\n"
        f"{variables_block}"
    )


async def _persist_template_content(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    template_key: str,
    category_key: str,
    stored_group_key: str,
    content: str,
    panel_chat_id: int | None,
    panel_message_id: int | None,
) -> None:
    """Commit one template draft and reopen the detail panel."""
    repository = TemplateRepository(db_session)
    await repository.upsert(key=template_key, content=content)
    await db_session.commit()
    await state.clear()
    if await refresh_template_detail_panel(
        message,
        state,
        db_session=db_session,
        template_key=template_key,
        notice_text=texts.ADMIN_TEMPLATE_SAVED_TEXT,
        panel_chat_id=panel_chat_id,
        panel_message_id=panel_message_id,
    ):
        return
    group_key = stored_group_key or resolve_template_group_key(category_key, template_key)
    if group_key:
        await show_template_group(
            message,
            db_session=db_session,
            category_key=category_key,
            group_key=group_key,
            edit=False,
            state=state,
        )
        return
    await show_template_category(
        message,
        db_session=db_session,
        category_key=category_key,
        edit=False,
        state=state,
    )


def build_template_image_prompt_text(template_key: str) -> str:
    """Render a contextual prompt for updating one template image."""
    definition = get_template_definition(template_key)
    title = definition.title if definition is not None else "Шаблон"
    return (
        f"🖼 {title}\n\n"
        "Пришли новую картинку для этого шаблона.\n"
        "Подойдёт фото или файл-изображение 🌸"
    )


async def show_templates_home(
    message: Message,
    *,
    db_session: AsyncSession,
    edit: bool,
    state: FSMContext | None = None,
) -> None:
    """Show the template-category picker."""
    await ensure_required_templates(db_session)
    categories = list(list_template_categories())
    counts_by_key = {
        category.key: len(
            [
                definition
                for definition in list_template_definitions(category_key=category.key)
                if _is_template_visible(definition)
            ]
        )
        for category in categories
    }
    text = build_templates_home_text()
    reply_markup = build_admin_template_categories_keyboard(
        categories,
        counts_by_key=counts_by_key,
    )
    if state is not None:
        await send_admin_panel(message, state, text=text, reply_markup=reply_markup)
        return
    if edit:
        await replace_inline_message_text(message, text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


async def show_template_category(
    message: Message,
    *,
    db_session: AsyncSession,
    category_key: str,
    edit: bool,
    state: FSMContext | None = None,
) -> None:
    """Show subgroup blocks inside one category."""
    await ensure_required_templates(db_session)
    category = next((item for item in list_template_categories() if item.key == category_key), None)
    if category is None:
        await show_templates_home(message, db_session=db_session, edit=edit)
        return

    groups = _list_visible_template_groups(category_key)
    if not groups:
        await show_templates_home(message, db_session=db_session, edit=edit)
        return

    single_group = get_single_group_for_category(category_key)
    if single_group is not None:
        single_template = get_single_template_for_group(
            category_key=category_key,
            group_key=single_group.key,
        )
        if single_template is not None:
            await show_template_detail(
                message,
                db_session=db_session,
                template_key=single_template.key,
                edit=edit,
                state=state,
            )
            return
        await show_template_group(
            message,
            db_session=db_session,
            category_key=category_key,
            group_key=single_group.key,
            edit=edit,
            state=state,
        )
        return

    text = build_template_category_text(category_key)
    reply_markup = build_admin_template_category_keyboard(
        category_key,
        [(group.key, group.title) for group in groups],
    )
    if state is not None:
        await send_admin_panel(message, state, text=text, reply_markup=reply_markup)
        return
    if edit:
        await replace_inline_message_text(message, text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


async def show_template_group(
    message: Message,
    *,
    db_session: AsyncSession,
    category_key: str,
    group_key: str,
    edit: bool,
    state: FSMContext | None = None,
) -> None:
    """Show concrete templates inside one subgroup."""
    await ensure_required_templates(db_session)
    group = get_template_group(category_key, group_key)
    if group is None:
        await show_template_category(
            message,
            db_session=db_session,
            category_key=category_key,
            edit=edit,
            state=state,
        )
        return

    definitions = list_template_definitions_for_group(
        category_key=category_key,
        group_key=group_key,
    )
    if len(definitions) == 1:
        await show_template_detail(
            message,
            db_session=db_session,
            template_key=definitions[0].key,
            edit=edit,
            state=state,
        )
        return

    text = await build_template_group_text(
        db_session,
        category_key=category_key,
        group_key=group_key,
    )
    reply_markup = build_admin_template_group_keyboard(
        category_key,
        group_key,
        definitions,
        back_callback=resolve_template_group_back_callback(category_key),
    )
    if state is not None:
        await send_admin_panel(message, state, text=text or "", reply_markup=reply_markup)
        return
    if edit:
        await replace_inline_message_text(message, text or "", reply_markup=reply_markup)
        return
    await message.answer(text or "", reply_markup=reply_markup)


async def show_template_detail(
    message: Message,
    *,
    db_session: AsyncSession,
    template_key: str,
    edit: bool,
    state: FSMContext | None = None,
) -> None:
    """Show one editable template detail card."""
    await ensure_required_templates(db_session)
    detail = await build_template_detail_text(
        db_session,
        template_key=template_key,
    )
    if detail is None:
        await show_templates_home(message, db_session=db_session, edit=edit)
        return

    text, reply_markup = detail
    media = build_template_detail_media(template_key)
    if media is not None:
        photo_bytes, filename = media
        if _should_split_template_detail_media(text):
            if state is not None:
                await send_admin_panel(message, state, text=text, reply_markup=reply_markup)
                await send_admin_aux_photo(
                    message,
                    state,
                    photo_bytes=photo_bytes,
                    filename=filename,
                    caption="🖼 Превью картинки шаблона",
                )
                return
            if edit:
                await replace_inline_message_text(message, text, reply_markup=reply_markup)
            else:
                await message.answer(text, reply_markup=reply_markup)
            await message.answer_photo(
                photo=BufferedInputFile(photo_bytes, filename=filename),
                caption="🖼 Превью картинки шаблона",
            )
            return
        if state is not None:
            await send_admin_photo_panel(
                message,
                state,
                photo_bytes=photo_bytes,
                filename=filename,
                caption=text,
                reply_markup=reply_markup,
            )
            return
        await message.answer_photo(
            photo=BufferedInputFile(photo_bytes, filename=filename),
            caption=text,
            reply_markup=reply_markup,
        )
        return
    if state is not None:
        await send_admin_panel(message, state, text=text, reply_markup=reply_markup)
        return
    if edit:
        await replace_inline_message_text(message, text, reply_markup=reply_markup)
        return
    await message.answer(text, reply_markup=reply_markup)


async def dispatch_template_escape(
    message: Message,
    *,
    state: FSMContext,
    db_session: AsyncSession,
    settings: Settings,
    user: User,
    is_admin: bool,
) -> bool:
    """Route commands and admin menu buttons out of template-edit mode."""
    text = (message.text or "").strip()
    if not text:
        return False

    if text in {"/start", "/help", "/admin", "/menu"}:
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await show_admin_menu(message, db_session=db_session, settings=settings, state=state)
        return True

    if text == "📝 Шаблоны":
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await show_templates_home(message, db_session=db_session, edit=False, state=state)
        return True

    if text == "⚙️ Настройки":
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await show_settings(message, db_session=db_session, settings=settings, state=state)
        return True

    if text == "💼 Услуги":
        await state.clear()
        await show_services_list(message, db_session=db_session)
        return True

    if text == "📅 Расписание":
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await show_schedule_menu(message, state=state)
        return True

    if text == "📊 Статистика":
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await show_stats(
            message,
            db_session=db_session,
            settings=settings,
            period="current",
            state=state,
        )
        return True

    if text == "✉️ Рассылка":
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await open_broadcast(message, state, db_session=db_session, is_admin=is_admin)
        return True

    if text == "👥 Клиенты":
        await clear_state_preserving_admin_panel(state, admin_as_client=False)
        await open_clients_section(message, state, is_admin=is_admin)
        return True

    if REQUESTS_MENU_PATTERN.fullmatch(text):
        await state.clear()
        await show_pending_approvals(
            message,
            db_session=db_session,
            is_admin=is_admin,
            settings=settings,
        )
        return True

    if text == "🙈 Режим клиента":
        await state.clear()
        from src.bot.handlers.client.menu import show_client_menu

        await show_client_menu(message, db_session=db_session, user=user)
        return True

    return False


@router.message(lambda message: message.text == "📝 Шаблоны")
async def open_templates(
    message: Message,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Open the template editor section."""
    if not is_admin:
        return
    await show_templates_home(message, db_session=db_session, edit=False, state=state)


@router.callback_query(F.data == "admin_templates:home")
async def open_templates_home_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Return to the template category picker."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is not None:
        await show_templates_home(
            callback.message,
            db_session=db_session,
            edit=True,
            state=state,
        )


@router.callback_query(F.data.startswith("admin_templates:category:"))
async def open_template_category_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Open one template category."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    category_key = callback.data.rsplit(":", 1)[-1]
    await show_template_category(
        callback.message,
        db_session=db_session,
        category_key=category_key,
        edit=True,
        state=state,
    )


@router.callback_query(F.data.startswith("admin_templates:group:"))
async def open_template_group_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Open one subgroup inside a template category."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None or callback.data is None:
        return
    _, _, category_key, group_key = callback.data.split(":", 3)
    await show_template_group(
        callback.message,
        db_session=db_session,
        category_key=category_key,
        group_key=group_key,
        edit=True,
        state=state,
    )


@router.callback_query(F.data.startswith("admin_templates:open:"))
async def open_template_detail_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Open one template detail card."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return
    template_key = callback.data.rsplit(":", 1)[-1]
    await show_template_detail(
        callback.message,
        db_session=db_session,
        template_key=template_key,
        edit=True,
        state=state,
    )


@router.callback_query(F.data == "admin_templates:noop")
async def noop_template_callback(callback: CallbackQuery) -> None:
    """Acknowledge non-action section headers in template keyboards."""
    await callback.answer()


@router.callback_query(F.data.startswith("admin_templates:edit:"))
async def prompt_template_edit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Prompt for new template content."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    template_key = callback.data.split(":", 2)[-1]
    definition = get_template_definition(template_key)
    group_key = (
        resolve_template_group_key(definition.category_key, template_key)
        if definition is not None
        else None
    )
    await state.set_state(AdminTemplateEdit.input_content)
    await state.update_data(
        admin_template_key=template_key,
        admin_template_category=(definition.category_key if definition is not None else "other"),
        admin_template_group=group_key,
    )
    if callback.message is not None:
        await send_admin_panel(
            callback.message,
            state,
            text=await build_template_edit_prompt_text(
                db_session,
                template_key,
            ),
            reply_markup=build_admin_template_edit_cancel_keyboard(),
        )


@router.callback_query(F.data.startswith("admin_templates:upload_image:"))
async def prompt_template_image_upload(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Prompt for a new image attachment for one template."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    template_key = callback.data.split(":", 2)[-1]
    definition = get_template_definition(template_key)
    if definition is None or not definition.supports_media:
        logger.info(
            "template upload skipped: key=%s definition=%s supports_media=%s",
            template_key,
            definition is not None,
            getattr(definition, "supports_media", None),
        )
        return
    await state.set_state(AdminTemplateEdit.await_image)
    await state.update_data(
        admin_template_key=template_key,
        admin_template_category=definition.category_key,
        admin_template_group=resolve_template_group_key(definition.category_key, template_key),
    )
    logger.info("template upload state set: key=%s", template_key)
    if callback.message is not None:
        await send_admin_panel(
            callback.message,
            state,
            text=build_template_image_prompt_text(template_key),
            reply_markup=build_admin_template_media_cancel_keyboard(template_key),
        )


@router.callback_query(F.data.startswith("admin_templates:preview_image:"))
async def preview_template_image(
    callback: CallbackQuery,
    *,
    is_admin: bool,
) -> None:
    """Preview the image currently attached to a template."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    template_key = callback.data.rsplit(":", 1)[-1]
    if not has_template_media(template_key):
        await callback.answer(texts.ADMIN_TEMPLATE_IMAGE_MISSING_ALERT_TEXT, show_alert=True)
        return
    await callback.answer(texts.ADMIN_TEMPLATE_IMAGE_ALREADY_VISIBLE_TEXT)


@router.callback_query(F.data.startswith("admin_templates:remove_image:"))
async def remove_template_image_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Remove the image attached to a template."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    template_key = callback.data.rsplit(":", 1)[-1]
    remove_template_media(template_key)
    if callback.message is not None:
        await show_template_detail(
            callback.message,
            db_session=db_session,
            template_key=template_key,
            edit=True,
            state=state,
        )


@router.callback_query(F.data.startswith("admin_templates:restore_image:"))
async def restore_template_image_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Restore the bundled image after a custom override or deletion."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    template_key = callback.data.rsplit(":", 1)[-1]
    if not restore_bundled_template_media(template_key):
        await callback.answer(texts.ADMIN_TEMPLATE_IMAGE_MISSING_ALERT_TEXT, show_alert=True)
        return
    await callback.answer("Стандартная картинка возвращена")
    if callback.message is not None:
        await show_template_detail(
            callback.message,
            db_session=db_session,
            template_key=template_key,
            edit=True,
            state=state,
        )


@router.callback_query(F.data.startswith("admin_templates:reset_text:"))
async def reset_template_text_callback(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
    db_session: AsyncSession,
) -> None:
    """Restore the built-in text for one editable template."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    template_key = callback.data.rsplit(":", 1)[-1]
    definition = get_template_definition(template_key)
    if definition is None:
        await callback.answer("Не нашла этот шаблон", show_alert=True)
        return
    await TemplateRepository(db_session).upsert(
        key=template_key,
        content=definition.default_content,
    )
    await db_session.commit()
    await callback.answer("Вернула стандартный текст")
    if callback.message is not None:
        await show_template_detail(
            callback.message,
            db_session=db_session,
            template_key=template_key,
            edit=True,
            state=state,
        )


@router.callback_query(
    StateFilter(AdminTemplateEdit.input_content, AdminTemplateEdit.confirm_content),
    F.data == "admin_templates:cancel_edit",
)
async def cancel_template_edit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Cancel template editing and return to the most relevant previous screen."""
    await callback.answer()
    data = await state.get_data()
    template_key = str(data.get("admin_template_key") or "")
    category_key = str(data.get("admin_template_category") or "")
    group_key = str(data.get("admin_template_group") or "")
    await state.clear()
    if callback.message is not None and template_key:
        await show_template_detail(
            callback.message,
            db_session=db_session,
            template_key=template_key,
            edit=True,
            state=state,
        )
        return
    if callback.message is not None and category_key and group_key:
        await show_template_group(
            callback.message,
            db_session=db_session,
            category_key=category_key,
            group_key=group_key,
            edit=True,
            state=state,
        )
        return
    if callback.message is not None and category_key:
        await show_template_category(
            callback.message,
            db_session=db_session,
            category_key=category_key,
            edit=True,
            state=state,
        )


@router.callback_query(
    StateFilter(AdminTemplateEdit.await_image),
    F.data == "admin_templates:cancel_media",
)
async def cancel_template_media_edit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Cancel image editing and return to the most relevant previous screen."""
    await callback.answer()
    data = await state.get_data()
    template_key = str(data.get("admin_template_key") or "")
    category_key = str(data.get("admin_template_category") or "")
    group_key = str(data.get("admin_template_group") or "")
    await state.clear()
    if callback.message is not None and template_key:
        await show_template_detail(
            callback.message,
            db_session=db_session,
            template_key=template_key,
            edit=True,
            state=state,
        )
        return
    if callback.message is not None and category_key and group_key:
        await show_template_group(
            callback.message,
            db_session=db_session,
            category_key=category_key,
            group_key=group_key,
            edit=True,
            state=state,
        )
        return
    if callback.message is not None and category_key:
        await show_template_category(
            callback.message,
            db_session=db_session,
            category_key=category_key,
            edit=True,
            state=state,
        )


@router.callback_query(
    StateFilter(AdminTemplateEdit.confirm_content),
    F.data == "admin_templates:back_to_edit",
)
async def back_to_template_edit(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Return from the warning step back to normal template editing."""
    await callback.answer()
    data = await state.get_data()
    template_key = str(data.get("admin_template_key") or "")
    if callback.message is None or not template_key:
        return
    await state.set_state(AdminTemplateEdit.input_content)
    await send_admin_panel(
        callback.message,
        state,
        text=await build_template_edit_prompt_text(
            db_session,
            template_key,
            draft_content=str(data.get(TEMPLATE_PENDING_CONTENT_KEY) or ""),
        ),
        reply_markup=build_admin_template_edit_cancel_keyboard(),
    )


@router.callback_query(
    StateFilter(AdminTemplateEdit.confirm_content),
    F.data == "admin_templates:save_anyway",
)
async def save_template_content_anyway(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Persist a warned template draft after explicit admin confirmation."""
    await callback.answer()
    data = await state.get_data()
    template_key = str(data.get("admin_template_key") or "")
    category_key = str(data.get("admin_template_category") or "other")
    stored_group_key = str(data.get("admin_template_group") or "")
    pending_content = str(data.get(TEMPLATE_PENDING_CONTENT_KEY) or "").strip()
    panel_chat_id = data.get("admin_panel_chat_id")
    panel_message_id = data.get("admin_panel_message_id")
    if callback.message is None or not template_key or not pending_content:
        return
    await _persist_template_content(
        callback.message,
        state,
        db_session=db_session,
        template_key=template_key,
        category_key=category_key,
        stored_group_key=stored_group_key,
        content=pending_content,
        panel_chat_id=int(panel_chat_id) if panel_chat_id is not None else None,
        panel_message_id=int(panel_message_id) if panel_message_id is not None else None,
    )


@router.message(StateFilter(AdminTemplateEdit.input_content, AdminTemplateEdit.confirm_content))
async def save_template_content(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    settings: Settings,
    user: User,
    is_admin: bool,
) -> None:
    """Persist new template content."""
    if await dispatch_template_escape(
        message,
        state=state,
        db_session=db_session,
        settings=settings,
        user=user,
        is_admin=is_admin,
    ):
        return

    data = await state.get_data()
    template_key = str(data.get("admin_template_key"))
    category_key = str(data.get("admin_template_category") or "other")
    stored_group_key = str(data.get("admin_template_group") or "")
    draft_content = (message.text or "").strip()
    if len(draft_content) < 10:
        await message.answer(texts.ADMIN_TEMPLATE_TOO_SHORT_TEXT)
        return
    missing, unknown = _collect_template_placeholder_warnings(template_key, draft_content)
    if missing or unknown:
        await state.set_state(AdminTemplateEdit.confirm_content)
        await state.update_data(**{TEMPLATE_PENDING_CONTENT_KEY: draft_content})
        await send_admin_panel(
            message,
            state,
            text=_build_placeholder_warning_text(
                template_key,
                missing=missing,
                unknown=unknown,
            ),
            reply_markup=build_admin_template_warning_keyboard(),
        )
        return
    panel_chat_id = data.get("admin_panel_chat_id")
    panel_message_id = data.get("admin_panel_message_id")
    await _persist_template_content(
        message,
        state,
        db_session=db_session,
        template_key=template_key,
        category_key=category_key,
        stored_group_key=stored_group_key,
        content=draft_content,
        panel_chat_id=int(panel_chat_id) if panel_chat_id is not None else None,
        panel_message_id=int(panel_message_id) if panel_message_id is not None else None,
    )


@router.message(StateFilter(AdminTemplateEdit.await_image))
async def save_template_image_content(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
) -> None:
    """Persist a new image attachment for a template.

    Unified handler for await_image state. Accepts either a photo (compressed)
    or a document with an image mime type (admin sending as file). Anything
    else gets a polite reminder to send as photo.
    """
    data = await state.get_data()
    template_key = str(data.get("admin_template_key") or "")
    category_key = str(data.get("admin_template_category") or "other")
    stored_group_key = str(data.get("admin_template_group") or "")
    logger.info(
        "template image handler hit: key=%s content_type=%s photo=%s document=%s",
        template_key,
        message.content_type,
        bool(message.photo),
        bool(message.document),
    )

    image_bytes: bytes | None = None
    if message.photo:
        photo = message.photo[-1]
        try:
            downloaded = await message.bot.download(photo)
        except Exception:
            logger.exception("failed to download template image photo key=%s", template_key)
            downloaded = None
        if downloaded is not None:
            downloaded.seek(0)
            image_bytes = downloaded.read()
    elif message.document is not None and _document_is_supported_image(message.document):
        try:
            downloaded = await message.bot.download(message.document)
        except Exception:
            logger.exception("failed to download template image document key=%s", template_key)
            downloaded = None
        if downloaded is not None:
            downloaded.seek(0)
            image_bytes = downloaded.read()

    if image_bytes is None:
        await message.answer(texts.ADMIN_TEMPLATE_IMAGE_NOT_PHOTO_TEXT)
        return
    if len(image_bytes) > MAX_TEMPLATE_IMAGE_BYTES:
        await message.answer(texts.ADMIN_TEMPLATE_IMAGE_TOO_LARGE_TEXT)
        return

    try:
        save_template_media(template_key, image_bytes)
    except Exception:
        logger.exception("failed to persist template image key=%s", template_key)
        await message.answer(texts.ADMIN_TEMPLATE_IMAGE_NOT_PHOTO_TEXT)
        return

    panel_chat_id = data.get("admin_panel_chat_id")
    panel_message_id = data.get("admin_panel_message_id")
    await state.clear()
    if await refresh_template_detail_panel(
        message,
        state,
        db_session=db_session,
        template_key=template_key,
        notice_text=texts.ADMIN_TEMPLATE_IMAGE_SAVED_TEXT,
        panel_chat_id=int(panel_chat_id) if panel_chat_id is not None else None,
        panel_message_id=int(panel_message_id) if panel_message_id is not None else None,
    ):
        return

    group_key = stored_group_key or resolve_template_group_key(category_key, template_key)
    if group_key:
        await show_template_group(
            message,
            db_session=db_session,
            category_key=category_key,
            group_key=group_key,
            edit=False,
            state=state,
        )
        return
    await show_template_category(
        message,
        db_session=db_session,
        category_key=category_key,
        edit=False,
        state=state,
    )
