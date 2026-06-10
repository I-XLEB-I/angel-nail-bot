from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiogram.types import BufferedInputFile, Message

from src.bot.ui_utils import replace_inline_message_panel
from src.services.template_media import has_template_media, template_media_path

BRAND_IMAGE_PATH = Path(__file__).resolve().parents[4] / "assets" / "brand.jpg"


def load_image_bytes(path: Path) -> bytes | None:
    """Return image bytes if the asset exists."""
    if not path.exists():
        return None
    return path.read_bytes()


def load_brand_image_bytes() -> bytes | None:
    """Return the shared brand image bytes if the asset exists."""
    return load_image_bytes(BRAND_IMAGE_PATH)


async def send_brand_message(
    message: Message,
    *,
    caption: str,
    reply_markup=None,
    replace_current: bool = False,
    template_key: str | None = None,
    image_path: Path | None = None,
    fallback_title: str | None = None,
    fallback_subtitle: str | None = None,
    fallback_kind: str = "client_card",
    parse_mode=None,
) -> None:
    """Send a shared brand image, falling back to plain text when no static media exists."""
    resolved_image_path = BRAND_IMAGE_PATH
    if template_key and has_template_media(template_key):
        resolved_image_path = template_media_path(template_key)
    elif image_path is not None:
        resolved_image_path = image_path
    image_bytes = load_image_bytes(resolved_image_path)
    if image_bytes is not None:
        if replace_current:
            await replace_inline_message_panel(
                message,
                photo_bytes=image_bytes,
                filename=resolved_image_path.name,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            return
        answer_photo = getattr(message, "answer_photo", None)
        if answer_photo is not None:
            try:
                await answer_photo(
                    photo=BufferedInputFile(image_bytes, filename=resolved_image_path.name),
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            except TypeError:
                await answer_photo(
                    photo=BufferedInputFile(image_bytes, filename=resolved_image_path.name),
                    caption=caption,
                    reply_markup=reply_markup,
                )
                return
            except Exception:
                pass
            else:
                return

    if replace_current:
        await replace_inline_message_panel(
            message,
            text=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return
    try:
        await message.answer(caption, reply_markup=reply_markup, parse_mode=parse_mode)
    except TypeError:
        await message.answer(caption, reply_markup=reply_markup)


async def send_template_message(
    message: Message,
    *,
    template_key: str,
    caption: str,
    reply_markup=None,
    replace_current: bool = False,
    parse_mode=None,
) -> None:
    """Send a template image when attached, otherwise send plain text only."""
    if has_template_media(template_key):
        image_path = template_media_path(template_key)
        image_bytes = load_image_bytes(image_path)
        if image_bytes is not None:
            if replace_current:
                await replace_inline_message_panel(
                    message,
                    photo_bytes=image_bytes,
                    filename=image_path.name,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
                return
            try:
                await message.answer_photo(
                    photo=BufferedInputFile(image_bytes, filename=image_path.name),
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=parse_mode,
                )
            except TypeError:
                await message.answer_photo(
                    photo=BufferedInputFile(image_bytes, filename=image_path.name),
                    caption=caption,
                    reply_markup=reply_markup,
                )
                return
            except Exception:
                pass
            else:
                return

    if replace_current:
        await replace_inline_message_panel(
            message,
            text=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return
    try:
        await message.answer(caption, reply_markup=reply_markup, parse_mode=parse_mode)
    except TypeError:
        await message.answer(caption, reply_markup=reply_markup)


async def send_brand_bot_message(
    bot: Bot,
    *,
    chat_id: int,
    caption: str,
    reply_markup=None,
    template_key: str | None = None,
    image_path: Path | None = None,
    parse_mode=None,
) -> None:
    """Send a brand image in proactive bot messages, falling back to plain text."""
    resolved_image_path = BRAND_IMAGE_PATH
    if template_key and has_template_media(template_key):
        resolved_image_path = template_media_path(template_key)
    elif image_path is not None:
        resolved_image_path = image_path
    image_bytes = load_image_bytes(resolved_image_path)
    send_photo = getattr(bot, "send_photo", None)
    if image_bytes is not None and send_photo is not None:
        try:
            await send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(image_bytes, filename=resolved_image_path.name),
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
        except TypeError:
            await send_photo(
                chat_id=chat_id,
                photo=BufferedInputFile(image_bytes, filename=resolved_image_path.name),
                caption=caption,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            pass
        else:
            return
    try:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TypeError:
        await bot.send_message(
            chat_id=chat_id,
            text=caption,
            reply_markup=reply_markup,
        )
