from __future__ import annotations

import io
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram.types import (
    BufferedInputFile,
    InputMediaPhoto,
    InputRichBlock,
    InputRichBlockBlockQuotation,
    InputRichBlockDetails,
    InputRichBlockDivider,
    InputRichBlockFooter,
    InputRichBlockList,
    InputRichBlockListItem,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockPullQuotation,
    InputRichBlockSectionHeading,
    InputRichBlockTable,
    InputRichMessage,
    Message,
    RichBlockTableCell,
    RichTextBold,
    RichTextItalic,
    RichTextMarked,
    RichTextUnderline,
)
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.handlers.client.address import build_public_address_text
from src.bot.handlers.client.portfolio import build_master_profile_caption
from src.config import Settings
from src.db.models import ServiceKind
from src.db.repositories.services import ServiceRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.admin_defaults import required_template_defaults
from src.services.booking import format_service_price
from src.services.image_theme import DEFAULT_ASSETS_DIR
from src.services.runtime_settings import get_bool_setting
from src.services.studio_address import load_studio_address_copy_text
from src.services.template_media import has_template_media, template_media_path
from src.services.template_texts import ensure_late_policy_notice, render_template_text

RICH_MESSAGES_TEST_ENABLED_KEY = "rich_messages_test_enabled"
COPYABLE_MEDIA_CONTENT_TYPES = frozenset(
    {"animation", "audio", "document", "photo", "video", "voice"}
)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True, slots=True)
class RichPreview:
    """One standard/rich comparison rendered only in the admin sandbox."""

    standard_text: str
    rich_message: InputRichMessage
    standard_media_path: Path | None = None


RichPreviewBuilder = Callable[[AsyncSession, Settings], Awaitable[RichPreview]]


@dataclass(frozen=True, slots=True)
class RichPreviewDefinition:
    """Metadata and builder for one extensible rich sandbox idea."""

    key: str
    title: str
    builder: RichPreviewBuilder


@dataclass(frozen=True, slots=True)
class RichMediaDefinition:
    """One independently managed image slot used only by rich previews."""

    key: str
    title: str


async def is_rich_messages_test_enabled(db_session: AsyncSession) -> bool:
    """Return whether the admin-only rich sandbox is enabled."""
    return await get_bool_setting(
        SettingRepository(db_session),
        key=RICH_MESSAGES_TEST_ENABLED_KEY,
        default=False,
    )


def validate_rich_test_source_message(message: Message) -> str | None:
    """Return an error message when a source message is unsafe for test copying."""
    if getattr(message, "media_group_id", None):
        return texts.ADMIN_RICH_TEST_UNSUPPORTED_MESSAGE_TEXT

    if getattr(message, "rich_message", None) is not None:
        return None

    content_type = str(getattr(message, "content_type", "") or "")
    text = (getattr(message, "text", None) or "").strip()
    caption = (getattr(message, "caption", None) or "").strip()

    if content_type == "text" and text:
        return None
    if content_type in COPYABLE_MEDIA_CONTENT_TYPES and caption:
        return None
    return texts.ADMIN_RICH_TEST_UNSUPPORTED_MESSAGE_TEXT


def _plain_text(value: str) -> str:
    return unescape(_HTML_TAG_RE.sub("", value)).strip()


def _split_heading_and_body(value: str, *, fallback_heading: str) -> tuple[str, list[str]]:
    paragraphs = [part.strip() for part in _plain_text(value).split("\n\n") if part.strip()]
    if not paragraphs:
        return fallback_heading, []
    first_lines = [line.strip() for line in paragraphs[0].splitlines() if line.strip()]
    heading = first_lines[0] if first_lines else fallback_heading
    body: list[str] = []
    if len(first_lines) > 1:
        body.append("\n".join(first_lines[1:]))
    body.extend(paragraphs[1:])
    return heading, body


def _text_blocks(value: str, *, fallback_heading: str) -> list[InputRichBlock]:
    heading, paragraphs = _split_heading_and_body(value, fallback_heading=fallback_heading)
    blocks: list[InputRichBlock] = [
        InputRichBlockSectionHeading(text=heading, size=2),
    ]
    blocks.extend(InputRichBlockParagraph(text=paragraph) for paragraph in paragraphs)
    return blocks


def _effective_media_path(*keys: str) -> Path | None:
    for key in keys:
        if has_template_media(key):
            return template_media_path(key)
    return None


