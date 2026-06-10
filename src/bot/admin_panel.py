from __future__ import annotations

from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, Message

from src.bot.ui_utils import upsert_inline_panel

ADMIN_PANEL_CHAT_ID_KEY = "admin_panel_chat_id"
ADMIN_PANEL_MESSAGE_ID_KEY = "admin_panel_message_id"
ADMIN_PANEL_AUX_CHAT_ID_KEY = "admin_panel_aux_chat_id"
ADMIN_PANEL_AUX_MESSAGE_ID_KEY = "admin_panel_aux_message_id"


async def delete_previous_admin_panel(state: FSMContext, *, bot) -> None:
    """Delete the previously remembered admin panel message, if any."""
    data = await state.get_data()
    chat_id = data.get(ADMIN_PANEL_CHAT_ID_KEY)
    message_id = data.get(ADMIN_PANEL_MESSAGE_ID_KEY)
    if not chat_id or not message_id:
        return
    try:
        await bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))
    except Exception:
        return


async def delete_previous_admin_aux_message(state: FSMContext, *, bot) -> None:
    """Delete the previously remembered auxiliary admin message, if any."""
    data = await state.get_data()
    chat_id = data.get(ADMIN_PANEL_AUX_CHAT_ID_KEY)
    message_id = data.get(ADMIN_PANEL_AUX_MESSAGE_ID_KEY)
    if not chat_id or not message_id:
        return
    try:
        await bot.delete_message(chat_id=int(chat_id), message_id=int(message_id))
    except Exception:
        return


async def remember_admin_panel(state: FSMContext, message: Message) -> None:
    """Store the latest admin panel message ids in FSM data."""
    if not hasattr(message, "chat") or not hasattr(message, "message_id"):
        return
    await state.update_data(
        **{
            ADMIN_PANEL_CHAT_ID_KEY: message.chat.id,
            ADMIN_PANEL_MESSAGE_ID_KEY: message.message_id,
        }
    )


async def remember_admin_aux_message(state: FSMContext, message: Message) -> None:
    """Store the latest auxiliary admin message ids in FSM data."""
    if not hasattr(message, "chat") or not hasattr(message, "message_id"):
        return
    await state.update_data(
        **{
            ADMIN_PANEL_AUX_CHAT_ID_KEY: message.chat.id,
            ADMIN_PANEL_AUX_MESSAGE_ID_KEY: message.message_id,
        }
    )


async def clear_admin_aux_message_reference(state: FSMContext) -> None:
    """Forget the stored auxiliary admin message ids."""
    await state.update_data(
        **{
            ADMIN_PANEL_AUX_CHAT_ID_KEY: None,
            ADMIN_PANEL_AUX_MESSAGE_ID_KEY: None,
        }
    )


