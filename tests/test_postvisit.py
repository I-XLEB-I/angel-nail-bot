from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.client import postvisit as postvisit_handler
from src.config import Settings
from src.db.base import Base
from src.db.models import (
    ApprovalRequest,
    Booking,
    BookingStatus,
    Service,
    ServiceKind,
    Slot,
    SlotStatus,
    User,
)


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}
        self.state = None

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def set_state(self, state) -> None:
        self.state = state

    async def clear(self) -> None:
        self.data.clear()
        self.state = None


class FakeBot:
    pass


class FakeMessage:
    def __init__(self, text: str | None = None, *, bot: FakeBot | None = None) -> None:
        self.text = text
        self.caption = None
        self.photo = None
        self.voice = None
        self.bot = bot or FakeBot()
        self.answers: list[tuple[str, object | None]] = []
        self.edits: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))


class FakeCallback:
    def __init__(
        self,
        data: str,
        *,
        bot: FakeBot | None = None,
        message: FakeMessage | None = None,
    ) -> None:
        self.data = data
        self.bot = bot or FakeBot()
        self.message = message or FakeMessage(bot=self.bot)
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


async def seed_completed_booking(session):
    user = User(
        tg_id=1001,
        display_name="Аня",
        phone="+79990000001",
        is_admin=False,
        is_blocked=False,
    )
    service = Service(
        name="Маникюр",
        price=2400,
        price_variable=False,
        duration_min=120,
        kind=ServiceKind.BASE,
        is_active=True,
        display_order=10,
    )
    slot = Slot(
        start_at=datetime.now(UTC) - timedelta(days=1),
        status=SlotStatus.BOOKED,
    )
    booking = Booking(
        client=user,
        slot=slot,
        base_service=service,
        addons=[],
        design_photos=[],
        fixed_price=2400,
        has_variable_price=False,
        status=BookingStatus.COMPLETED,
    )
    session.add_all([user, service, slot, booking])
    await session.commit()
    return user, booking


@pytest.mark.asyncio
async def test_low_rating_creates_approval_immediately(monkeypatch) -> None:
    sent_approvals: list[int] = []

    async def fake_send_approval_card_to_admins(*, approval, **kwargs) -> None:
        del kwargs
        sent_approvals.append(approval.id)

    monkeypatch.setattr(
        postvisit_handler,
        "send_approval_card_to_admins",
        fake_send_approval_card_to_admins,
    )

    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, booking = await seed_completed_booking(session)
        state = FakeState()
        callback = FakeCallback(f"postvisit:rate:{booking.id}:1")

        await postvisit_handler.rate_postvisit(
            callback,
            state,
            db_session=session,
            user=user,
            settings=settings,
        )

        approval = await session.scalar(select(ApprovalRequest))
        assert approval is not None
        assert approval.requested_text == "Низкая оценка: 1⭐ (без комментария)"
        assert approval.related_booking_id == booking.id
        assert sent_approvals == [approval.id]
        assert state.state == postvisit_handler.AskingMaster.input_message
        assert state.data["postvisit_feedback_approval_id"] == approval.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_mid_rating_comment_reuses_existing_approval(monkeypatch) -> None:
    forwarded_messages: list[str] = []

    async def fake_send_approval_card_to_admins(**kwargs) -> None:
        del kwargs

    async def fake_send_text_to_admins(bot, *, admin_tg_ids, text, reply_markup=None) -> None:
        del bot, admin_tg_ids, reply_markup
        forwarded_messages.append(text)

    monkeypatch.setattr(
        postvisit_handler,
        "send_approval_card_to_admins",
        fake_send_approval_card_to_admins,
    )
    monkeypatch.setattr(postvisit_handler, "send_text_to_admins", fake_send_text_to_admins)

    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, booking = await seed_completed_booking(session)
        state = FakeState()
        callback = FakeCallback(f"postvisit:rate:{booking.id}:3")

        await postvisit_handler.rate_postvisit(
            callback,
            state,
            db_session=session,
            user=user,
            settings=settings,
        )

        first_count = await session.scalar(select(func.count(ApprovalRequest.id)))
        assert first_count == 1
        assert state.state == postvisit_handler.PostvisitFeedback.input_text

        message = FakeMessage("Хочется чуть аккуратнее у кутикулы")
        await postvisit_handler.submit_postvisit_feedback(
            message,
            state,
            db_session=session,
            user=user,
            settings=settings,
        )

        final_count = await session.scalar(select(func.count(ApprovalRequest.id)))
        assert final_count == 1
        assert len(forwarded_messages) == 1
        assert "Хочется чуть аккуратнее у кутикулы" in forwarded_messages[0]
        assert message.answers[-1][0] == postvisit_handler.texts.POSTVISIT_FEEDBACK_THANK_YOU_TEXT

    await engine.dispose()