def _photo_block(path: Path, *, compact: bool = False) -> InputRichBlockPhoto:
    if not compact:
        content = path.read_bytes()
    else:
        with Image.open(path) as source:
            image = source.convert("RGB")
            target_ratio = 3.0
            current_ratio = image.width / image.height
            if current_ratio < target_ratio:
                crop_height = max(1, round(image.width / target_ratio))
                top = max(0, (image.height - crop_height) // 2)
                image = image.crop((0, top, image.width, top + crop_height))
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=90, optimize=True)
            content = buffer.getvalue()
    return InputRichBlockPhoto(
        photo=InputMediaPhoto(
            media=BufferedInputFile(content, filename=path.name),
        )
    )


def _price_table(title: str, services: list) -> InputRichBlockTable:
    cells = [
        [
            RichBlockTableCell(align="left", valign="middle", text="Услуга", is_header=True),
            RichBlockTableCell(align="right", valign="middle", text="Цена", is_header=True),
        ]
    ]
    for service in services:
        cells.append(
            [
                RichBlockTableCell(align="left", valign="middle", text=service.name),
                RichBlockTableCell(
                    align="right",
                    valign="middle",
                    text=RichTextBold(text=format_service_price(service)),
                ),
            ]
        )
    return InputRichBlockTable(
        cells=cells,
        is_bordered=True,
        is_striped=True,
        caption=title,
    )


async def build_rich_price_preview(
    db_session: AsyncSession,
    settings: Settings,
) -> RichPreview:
    """Build the current price and a data-driven rich table comparison."""
    del settings
    service_repository = ServiceRepository(db_session)
    template_repository = TemplateRepository(db_session)
    defaults = required_template_defaults()
    price_text = await template_repository.get_content_or_default("price", defaults["price"])
    base_services = await service_repository.list_active(kind=ServiceKind.BASE)
    addon_services = await service_repository.list_active(kind=ServiceKind.ADDON)

    blocks = _text_blocks(price_text, fallback_heading="Актуальный прайс")
    rich_banner = _effective_media_path("rich_price_header", "greeting_header")
    if rich_banner is None:
        bundled_brand = DEFAULT_ASSETS_DIR / "brand.jpg"
        rich_banner = bundled_brand if bundled_brand.exists() else None
    if rich_banner is not None:
        blocks.insert(1, _photo_block(rich_banner, compact=True))
    if base_services:
        blocks.append(_price_table("Основные услуги", base_services))
    if addon_services:
        blocks.append(_price_table("Дополнительно", addon_services))
    if not base_services and not addon_services:
        blocks.append(InputRichBlockParagraph(text="Активных услуг пока нет."))

    return RichPreview(
        standard_text=price_text.strip() or defaults["price"],
        standard_media_path=_effective_media_path("price"),
        rich_message=InputRichMessage(blocks=blocks),
    )


async def build_rich_price_message(db_session: AsyncSession) -> InputRichMessage:
    """Keep the original public helper used by existing sandbox integrations."""
    preview = await build_rich_price_preview(db_session, Settings())
    return preview.rich_message


async def build_rich_about_preview(
    db_session: AsyncSession,
    settings: Settings,
) -> RichPreview:
    """Build the current master profile and a structured rich comparison."""
    del settings
    caption = await build_master_profile_caption(db_session)
    blocks = _text_blocks(caption, fallback_heading="Знакомься — это Ангела")
    media_path = _effective_media_path("rich_about_inline", "about_master")
    if media_path is not None:
        insert_at = min(2, len(blocks))
        blocks.insert(insert_at, _photo_block(media_path))
    return RichPreview(
        standard_text=caption,
        standard_media_path=_effective_media_path("about_master"),
        rich_message=InputRichMessage(blocks=blocks),
    )


async def build_rich_address_preview(
    db_session: AsyncSession,
    settings: Settings,
) -> RichPreview:
    """Build the current public address and an inline-image rich comparison."""
    del settings
    address_text = await build_public_address_text(db_session)
    blocks = _text_blocks(address_text, fallback_heading="Адрес и как добраться")
    media_path = _effective_media_path("rich_address_landmark", "navigation_public")
    if media_path is not None:
        blocks.insert(min(2, len(blocks)), _photo_block(media_path))
    return RichPreview(
        standard_text=address_text,
        standard_media_path=_effective_media_path("navigation_public"),
        rich_message=InputRichMessage(blocks=blocks),
    )


