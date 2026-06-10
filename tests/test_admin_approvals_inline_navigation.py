from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import approvals as approvals_handler
from src.db.base import Base
from src.db.models import (
    ApprovalRequest,
    ApprovalRequestKind,
    ApprovalRequestStatus,
    Slot,
    SlotStatus,
    User,
)
from src.services.schedule_image import ScheduleImageEntry, ScheduleImagePage


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)


class FakeChat:
    def __init__(self, chat_id: int = 700) -> None:
        self.id = chat_id


class FakeBot:
    pass


class FakeMessage:
    def __init__(self) -> None:
        self.chat = FakeChat()
        self.message_id = 55


class FakeCallback:
    def __init__(self, data: str, *, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message or FakeMessage()
        self.bot = FakeBot()
        self.answered = False

    async def answer(self, *args, **kwargs) -> None:
        del args, kwargs
        self.answered = True


@pytest.mark.asyncio
async def test_decline_request_from_photo_card_uses_safe_panel_update(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    captured: dict[str, object] = {}

    async def fake_upsert_inline_panel(
        bot, *, chat_id, message_id, text, reply_markup=None, **kwargs
    ):
        del bot, kwargs
        captured["chat_id"] = chat_id
        captured["message_id"] = message_id
        captured["text"] = text
        captured["reply_markup"] = reply_markup
        message = FakeMessage()
        message.chat.id = chat_id
        message.message_id = message_id
        return message

    monkeypatch.setattr(approvals_handler, "upsert_inline_panel", fake_upsert_inline_panel)

    async with session_factory() as session:
        user = User(tg_id=5000, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            requested_text="Можно завтра в 18:00?",
            kind=ApprovalRequestKind.NEW_BOOKING,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        session.add_all([user, approval])
        await session.commit()

        callback = FakeCallback(f"approval:decline:{approval.id}")
        state = FakeState()

        await approvals_handler.decline_request(
            callback,
            state=state,
            db_session=session,
            is_admin=True,
            settings=type("SettingsStub", (), {"tz": "Europe/Moscow"})(),
        )

        assert callback.answered is True
        assert captured["chat_id"] == callback.message.chat.id
        assert captured["message_id"] == callback.message.message_id
        assert captured["text"] == approvals_handler.texts.ADMIN_APPROVAL_DECLINE_PROMPT_TEXT

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_slot_picker_from_photo_card_uses_safe_panel_update(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=5001, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            requested_text="Можно завтра в 18:00?",
            kind=ApprovalRequestKind.NEW_BOOKING,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.FREE,
        )
        session.add_all([user, approval, slot])
        await session.commit()

        captured: dict[str, object] = {}

        async def fake_upsert_inline_panel(
            bot, *, chat_id, message_id, text, reply_markup=None, **kwargs
        ):
            del bot
            captured["chat_id"] = chat_id
            captured["message_id"] = message_id
            captured["text"] = text
            captured["reply_markup"] = reply_markup
            captured["extra"] = kwargs
            message = FakeMessage()
            message.chat.id = chat_id
            message.message_id = message_id
            return message

        monkeypatch.setattr(approvals_handler, "upsert_inline_panel", fake_upsert_inline_panel)

        async def fake_is_schedule_image_enabled(*args, **kwargs):
            del args, kwargs
            return True

        monkeypatch.setattr(
            approvals_handler,
            "is_schedule_image_enabled",
            fake_is_schedule_image_enabled,
        )

        async def fake_build_schedule_image_pages_data(*args, **kwargs):
            del args, kwargs
            return [
                ScheduleImagePage(
                    entries=[
                        ScheduleImageEntry(
                            local_date=approvals_handler.format_local_datetime(
                                slot.start_at,
                                "Europe/Moscow",
                            ).date(),
                            day_label="18 мая",
                            times=["16:00", "18:00"],
                        )
                    ],
                    period="18 мая",
                    caption="Свободные окошки",
                    page_number=1,
                    total_pages=1,
                )
            ]

        monkeypatch.setattr(
            approvals_handler,
            "build_schedule_image_pages_data",
            fake_build_schedule_image_pages_data,
        )
        monkeypatch.setattr(
            approvals_handler,
            "render_schedule_image_bytes",
            lambda *args, **kwargs: b"\x89PNGfake",
        )

        callback = FakeCallback(f"approval:confirm:{approval.id}")
        state = FakeState()

        await approvals_handler.open_slot_picker(
            callback,
            state=state,
            approval=approval,
            db_session=session,
            settings=type("SettingsStub", (), {"tz": "Europe/Moscow"})(),
        )

        assert captured["chat_id"] == callback.message.chat.id
        assert captured["message_id"] == callback.message.message_id
        assert captured["text"] == approvals_handler.texts.ADMIN_APPROVAL_CONFIRM_DAY_TEXT
        assert captured["reply_markup"] is not None
        assert captured["extra"]["photo_bytes"] == b"\x89PNGfake"
        callbacks = [
            button.callback_data
            for row in captured["reply_markup"].inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert any(callback_data.startswith("approval:pick_day:") for callback_data in callbacks)

    await engine.dispose()


@pytest.mark.asyncio
async def test_pick_approval_day_opens_time_keyboard_with_back_to_days(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=5004, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            requested_text="Можно вечером?",
            kind=ApprovalRequestKind.RESCHEDULE,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        slot = Slot(
            start_at=datetime.now(UTC).replace(hour=18, minute=0, second=0, microsecond=0)
            + timedelta(days=2),
            status=SlotStatus.FREE,
        )
        session.add_all([user, approval, slot])
        await session.commit()

        captured: dict[str, object] = {}

        async def fake_upsert_inline_panel(
            bot, *, chat_id, message_id, text, reply_markup=None, **kwargs
        ):
            del bot, kwargs
            captured["chat_id"] = chat_id
            captured["message_id"] = message_id
            captured["text"] = text
            captured["reply_markup"] = reply_markup
            message = FakeMessage()
            message.chat.id = chat_id
            message.message_id = message_id
            return message

        monkeypatch.setattr(approvals_handler, "upsert_inline_panel", fake_upsert_inline_panel)

        local_day = approvals_handler.format_local_datetime(
            slot.start_at,
            "Europe/Moscow",
        ).date().isoformat()
        callback = FakeCallback(f"approval:pick_day:{approval.id}:offer:{local_day}")
        state = FakeState()

        await approvals_handler.choose_approval_slot_picker_day(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=type("SettingsStub", (), {"tz": "Europe/Moscow"})(),
        )

        assert callback.answered is True
        assert "ВЫБЕРИ ВРЕМЯ" in str(captured["text"])
        markup = captured["reply_markup"]
        assert markup is not None
        callbacks = [
            button.callback_data
            for row in markup.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert f"approval:offer_slot:{approval.id}:{slot.id}" in callbacks
        assert (
            f"approval:pick_days_back:{approval.id}:offer:{local_day}" in callbacks
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_request_with_exact_time_resolves_without_slot_picker(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=5002, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            requested_text="24.04 18:00",
            kind=ApprovalRequestKind.FREQUENT_BOOKING,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        session.add_all([user, approval])
        await session.commit()

        captured: dict[str, object] = {}

        async def fake_resolve_with_slot(
            *,
            callback,
            state=None,
            approval,
            slot_id,
            db_session,
            settings,
        ) -> None:
            del callback, state, db_session, settings
            captured["approval_id"] = approval.id
            captured["slot_id"] = slot_id

        async def fake_open_slot_picker(*args, **kwargs) -> None:
            raise AssertionError("slot picker should not open for exact direct confirm")

        monkeypatch.setattr(approvals_handler, "resolve_with_slot", fake_resolve_with_slot)
        monkeypatch.setattr(approvals_handler, "open_slot_picker", fake_open_slot_picker)

        callback = FakeCallback(f"approval:confirm:{approval.id}")
        state = FakeState()

        await approvals_handler.confirm_request(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=type("SettingsStub", (), {"tz": "Europe/Moscow"})(),
        )

        assert callback.answered is True
        assert captured["approval_id"] == approval.id
        assert isinstance(captured["slot_id"], int)


@pytest.mark.asyncio
async def test_decline_commit_unavailable_without_state_replaces_current_card(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    captured: dict[str, object] = {}

    async def fake_replace_inline_message_text(message, text, reply_markup=None, **kwargs):
        del message, kwargs
        captured["text"] = text
        captured["reply_markup"] = reply_markup

    monkeypatch.setattr(
        approvals_handler,
        "replace_inline_message_text",
        fake_replace_inline_message_text,
    )

    async with session_factory() as session:
        callback = FakeCallback("approval:decline_commit:999:busy")

        await approvals_handler.decline_with_template_reason_commit(
            callback,
            db_session=session,
            is_admin=True,
        )

        assert callback.answered is True
        assert captured["text"] == approvals_handler.texts.MY_BOOKINGS_ACTION_UNAVAILABLE_TEXT

    await engine.dispose()

    await engine.dispose()


@pytest.mark.asyncio
async def test_open_approval_client_card_preserves_return_context(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=5003, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            requested_text="Завтра вечером",
            kind=ApprovalRequestKind.NEW_BOOKING,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        session.add_all([user, approval])
        await session.commit()

        captured: dict[str, object] = {}

        async def fake_show_client_card(
            target,
            *,
            db_session,
            settings,
            client_id,
            back_callback,
            edit=False,
            notice_text=None,
        ) -> None:
            del target, db_session, settings, notice_text
            captured["client_id"] = client_id
            captured["back_callback"] = back_callback
            captured["edit"] = edit

        monkeypatch.setattr(approvals_handler, "show_client_card", fake_show_client_card)

        callback = FakeCallback(f"approval:client:{approval.id}")

        await approvals_handler.open_approval_client_card(
            callback,
            db_session=session,
            is_admin=True,
            settings=type("SettingsStub", (), {"tz": "Europe/Moscow"})(),
        )

        assert callback.answered is True
        assert captured["client_id"] == user.id
        assert captured["back_callback"] == f"admin_approvals:open:{approval.id}"
        assert captured["edit"] is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_quiet_close_approval_resolves_without_client_message(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    captured: dict[str, object] = {}

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
        captured["notice_text"] = notice_text

    monkeypatch.setattr(approvals_handler, "show_pending_approvals", fake_show_pending_approvals)

    async with session_factory() as session:
        user = User(tg_id=5004, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            requested_text="Завтра вечером",
            kind=ApprovalRequestKind.LATE_RESCHEDULE,
            status=ApprovalRequestStatus.OFFERED,
            addons=[],
            design_photos=[],
        )
        session.add_all([user, approval])
        await session.commit()

        callback = FakeCallback(f"approval:quiet_close:{approval.id}")
        state = FakeState()

        await approvals_handler.quietly_close_approval(
            callback,
            state=state,
            db_session=session,
            is_admin=True,
            settings=type("SettingsStub", (), {"tz": "Europe/Moscow"})(),
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert callback.answered is True
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.RESPONDED
        assert refreshed.admin_response_text == "Тихо закрыто"
        assert captured["notice_text"] == approvals_handler.texts.ADMIN_APPROVAL_QUIET_CLOSE_TEXT

    await engine.dispose()


@pytest.mark.asyncio
async def test_read_callback_still_quietly_closes_question(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    captured: dict[str, object] = {}

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
        captured["notice_text"] = notice_text

    monkeypatch.setattr(approvals_handler, "show_pending_approvals", fake_show_pending_approvals)

    async with session_factory() as session:
        user = User(tg_id=5005, display_name="Клиентка", is_admin=False, is_blocked=False)
        approval = ApprovalRequest(
            client=user,
            requested_text="Есть вопрос",
            kind=ApprovalRequestKind.QUESTION,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        session.add_all([user, approval])
        await session.commit()

        callback = FakeCallback(f"approval:read:{approval.id}")
        state = FakeState()

        await approvals_handler.quietly_close_approval(
            callback,
            state=state,
            db_session=session,
            is_admin=True,
            settings=type("SettingsStub", (), {"tz": "Europe/Moscow"})(),
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert callback.answered is True
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.RESPONDED
        assert refreshed.admin_response_text == "Прочитано"
        assert captured["notice_text"] == approvals_handler.texts.ADMIN_APPROVAL_READ_TEXT

    await engine.dispose()
