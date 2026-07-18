from __future__ import annotations

from html import escape

from aiogram.types import (
    BufferedInputFile,
    InputMediaPhoto,
    InputRichMessage,
    InputRichMessageMedia,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.db.models import ServiceKind
from src.db.repositories.services import ServiceRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.admin_defaults import required_template_defaults
from src.services.booking import format_service_price
from src.services.runtime_settings import get_bool_setting
from src.services.template_media import has_template_media, template_media_path

RICH_MESSAGES_TEST_ENABLED_KEY = "rich_messages_test_enabled"
RICH_PRICE_MEDIA_ID = "price_cover"
COPYABLE_MEDIA_CONTENT_TYPES = frozenset(
    {"animation", "audio", "document", "photo", "video", "voice"}
)


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


def _split_price_intro(text: str) -> tuple[str, str]:
    """Split one editable intro into a heading and the remaining body."""
    paragraphs = [chunk.strip() for chunk in text.strip().split("\n\n") if chunk.strip()]
    if not paragraphs:
        return "Актуальный прайс", ""

    first_block = paragraphs[0]
    first_lines = [line.strip() for line in first_block.splitlines() if line.strip()]
    if not first_lines:
        return "Актуальный прайс", "\n\n".join(paragraphs[1:])

    heading = first_lines[0]
    body_blocks: list[str] = []
    remaining_first_block = "\n".join(first_lines[1:]).strip()
    if remaining_first_block:
        body_blocks.append(remaining_first_block)
    body_blocks.extend(paragraphs[1:])
    return heading, "\n\n".join(body_blocks).strip()


def _render_rich_paragraphs(text: str) -> str:
    """Render plain admin-editable text as rich HTML paragraphs."""
    blocks: list[str] = []
    for paragraph in text.split("\n\n"):
        lines = [escape(line.strip()) for line in paragraph.splitlines() if line.strip()]
        if not lines:
            continue
        blocks.append(f"<p>{' '.join(lines)}</p>")
    return "".join(blocks)


def _render_price_table(title: str, services: list) -> str:
    """Render one rich HTML price table for one service group."""
    rows = [
        "<table bordered striped>",
        f"<caption>{escape(title)}</caption>",
        "<tr><th>Услуга</th><th>Цена</th></tr>",
    ]
    for service in services:
        rows.append(
            "<tr>"
            f"<td>{escape(service.name)}</td>"
            f"<td align=\"right\">{escape(format_service_price(service))}</td>"
            "</tr>"
        )
    rows.append("</table>")
    return "".join(rows)


async def build_rich_price_message(db_session: AsyncSession) -> InputRichMessage:
    """Build the admin-only rich price preview from current templates and services."""
    service_repository = ServiceRepository(db_session)
    template_repository = TemplateRepository(db_session)
    defaults = required_template_defaults()
    price_text = await template_repository.get_content_or_default("price", defaults["price"])
    base_services = await service_repository.list_active(kind=ServiceKind.BASE)
    addon_services = await service_repository.list_active(kind=ServiceKind.ADDON)

    heading, body = _split_price_intro(price_text)
    html_parts: list[str] = []
    media: list[InputRichMessageMedia] | None = None

    if has_template_media("price"):
        image_path = template_media_path("price")
        media = [
            InputRichMessageMedia(
                id=RICH_PRICE_MEDIA_ID,
                media=InputMediaPhoto(
                    media=BufferedInputFile(
                        image_path.read_bytes(),
                        filename=image_path.name,
                    )
                ),
            )
        ]
        html_parts.append(f'<img src="tg://photo?id={RICH_PRICE_MEDIA_ID}" alt="Прайс"/>')

    html_parts.append(f"<h2>{escape(heading or 'Актуальный прайс')}</h2>")
    if body:
        html_parts.append(_render_rich_paragraphs(body))

    if base_services:
        html_parts.append(_render_price_table("Основные услуги", base_services))
    if addon_services:
        html_parts.append(_render_price_table("Дополнительно", addon_services))
    if not base_services and not addon_services:
        html_parts.append("<p>Активных услуг пока нет.</p>")

    return InputRichMessage(html="".join(html_parts), media=media)
