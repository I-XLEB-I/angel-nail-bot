from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import proxy_chat as proxy_chat_handler
from src.config import Settings
from src.db.base import Base
from src.db.models import ApprovalRequest, ApprovalRequestKind, ApprovalRequestStatus, User


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.state = None
        self.cleared = False

    async def set_state(self, state) -> None:
        self.state = state

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def clear(self) -> None:
        self.cleared = True
        self.data.clear()
        self.state = None


class FakeChat:
    def __init__(self, chat_id: int = 500) -> None:
        self.id = chat_id


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object | None]] = []

    async def send_message(self, *, chat_id: int, text: str, reply_markup=None) -> None:
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )


class FakeMessage:
    def __init__(self, text: str | None = None, *, bot: FakeBot | None = None) -> None:
        self.text = text
        self.bot = bot or FakeBot()
        self.chat = FakeChat()
        self.message_id = 42
        self.answers: list[tuple[str, object | None]] = []
        self.edits: list[tuple[str, object | None]] = []
        self.photo = None
        self.voice = None
        self.caption = None

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))


class FakeCallback:
    def __init__(self, data: str, *, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message or FakeMessage()
        self.bot = self.message.bot
        self.answered = False

    async def answer(self, *args, **kwargs) -> None:
        del args, kwargs
        self.answered = True


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_start_admin_reply_replaces_photo_or_text_message_safely(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        captured: dict[str, object] = {}

        async def fake_upsert_inline_panel(
            bot, *, chat_id, message_id, text, reply_markup=None, **kwargs
        ):
            del bot, kwargs
            captured["chat_id"] = chat_id
            captured["message_id"] = message_id
            captured["text"] = text
            captured["reply_markup"] = reply_markup
            message = FakeMessage(bot=FakeBot())
            message.chat.id = chat_id
            message.message_id = message_id
            return message

        monkeypatch.setattr(proxy_chat_handler, "upsert_inline_panel", fake_upsert_inline_panel)

        user = User(tg_id=1001, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            kind=ApprovalRequestKind.QUESTION,
            status=ApprovalRequestStatus.PENDING,
            requested_text="Можно ли такой дизайн?",
        )
        session.add_all([user, approval])
        await session.commit()

        callback = FakeCallback(f"approval:reply:{approval.id}")
        state = FakeState()

        await proxy_chat_handler.start_admin_reply(
            callback,
            state,
            db_session=session,
            is_admin=True,
        )

        assert callback.answered is True
        assert state.state is not None
        assert captured["chat_id"] == callback.message.chat.id
        assert captured["message_id"] == callback.message.message_id
        assert captured["text"] == proxy_chat_handler.texts.ADMIN_APPROVAL_REPLY_PROMPT_TEXT

    await engine.dispose()


@pytest.mark.asyncio
async def test_submit_admin_reply_returns_to_pending_queue(monkeypatch) -> None:
    queue_calls: list[str] = []

    async def fake_show_pending_approvals(
        message,
        *,
        db_session,
        is_admin,
        settings,
        state=None,
        edit=False,
        notice_text=None,
    ) -> None:
        del message, db_session, is_admin, settings, state, edit
        queue_calls.append(str(notice_text))

    monkeypatch.setattr(proxy_chat_handler, "show_pending_approvals", fake_show_pending_approvals)

    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=2001, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            kind=ApprovalRequestKind.QUESTION,
            status=ApprovalRequestStatus.PENDING,
            requested_text="Есть вопрос",
        )
        session.add_all([user, approval])
        await session.commit()

        message = FakeMessage("Ответ клиентке")
        state = FakeState()
        await state.update_data(approval_id=approval.id, admin_action="reply")

        await proxy_chat_handler.submit_admin_reply(
            message,
            state,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert queue_calls == [proxy_chat_handler.texts.ADMIN_APPROVAL_REPLY_SENT_TEXT]
        assert message.answers == []
        assert len(message.bot.sent_messages) == 1
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.PENDING
        assert refreshed.admin_response_text == "Ответ клиентке"

    await engine.dispose()


@pytest.mark.asyncio
async def test_submit_admin_reply_preserves_offered_status(monkeypatch) -> None:
    queue_calls: list[str] = []

    async def fake_show_pending_approvals(
        message,
        *,
        db_session,
        is_admin,
        settings,
        state=None,
        edit=False,
        notice_text=None,
    ) -> None:
        del message, db_session, is_admin, settings, state, edit
        queue_calls.append(str(notice_text))

    monkeypatch.setattr(proxy_chat_handler, "show_pending_approvals", fake_show_pending_approvals)

    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=2003, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            kind=ApprovalRequestKind.NEW_BOOKING,
            status=ApprovalRequestStatus.OFFERED,
            requested_text="Можно позже?",
        )
        session.add_all([user, approval])
        await session.commit()

        message = FakeMessage("Уточняю детали")
        state = FakeState()
        await state.update_data(approval_id=approval.id, admin_action="reply")

        await proxy_chat_handler.submit_admin_reply(
            message,
            state,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert queue_calls == [proxy_chat_handler.texts.ADMIN_APPROVAL_REPLY_SENT_TEXT]
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.OFFERED
        assert refreshed.admin_response_text == "Уточняю детали"

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_admin_quick_reply_keeps_request_open(monkeypatch) -> None:
    queue_calls: list[str] = []

    async def fake_show_pending_approvals(
        message,
        *,
        db_session,
        is_admin,
        settings,
        state=None,
        edit=False,
        notice_text=None,
    ) -> None:
        del message, db_session, is_admin, settings, state, edit
        queue_calls.append(str(notice_text))

    monkeypatch.setattr(proxy_chat_handler, "show_pending_approvals", fake_show_pending_approvals)

    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=2004, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            kind=ApprovalRequestKind.NEW_BOOKING,
            status=ApprovalRequestStatus.PENDING,
            requested_text="После 19 можно?",
        )
        session.add_all([user, approval])
        await session.commit()

        callback = FakeCallback(f"approval:quick_reply:{approval.id}:after_19")
        state = FakeState()

        await proxy_chat_handler.send_admin_quick_reply(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert callback.answered is True
        assert queue_calls == [proxy_chat_handler.texts.ADMIN_APPROVAL_REPLY_SENT_TEXT]
        assert len(callback.bot.sent_messages) == 1
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.PENDING
        assert (
            refreshed.admin_response_text
            == proxy_chat_handler.texts.ADMIN_APPROVAL_QUICK_REPLY_AFTER_19_TEXT
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_submit_admin_decline_reason_requires_explicit_confirmation(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_send_admin_panel(message, state, *, text, reply_markup=None, parse_mode=None):
        del message, state, parse_mode
        captured["text"] = text
        captured["reply_markup"] = reply_markup
        return FakeMessage()

    monkeypatch.setattr(proxy_chat_handler, "send_admin_panel", fake_send_admin_panel)

    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=2002, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            kind=ApprovalRequestKind.QUESTION,
            status=ApprovalRequestStatus.PENDING,
            requested_text="Есть вопрос",
        )
        session.add_all([user, approval])
        await session.commit()

        message = FakeMessage("Своя причина отказа")
        state = FakeState()
        await state.update_data(admin_action="decline", approval_id=approval.id)

        await proxy_chat_handler.submit_admin_reply(
            message,
            state,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.PENDING
        assert state.data["decline_pending_reason"] == "Своя причина отказа"
        assert message.bot.sent_messages == []
        assert "Точно отказать клиентке" in str(captured["text"])

    await engine.dispose()