def _preview_datetime(settings: Settings) -> tuple[str, str]:
    local = datetime.now(ZoneInfo(settings.tz)) + timedelta(days=1)
    return local.strftime("%d.%m.%Y"), "14:00"


async def build_rich_reminder_24h_preview(
    db_session: AsyncSession,
    settings: Settings,
) -> RichPreview:
    """Build a standard/rich preview for the day-before reminder."""
    date_label, time_label = _preview_datetime(settings)
    address = await load_studio_address_copy_text(SettingRepository(db_session))
    values = {
        "name": "Мария",
        "display_name": "Мария",
        "date": date_label,
        "time": time_label,
        "service": "Покрытие гель-лак",
        "service_name": "Покрытие гель-лак",
        "address": address,
        "address_short": address,
        "address_text": address,
    }
    template = await TemplateRepository(db_session).get_content_or_default(
        "reminder_24h",
        texts.DEFAULT_REMINDER_24H_TEMPLATE,
    )
    standard = render_template_text(template, values).strip()
    blocks: list[InputRichBlock] = [
        InputRichBlockSectionHeading(text="Завтра встречаемся, Мария 🌸", size=2),
        InputRichBlockParagraph(
            text=["📅 ", RichTextBold(text=f"{date_label}, в {time_label}")]
        ),
        InputRichBlockParagraph(
            text=["💅 ", RichTextBold(text="Покрытие гель-лак")]
        ),
        InputRichBlockParagraph(text=f"📍 {address}"),
        InputRichBlockDivider(),
        InputRichBlockParagraph(text="Всё в силе?"),
    ]
    return RichPreview(standard_text=standard, rich_message=InputRichMessage(blocks=blocks))


async def build_rich_reminder_2h_preview(
    db_session: AsyncSession,
    settings: Settings,
) -> RichPreview:
    """Build a standard/rich preview for the immediate pre-visit reminder."""
    del settings
    values = {
        "name": "Мария",
        "date": "сегодня",
        "time": "14:00",
        "service": "Покрытие гель-лак",
        "service_name": "Покрытие гель-лак",
    }
    template = await TemplateRepository(db_session).get_content_or_default(
        "reminder_2h",
        texts.DEFAULT_REMINDER_2H_TEMPLATE,
    )
    standard = ensure_late_policy_notice(render_template_text(template, values).strip())
    blocks: list[InputRichBlock] = [
        InputRichBlockSectionHeading(
            text=["Уже скоро — сегодня в ", RichTextUnderline(text="14:00")],
            size=2,
        ),
        InputRichBlockParagraph(
            text=["💅 ", RichTextBold(text="Покрытие гель-лак")]
        ),
        InputRichBlockDivider(),
        InputRichBlockParagraph(
            text="Если задержишься больше чем на 15 минут — запись может отмениться 🤍"
        ),
        InputRichBlockParagraph(
            text="Если опаздываешь — нажми «⏰ Опаздываю» ниже, я сразу передам Ангеле."
        ),
    ]
    return RichPreview(standard_text=standard, rich_message=InputRichMessage(blocks=blocks))


async def build_rich_booking_confirmation_preview(
    db_session: AsyncSession,
    settings: Settings,
) -> RichPreview:
    """Build a safe sample booking confirmation without creating a booking."""
    date_label, time_label = _preview_datetime(settings)
    address = await load_studio_address_copy_text(SettingRepository(db_session))
    address_block = f"<b>📍 Адрес</b>\n{address}"
    template = await TemplateRepository(db_session).get_content_or_default(
        "booking_confirm",
        texts.DEFAULT_BOOKING_CONFIRM_TEMPLATE,
    )
    standard = render_template_text(
        template,
        {
            "name": "Мария",
            "date": date_label,
            "time": time_label,
            "service": "Покрытие гель-лак",
            "payment": "Наличными",
            "address": address,
            "address_block": address_block,
        },
    ).strip()
    blocks: list[InputRichBlock] = [
        InputRichBlockSectionHeading(text="Записала тебя ✨", size=2),
        InputRichBlockParagraph(
            text=["📅 ", RichTextBold(text=f"{date_label} · {time_label}")]
        ),
        InputRichBlockParagraph(
            text=["💅 ", RichTextBold(text="Покрытие гель-лак")]
        ),
        InputRichBlockParagraph(text=["💳 ", RichTextBold(text="Наличными")]),
        InputRichBlockDivider(),
        InputRichBlockParagraph(text=f"📍 {address}"),
    ]
    media_path = _effective_media_path("booking_confirm")
    if media_path is not None:
        blocks.append(_photo_block(media_path))
    blocks.extend(
        [
            InputRichBlockDivider(),
            InputRichBlockParagraph(text="Напомню за сутки и за 2 часа."),
            InputRichBlockParagraph(
                text="Если что-то изменится — открой «Мои записи» в меню 🤍"
            ),
            InputRichBlockParagraph(text="До встречи 🌸"),
        ]
    )
    return RichPreview(
        standard_text=standard,
        standard_media_path=media_path,
        rich_message=InputRichMessage(blocks=blocks),
    )


