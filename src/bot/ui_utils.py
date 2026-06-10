from __future__ import annotations

from aiogram import Bot
from aiogram.types import BufferedInputFile, InputMediaPhoto, Message


async def safe_delete_message(message: Message | None) -> None:
    """Delete a message if possible, ignoring Telegram-side race conditions."""
    if message is None:
        return
    try:
        await message.delete()
    except Exception:
        return


async def replace_inline_message_text(
    message: Message,
    text: str,
    *,
    reply_markup=None,
    parse_mode=None,
) -> None:
    """Edit an inline-menu message in place, falling back to replace-on-failure."""
    try:
        try:
            await message.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TypeError:
            await message.edit_text(text, reply_markup=reply_markup)
        return
    except Exception:
        await safe_delete_message(message)
        try:
            await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
        except TypeError:
            await message.answer(text, reply_markup=reply_markup)


async def replace_inline_message_photo(
    message: Message,
    *,
    photo_bytes: bytes,
    filename: str,
    caption: str,
    reply_markup=None,
    parse_mode=None,
) -> None:
    """Replace an inline-menu message with a photo panel when possible."""
    media = InputMediaPhoto(
        media=BufferedInputFile(photo_bytes, filename=filename),
        caption=caption,
        parse_mode=parse_mode,
    )

    try:
        await message.edit_media(media=media, reply_markup=reply_markup)
        return
    except Exception:
        pass

    bot = getattr(message, "bot", None)
    chat = getattr(message, "chat", None)
    message_id = getattr(message, "message_id", None)
    if bot is not None and chat is not None and message_id is not None:
        try:
            await bot.edit_message_media(
                chat_id=chat.id,
                message_id=message_id,
                media=media,
                reply_markup=reply_markup,
            )
            return
        except Exception:
            pass

    await safe_delete_message(message)
    try:
        await message.answer_photo(
            photo=BufferedInputFile(photo_bytes, filename=filename),
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TypeError:
        await message.answer_photo(
            photo=BufferedInputFile(photo_bytes, filename=filename),
            caption=caption,
            reply_markup=reply_markup,
        )
    except Exception:
        try:
            await message.answer(caption, reply_markup=reply_markup, parse_mode=parse_mode)
        except TypeError:
            await message.answer(caption, reply_markup=reply_markup)


async def replace_inline_message_panel(
    message: Message,
    *,
    text: str | None = None,
    photo_bytes: bytes | None = None,
    filename: str | None = None,
    caption: str | None = None,
    reply_markup=None,
    parse_mode=None,
) -> None:
    """Replace a client/admin inline panel, preferring edit-in-place."""
    if photo_bytes is not None:
        await replace_inline_message_photo(
            message,
            photo_bytes=photo_bytes,
            filename=filename or "panel.png",
            caption=caption or "",
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        return
    if text is None:
        raise ValueError("Either text or photo_bytes must be provided")
    await replace_inline_message_text(
        message,
        text,
        reply_markup=reply_markup,
        parse_mode=parse_mode,
    )


async def upsert_inline_panel(
    bot: Bot,
    *,
    chat_id: int,
    message_id: int,
    text: str,
    reply_markup=None,
    parse_mode=None,
    photo_bytes: bytes | None = None,
    filename: str | None = None,
    caption: str | None = None,
) -> Message:
    """Edit an existing panel by ids, falling back to sending a new message."""
    if photo_bytes is not None:
        media = InputMediaPhoto(
            media=BufferedInputFile(photo_bytes, filename=filename or "panel.png"),
            caption=caption or "",
            parse_mode=parse_mode,
        )
        try:
            await bot.edit_message_media(
                chat_id=chat_id,
                message_id=message_id,
                media=media,
                reply_markup=reply_markup,
            )
            return type(
                "PanelRef",
                (),
                {
                    "chat": type("ChatRef", (), {"id": chat_id})(),
                    "message_id": message_id,
                },
            )()
        except Exception:
            send_photo = getattr(bot, "send_photo", None)
            if send_photo is not None:
                try:
                    return await send_photo(
                        chat_id=chat_id,
                        photo=BufferedInputFile(photo_bytes, filename=filename or "panel.png"),
                        caption=caption or "",
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                except TypeError:
                    return await send_photo(
                        chat_id=chat_id,
                        photo=BufferedInputFile(photo_bytes, filename=filename or "panel.png"),
                        caption=caption or "",
                        reply_markup=reply_markup,
                    )
            return await bot.send_message(
                chat_id=chat_id,
                text=caption or text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )

    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
        # Returning a lightweight reference object is unnecessary here; callers
        # only need stable ids, which remain the same on a successful edit.
        return type(
            "PanelRef",
            (),
            {
                "chat": type("ChatRef", (), {"id": chat_id})(),
                "message_id": message_id,
            },
        )()
    except Exception:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