async def send_admin_panel(
    message: Message,
    state: FSMContext,
    *,
    text: str,
    reply_markup=None,
    parse_mode=None,
) -> Message:
    """Replace the previous admin section panel, preferring in-place edits."""
    bot = getattr(message, "bot", None)
    data = await state.get_data()
    previous_chat_id = data.get(ADMIN_PANEL_CHAT_ID_KEY)
    previous_message_id = data.get(ADMIN_PANEL_MESSAGE_ID_KEY)
    if bot is not None:
        await delete_previous_admin_aux_message(state, bot=bot)
        await clear_admin_aux_message_reference(state)
        if previous_chat_id and previous_message_id:
            panel = await upsert_inline_panel(
                bot,
                chat_id=int(previous_chat_id),
                message_id=int(previous_message_id),
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            if getattr(panel, "message_id", None) != int(previous_message_id):
                try:
                    await bot.delete_message(
                        chat_id=int(previous_chat_id),
                        message_id=int(previous_message_id),
                    )
                except Exception:
                    pass
            await remember_admin_panel(state, panel)
            return panel
    try:
        panel = await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TypeError:
        panel = await message.answer(text, reply_markup=reply_markup)
    if panel is None:
        panel = message
    await remember_admin_panel(state, panel)
    return panel


async def send_admin_photo_panel(
    message: Message,
    state: FSMContext,
    *,
    photo_bytes: bytes,
    filename: str,
    caption: str,
    reply_markup=None,
    parse_mode=None,
) -> Message:
    """Replace the previous admin panel with a photo-based panel."""
    bot = getattr(message, "bot", None)
    data = await state.get_data()
    previous_chat_id = data.get(ADMIN_PANEL_CHAT_ID_KEY)
    previous_message_id = data.get(ADMIN_PANEL_MESSAGE_ID_KEY)
    if bot is not None:
        await delete_previous_admin_aux_message(state, bot=bot)
        await clear_admin_aux_message_reference(state)
        if previous_chat_id and previous_message_id:
            panel = await upsert_inline_panel(
                bot,
                chat_id=int(previous_chat_id),
                message_id=int(previous_message_id),
                text=caption,
                photo_bytes=photo_bytes,
                filename=filename,
                caption=caption,
                reply_markup=reply_markup,
                parse_mode=parse_mode,
            )
            if getattr(panel, "message_id", None) != int(previous_message_id):
                try:
                    await bot.delete_message(
                        chat_id=int(previous_chat_id),
                        message_id=int(previous_message_id),
                    )
                except Exception:
                    pass
            await remember_admin_panel(state, panel)
            return panel
    try:
        panel = await message.answer_photo(
            photo=BufferedInputFile(photo_bytes, filename=filename),
            caption=caption,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )
    except TypeError:
        panel = await message.answer_photo(
            photo=BufferedInputFile(photo_bytes, filename=filename),
            caption=caption,
            reply_markup=reply_markup,
        )
    if panel is None:
        panel = message
    await remember_admin_panel(state, panel)
    return panel


async def send_admin_aux_photo(
    message: Message,
    state: FSMContext,
    *,
    photo_bytes: bytes,
    filename: str,
    caption: str | None = None,
    parse_mode=None,
) -> Message:
    """Send or replace a short-lived auxiliary admin photo under the main panel."""
    bot = getattr(message, "bot", None)
    if bot is not None:
        await delete_previous_admin_aux_message(state, bot=bot)
        await clear_admin_aux_message_reference(state)
    try:
        panel = await message.answer_photo(
            photo=BufferedInputFile(photo_bytes, filename=filename),
            caption=caption,
            parse_mode=parse_mode,
        )
    except TypeError:
        panel = await message.answer_photo(
            photo=BufferedInputFile(photo_bytes, filename=filename),
            caption=caption,
        )
    if panel is None:
        panel = message
    await remember_admin_aux_message(state, panel)
    return panel


async def clear_state_preserving_admin_panel(
    state: FSMContext,
    *,
    admin_as_client: bool | None = None,
) -> None:
    """Clear FSM state but keep the remembered admin panel ids."""
    data = await state.get_data()
    keep_admin_as_client = (
        data.get("admin_as_client", False) if admin_as_client is None else admin_as_client
    )
    panel_chat_id = data.get(ADMIN_PANEL_CHAT_ID_KEY)
    panel_message_id = data.get(ADMIN_PANEL_MESSAGE_ID_KEY)
    aux_chat_id = data.get(ADMIN_PANEL_AUX_CHAT_ID_KEY)
    aux_message_id = data.get(ADMIN_PANEL_AUX_MESSAGE_ID_KEY)
    await state.clear()
    payload: dict[str, object] = {}
    if keep_admin_as_client:
        payload["admin_as_client"] = True
    if panel_chat_id and panel_message_id:
        payload[ADMIN_PANEL_CHAT_ID_KEY] = panel_chat_id
        payload[ADMIN_PANEL_MESSAGE_ID_KEY] = panel_message_id
    if aux_chat_id and aux_message_id:
        payload[ADMIN_PANEL_AUX_CHAT_ID_KEY] = aux_chat_id
        payload[ADMIN_PANEL_AUX_MESSAGE_ID_KEY] = aux_message_id
    if payload:
        await state.update_data(**payload)
