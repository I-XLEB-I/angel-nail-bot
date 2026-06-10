from __future__ import annotations

import asyncio

from aiogram import Bot, F, Router
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from src.bot import texts
from src.bot.admin_panel import send_admin_panel
from src.bot.keyboards.admin import (
    build_admin_broadcast_input_keyboard,
    build_admin_broadcast_preview_keyboard,
)
from src.bot.states import AdminBroadcast
from src.bot.ui_utils import replace_inline_message_text, upsert_inline_panel
from src.db.repositories.users import UserRepository

router = Router(name="admin_broadcast")


def render_broadcast_prompt_text(recipient_count: int) -> str:
    """Render the single-screen prompt for the broadcast flow."""
    return texts.ADMIN_BROADCAST_PROMPT_TEXT.format(count=recipient_count)


async def run_broadcast(
    bot: Bot,
    *,
    recipient_ids: list[int],
    text: str,
) -> tuple[int, int, int, list[int]]:
    """Send a broadcast through a queue with a 20 msg/sec limit."""
    queue: asyncio.Queue[int | None] = asyncio.Queue()
    for tg_id in recipient_ids:
        await queue.put(tg_id)
    await queue.put(None)

    delivered = 0
    blocked = 0
    failed = 0
    blocked_ids: list[int] = []

    async def worker() -> None:
        nonlocal delivered, blocked, failed
        while True:
            tg_id = await queue.get()
            if tg_id is None:
                queue.task_done()
                break

            try:
                await bot.send_message(
                    chat_id=tg_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                delivered += 1
            except TelegramForbiddenError:
                blocked += 1
                blocked_ids.append(tg_id)
            except TelegramBadRequest as exc:
                error_text = str(exc).lower()
                if (
                    "chat not found" in error_text
                    or "bot was blocked" in error_text
                    or "user is deactivated" in error_text
                ):
                    blocked += 1
                    blocked_ids.append(tg_id)
                else:
                    failed += 1
            except Exception:
                failed += 1
            finally:
                queue.task_done()
                await asyncio.sleep(0.05)

    worker_task = asyncio.create_task(worker())
    await queue.join()
    await worker_task
    return delivered, blocked, failed, blocked_ids


@router.message(lambda message: message.text == "✉️ Рассылка")
async def open_broadcast(
    message: Message,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Start the broadcast flow."""
    if not is_admin:
        return
    recipients = await UserRepository(db_session).list_broadcast_recipients()
    panel = await send_admin_panel(
        message,
        state,
        text=render_broadcast_prompt_text(len(recipients)),
        reply_markup=build_admin_broadcast_input_keyboard(),
    )
    await state.set_state(AdminBroadcast.input_text)
    await state.update_data(
        admin_broadcast_panel_chat_id=panel.chat.id,
        admin_broadcast_panel_message_id=panel.message_id,
        admin_broadcast_recipient_count=len(recipients),
    )


@router.message(StateFilter(AdminBroadcast.input_text))
async def preview_broadcast(
    message: Message,
    state: FSMContext,
) -> None:
    """Render a broadcast preview inside the existing panel."""
    text = (message.text or "").strip()
    data = await state.get_data()
    panel_chat_id = int(data.get("admin_broadcast_panel_chat_id"))
    panel_message_id = int(data.get("admin_broadcast_panel_message_id"))
    recipient_count = int(data.get("admin_broadcast_recipient_count", 0))
    if not text:
        await upsert_inline_panel(
            message.bot,
            chat_id=panel_chat_id,
            message_id=panel_message_id,
            text=render_broadcast_prompt_text(recipient_count),
            reply_markup=build_admin_broadcast_input_keyboard(),
        )
        return

    try:
        panel = await upsert_inline_panel(
            message.bot,
            chat_id=panel_chat_id,
            message_id=panel_message_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=build_admin_broadcast_preview_keyboard(recipient_count),
        )
    except TelegramBadRequest:
        await upsert_inline_panel(
            message.bot,
            chat_id=panel_chat_id,
            message_id=panel_message_id,
            text=texts.ADMIN_BROADCAST_INVALID_TEXT,
            reply_markup=build_admin_broadcast_input_keyboard(),
        )
        return

    await state.update_data(
        admin_broadcast_text=text,
        admin_broadcast_panel_chat_id=panel.chat.id,
        admin_broadcast_panel_message_id=panel.message_id,
    )


@router.callback_query(F.data == "admin_broadcast:cancel")
async def cancel_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    is_admin: bool,
) -> None:
    """Cancel the pending broadcast."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    await state.clear()
    if callback.message is not None:
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_BROADCAST_CANCELLED_TEXT,
            reply_markup=None,
        )


@router.callback_query(F.data == "admin_broadcast:confirm")
async def confirm_broadcast(
    callback: CallbackQuery,
    state: FSMContext,
    *,
    db_session: AsyncSession,
    is_admin: bool,
) -> None:
    """Send the broadcast to all active client recipients."""
    if not is_admin:
        await callback.answer(texts.ADMIN_ONLY_TEXT, show_alert=True)
        return
    await callback.answer()
    if callback.message is None:
        return

    data = await state.get_data()
    text = str(data.get("admin_broadcast_text", "")).strip()
    if not text:
        await replace_inline_message_text(
            callback.message,
            texts.ADMIN_BROADCAST_INVALID_TEXT,
            reply_markup=build_admin_broadcast_input_keyboard(),
        )
        return

    repository = UserRepository(db_session)
    recipients = await repository.list_broadcast_recipients()
    await replace_inline_message_text(
        callback.message,
        texts.ADMIN_BROADCAST_STARTED_TEXT,
        reply_markup=None,
    )
    delivered, blocked, failed, blocked_ids = await run_broadcast(
        callback.bot,
        recipient_ids=[user.tg_id for user in recipients],
        text=text,
    )
    for user in recipients:
        if user.tg_id in blocked_ids:
            user.is_blocked = True
    await db_session.commit()
    await state.clear()
    await replace_inline_message_text(
        callback.message,
        texts.ADMIN_BROADCAST_REPORT_TEXT.format(
            delivered=delivered,
            blocked=blocked,
            failed=failed,
        ),
        reply_markup=None,
    )