async def build_rich_calm_style_preview(
    db_session: AsyncSession,
    settings: Settings,
) -> RichPreview:
    """Show a restrained premium hierarchy for transactional messages."""
    date_label, time_label = _preview_datetime(settings)
    address = await load_studio_address_copy_text(SettingRepository(db_session))
    standard = (
        "<b>Записала тебя ✨</b>\n\n"
        f"📅 <b>{date_label} · {time_label}</b>\n"
        "💅 <b>Покрытие гель-лак</b>\n"
        "💳 Наличными\n\n"
        "────────────\n\n"
        f"📍 {address}\n\n"
        "Напомню за сутки и за 2 часа.\n"
        "Если что-то изменится — открой «Мои записи» 🤍"
    )
    blocks: list[InputRichBlock] = [
        InputRichBlockSectionHeading(text="Записала тебя ✨", size=2),
        InputRichBlockParagraph(
            text=[
                "📅 ",
                RichTextBold(text=date_label),
                " · ",
                RichTextMarked(text=RichTextBold(text=time_label)),
            ]
        ),
        InputRichBlockParagraph(
            text=["💅 ", RichTextBold(text="Покрытие гель-лак")]
        ),
        InputRichBlockParagraph(text="💳 Наличными"),
        InputRichBlockDivider(),
        InputRichBlockParagraph(text=["📍 ", RichTextBold(text=address)]),
        InputRichBlockFooter(
            text="Напомню за сутки и за 2 часа. Если что-то изменится — открой «Мои записи» 🤍"
        ),
    ]
    return RichPreview(standard_text=standard, rich_message=InputRichMessage(blocks=blocks))


async def build_rich_editorial_style_preview(
    db_session: AsyncSession,
    settings: Settings,
) -> RichPreview:
    """Show an editorial composition for warm brand storytelling."""
    del settings
    standard = (
        "<b>Знакомься — это Ангела</b>\n\n"
        "Мастер, к которому приходят не только за красивым маникюром, "
        "но и за спокойным временем для себя.\n\n"
        "<i>«Мне важно, чтобы тебе было комфортно на каждом этапе»</i>\n\n"
        "Ниже можно посмотреть работы и выбрать настроение для следующего визита."
    )
    blocks: list[InputRichBlock] = [
        InputRichBlockSectionHeading(text="Знакомься — это Ангела", size=1),
        InputRichBlockParagraph(
            text=[
                "Мастер, к которому приходят не только за ",
                RichTextBold(text="красивым маникюром"),
                ", но и за спокойным временем для себя.",
            ]
        ),
    ]
    media_path = _effective_media_path("rich_about_inline", "about_master")
    if media_path is not None:
        blocks.append(_photo_block(media_path))
    blocks.extend(
        [
            InputRichBlockPullQuotation(
                text=RichTextItalic(
                    text="Мне важно, чтобы тебе было комфортно на каждом этапе"
                ),
                credit="Ангела",
            ),
            InputRichBlockParagraph(
                text="Ниже можно посмотреть работы и выбрать настроение для следующего визита."
            ),
            InputRichBlockFooter(text="Красиво, аккуратно и без лишней суеты 🌸"),
        ]
    )
    return RichPreview(
        standard_text=standard,
        standard_media_path=_effective_media_path("about_master"),
        rich_message=InputRichMessage(blocks=blocks),
    )


