from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import force_majeure as force_majeure_handler
from src.config import Settings
from src.db.base import Base
from src.db.models import (
    ApprovalRequest,
    ApprovalRequestKind,
    ApprovalRequestStatus,
    Booking,
    BookingStatus,
    Service,
    ServiceKind,
    Slot,
    SlotStatus,
    User,
)
from src.db.repositories.templates import TemplateRepository


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})
        self.cleared = False
        self.state = None

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.data.clear()
        self.cleared = True


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
    def __init__(self, data: str) -> None:
        self.data = data
        self.message = FakeMessage()
        self.bot = FakeBot()
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
async def test_force_majeure_day_uses_editable_default_template(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    rendered: list[tuple[str, object | None]] = []

    async def fake_replace(message, text, reply_markup=None, **kwargs) -> None:
        del message, kwargs
        rendered.append((text, reply_markup))

    monkeypatch.setattr(
        force_majeure_handler,
        "replace_inline_message_text",
        fake_replace,
    )

    async with session_factory() as session:
        await TemplateRepository(session).upsert(
            key="force_majeure_notice",
            content="Свой текст форс-мажора для клиентки",
        )
        await session.commit()
        callback = FakeCallback("force_majeure:day:2026-07-20")
        state = FakeState()

        await force_majeure_handler.force_majeure_day_chosen(
            callback,
            state,
            is_admin=True,
            db_session=session,
        )

        assert state.data["force_majeure_reason"] == "Свой текст форс-мажора для клиентки"
        assert "Свой текст форс-мажора" in rendered[0][0]
        markup = rendered[0][1]
        assert markup.inline_keyboard[0][0].callback_data == (
            "force_majeure:use_template:2026-07-20"
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_force_majeure_final_commit_cancels_active_bookings_and_marks_notice_sent(
    monkeypatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sent: list[dict[str, object]] = []
    replaced: list[str] = []

    async def fake_send_text_to_user(_bot, *, tg_id: int, text: str, reply_markup=None) -> None:
        sent.append({"tg_id": tg_id, "text": text, "reply_markup": reply_markup})

    async def fake_replace_inline_message_text(message, text, reply_markup=None, **kwargs) -> None:
        del message, reply_markup, kwargs
        replaced.append(text)

    async def fake_clear_state_preserving_admin_panel(state, **kwargs) -> None:
        del kwargs
        await state.clear()

    monkeypatch.setattr(force_majeure_handler, "send_text_to_user", fake_send_text_to_user)
    monkeypatch.setattr(
        force_majeure_handler,
        "replace_inline_message_text",
        fake_replace_inline_message_text,
    )
    monkeypatch.setattr(
        force_majeure_handler,
        "clear_state_preserving_admin_panel",
        fake_clear_state_preserving_admin_panel,
    )

    async with session_factory() as session:
        user = User(tg_id=5001, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        start_at = datetime.now(UTC) + timedelta(days=1)
        slot = Slot(start_at=start_at, status=SlotStatus.BOOKED)
        booking = Booking(
            client=user,
            slot=slot,
            base_service=service,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.PENDING_MASTER,
        )
        approval = ApprovalRequest(
            client=user,
            related_booking=booking,
            requested_text="Можно завтра?",
            kind=ApprovalRequestKind.RESCHEDULE,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        session.add_all([user, service, slot, booking, approval])
        await session.commit()

        state = FakeState({"force_majeure_reason": "Авария в доме"})
        callback = FakeCallback(
            "force_majeure:final_commit:"
            f"{start_at.astimezone(ZoneInfo('Europe/Moscow')).date().isoformat()}"
        )

        await force_majeure_handler.force_majeure_final_commit(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )

        await session.refresh(booking)
        await session.refresh(approval)

        assert callback.answered is True
        assert booking.status == BookingStatus.CANCELLED_BY_MASTER
        assert booking.cancel_reason_code == "force_majeure"
        assert booking.force_majeure_notice_sent_at is not None
        assert approval.status == ApprovalRequestStatus.DECLINED
        assert len(sent) == 1
        assert "Авария в доме" in str(sent[0]["text"])
        assert replaced[-1].startswith("✅")

    await engine.dispose()


@pytest.mark.asyncio
async def test_force_majeure_final_commit_resumes_unsent_notice_without_duplicate(
    monkeypatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    sent: list[int] = []

    async def fake_send_text_to_user(_bot, *, tg_id: int, text: str, reply_markup=None) -> None:
        del text, reply_markup
        sent.append(tg_id)

    async def fake_replace_inline_message_text(message, text, reply_markup=None, **kwargs) -> None:
        del message, text, reply_markup, kwargs

    async def fake_clear_state_preserving_admin_panel(state, **kwargs) -> None:
        del kwargs
        await state.clear()

    monkeypatch.setattr(force_majeure_handler, "send_text_to_user", fake_send_text_to_user)
    monkeypatch.setattr(
        force_majeure_handler,
        "replace_inline_message_text",
        fake_replace_inline_message_text,
    )
    monkeypatch.setattr(
        force_majeure_handler,
        "clear_state_preserving_admin_panel",
        fake_clear_state_preserving_admin_panel,
    )

    async with session_factory() as session:
        user = User(tg_id=5002, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        start_at = datetime.now(UTC) + timedelta(days=2)
        slot = Slot(start_at=start_at, status=SlotStatus.BOOKED)
        booking = Booking(
            client=user,
            slot=slot,
            base_service=service,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CANCELLED_BY_MASTER,
            cancel_reason_code="force_majeure",
            cancel_reason_text="Авария в доме",
            force_majeure_notice_sent_at=None,
        )
        session.add_all([user, service, slot, booking])
        await session.commit()

        callback = FakeCallback(
            "force_majeure:final_commit:"
            f"{start_at.astimezone(ZoneInfo('Europe/Moscow')).date().isoformat()}"
        )
        state = FakeState({"force_majeure_reason": "Авария в доме"})

        await force_majeure_handler.force_majeure_final_commit(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )
        await session.refresh(booking)
        assert booking.force_majeure_notice_sent_at is not None
        assert sent == [5002]

        await force_majeure_handler.force_majeure_final_commit(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=build_settings(),
        )
        assert sent == [5002]

    await engine.dispose()