async def build_rich_functional_style_preview(
    db_session: AsyncSession,
    settings: Settings,
) -> RichPreview:
    """Show lists, disclosure and a quotation in a practical address card."""
    del settings
    address = await load_studio_address_copy_text(SettingRepository(db_session))
    standard = (
        "<b>Адрес и как добраться</b>\n\n"
        f"📍 <b>{address}</b>\n\n"
        "1. Открой маршрут кнопкой ниже.\n"
        "2. Сверься с фотографией входа.\n"
        "3. Если не найдёшь студию — напиши Ангеле.\n\n"
        "Все дополнительные ориентиры можно держать в сворачиваемом блоке."
    )
    blocks: list[InputRichBlock] = [
        InputRichBlockSectionHeading(text="Адрес и как добраться", size=2),
        InputRichBlockParagraph(text=["📍 ", RichTextBold(text=address)]),
    ]
    media_path = _effective_media_path("rich_address_landmark", "navigation_public")
    if media_path is not None:
        blocks.append(_photo_block(media_path, compact=True))
    blocks.extend(
        [
            InputRichBlockSectionHeading(text="Перед выходом", size=4),
            InputRichBlockList(
                items=[
                    InputRichBlockListItem(
                        blocks=[InputRichBlockParagraph(text="Открой маршрут кнопкой ниже")],
                        has_checkbox=True,
                        is_checked=True,
                    ),
                    InputRichBlockListItem(
                        blocks=[InputRichBlockParagraph(text="Сверься с фотографией входа")],
                        has_checkbox=True,
                    ),
                    InputRichBlockListItem(
                        blocks=[InputRichBlockParagraph(text="При необходимости напиши Ангеле")],
                        has_checkbox=True,
                    ),
                ]
            ),
            InputRichBlockDetails(
                summary=RichTextBold(text="Как найти вход"),
                blocks=[
                    InputRichBlockParagraph(
                        text=(
                            "Здесь можно показать код двери, этаж и подробные ориентиры, "
                            "не перегружая основной экран."
                        )
                    )
                ],
            ),
            InputRichBlockBlockQuotation(
                blocks=[
                    InputRichBlockParagraph(
                        text="Если не найдёшь студию — напиши Ангеле, она поможет сориентироваться."
                    )
                ]
            ),
            InputRichBlockFooter(text="Маршрут и связь с мастером — на кнопках ниже."),
        ]
    )
    return RichPreview(
        standard_text=standard,
        standard_media_path=_effective_media_path("navigation_public"),
        rich_message=InputRichMessage(blocks=blocks),
    )


RICH_PREVIEW_DEFINITIONS: tuple[RichPreviewDefinition, ...] = (
    RichPreviewDefinition("price", "Прайс", build_rich_price_preview),
    RichPreviewDefinition("about", "Об Ангеле", build_rich_about_preview),
    RichPreviewDefinition("address", "Адрес", build_rich_address_preview),
    RichPreviewDefinition("reminder_24h", "Напоминание за сутки", build_rich_reminder_24h_preview),
    RichPreviewDefinition("reminder_2h", "Напоминание за 2 часа", build_rich_reminder_2h_preview),
    RichPreviewDefinition(
        "booking_confirm",
        "Подтверждение записи",
        build_rich_booking_confirmation_preview,
    ),
    RichPreviewDefinition(
        "style_calm",
        "Стиль: спокойный премиум",
        build_rich_calm_style_preview,
    ),
    RichPreviewDefinition(
        "style_editorial",
        "Стиль: редакционный",
        build_rich_editorial_style_preview,
    ),
    RichPreviewDefinition(
        "style_functional",
        "Стиль: функциональный",
        build_rich_functional_style_preview,
    ),
)

RICH_MEDIA_DEFINITIONS: tuple[RichMediaDefinition, ...] = (
    RichMediaDefinition("rich_price_header", "Баннер прайса"),
    RichMediaDefinition("rich_about_inline", "Фото «Об Ангеле»"),
    RichMediaDefinition("rich_address_landmark", "Ориентир адреса"),
)


def get_rich_preview_definition(key: str) -> RichPreviewDefinition | None:
    """Return one registered sandbox preview by its callback key."""
    return next((item for item in RICH_PREVIEW_DEFINITIONS if item.key == key), None)


def get_rich_media_definition(key: str) -> RichMediaDefinition | None:
    """Return one independently managed rich-preview image slot."""
    return next((item for item in RICH_MEDIA_DEFINITIONS if item.key == key), None)
