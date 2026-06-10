from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import approvals as approvals_handler
from src.bot.handlers.admin import proxy_chat as proxy_chat_handler
from src.bot.handlers.admin import schedule as schedule_handler
from src.bot.handlers.client import ask_master as ask_master_handler
from src.bot.handlers.client import booking_flow as booking_flow_handler
from src.bot.handlers.client import my_bookings as my_bookings_handler
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
    utcnow,
)
from src.db.repositories.rate_limit_events import RateLimitEventRepository
from src.db.repositories.settings import SettingRepository
from src.services import anti_abuse_alerts
from src.services.anti_abuse import (
    RescheduleAttemptResult,
    attempt_booking_with_anti_abuse,
    attempt_reschedule_with_anti_abuse,
)


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

    async def delete(self) -> None:
        return None


class FakeCallback:
    def __init__(self, data: str, *, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message or FakeMessage()
        self.answered = False
        self.bot = self.message.bot

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


@asynccontextmanager
async def make_session_scope(session_factory):
    async with session_factory() as session:
        yield session


async def create_base_entities(session):
    user = User(
        tg_id=1001,
        tg_username="client_one",
        display_name="Клиентка",
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
    session.add_all([user, service])
    await session.flush()
    return user, service


@pytest.mark.asyncio
async def test_second_active_booking_hits_active_limit() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        now = datetime.now(UTC)
        current_slot = Slot(start_at=now + timedelta(days=7), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=now + timedelta(days=10), status=SlotStatus.FREE)
        session.add_all([current_slot, new_slot])
        await session.flush()
        session.add(
            Booking(
                client_id=user.id,
                slot_id=current_slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=2400,
                has_variable_price=False,
                status=BookingStatus.CONFIRMED,
            )
        )
        await session.commit()

        result = await attempt_booking_with_anti_abuse(
            session,
            user=user,
            slot_id=new_slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            tz_name="Europe/Moscow",
        )

        approval_count = await session.scalar(select(func.count(ApprovalRequest.id)))
        booking_count = await session.scalar(select(func.count(Booking.id)))
        assert result.outcome == "active_limit"
        assert result.approval is None
        assert approval_count == 0
        assert booking_count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_frequent_booking_triggers_approval_without_active_booking() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        now = datetime.now(UTC)
        recent_completed_slot = Slot(start_at=now - timedelta(days=7), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=now + timedelta(days=10), status=SlotStatus.FREE)
        session.add_all([recent_completed_slot, new_slot])
        await session.flush()
        session.add(
            Booking(
                client_id=user.id,
                slot_id=recent_completed_slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=2400,
                has_variable_price=False,
                status=BookingStatus.COMPLETED,
            )
        )
        await session.commit()

        result = await attempt_booking_with_anti_abuse(
            session,
            user=user,
            slot_id=new_slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            tz_name="Europe/Moscow",
        )

        approval_count = await session.scalar(select(func.count(ApprovalRequest.id)))
        assert result.outcome == "frequent_booking"
        assert result.approval is not None
        assert result.approval.kind == ApprovalRequestKind.FREQUENT_BOOKING
        assert approval_count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_regular_client_with_five_completed_visits_bypasses_frequent_gate() -> None:
    """Постоянная клиентка (>=5 завершённых визита) внутри окна
    `min_days_between_bookings` бронируется мгновенно, без ApprovalRequest.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        now = datetime.now(UTC)

        await SettingRepository(session).upsert(key="max_active_bookings_per_user", value="2")

        # Пять завершённых визитов в прошлом — клиентка постоянная.
        for weeks_ago in (4, 8, 12, 16, 20):
            past_slot = Slot(
                start_at=now - timedelta(weeks=weeks_ago),
                status=SlotStatus.BOOKED,
            )
            session.add(past_slot)
            await session.flush()
            session.add(
                Booking(
                    client_id=user.id,
                    slot_id=past_slot.id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                )
            )

        # Активная запись внутри окна — она и триггерит has_relevant_booking_within_window.
        current_slot = Slot(start_at=now + timedelta(days=7), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=now + timedelta(days=10), status=SlotStatus.FREE)
        session.add_all([current_slot, new_slot])
        await session.flush()
        session.add(
            Booking(
                client_id=user.id,
                slot_id=current_slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=2400,
                has_variable_price=False,
                status=BookingStatus.CONFIRMED,
            )
        )
        await session.commit()

        result = await attempt_booking_with_anti_abuse(
            session,
            user=user,
            slot_id=new_slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            tz_name="Europe/Moscow",
        )

        approval_count = await session.scalar(select(func.count(ApprovalRequest.id)))
        # Подтверждение прошло мгновенно: outcome=confirmed, approval не создан.
        assert result.outcome == "confirmed", (
            f"Expected 'confirmed' for regular client, got '{result.outcome}'"
        )
        assert result.approval is None
        assert approval_count == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_booking_attempt_rate_limit_creates_pause() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        new_slot = Slot(start_at=datetime.now(UTC) + timedelta(days=20), status=SlotStatus.FREE)
        session.add(new_slot)
        await session.commit()

        repository = SettingRepository(session)
        await repository.upsert(key="booking_attempt_limit_count", value="2")
        await repository.upsert(key="booking_attempt_limit_window_minutes", value="10")
        await repository.upsert(key="booking_attempt_pause_minutes", value="30")
        await session.commit()

        events = RateLimitEventRepository(session)
        await events.create(
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "failed"},
            created_at=utcnow() - timedelta(minutes=5),
        )
        await events.create(
            user_id=user.id,
            kind="booking_attempt",
            metadata={"outcome": "failed"},
            created_at=utcnow() - timedelta(minutes=1),
        )
        await session.commit()

        result = await attempt_booking_with_anti_abuse(
            session,
            user=user,
            slot_id=new_slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            tz_name="Europe/Moscow",
        )

        pause_events = await events.count_since(
            user_id=user.id,
            kind="booking_attempt_pause",
            since=utcnow() - timedelta(minutes=31),
        )
        assert result.outcome == "attempt_limit"
        assert pause_events == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_booking_outside_window_confirms_directly() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        now = datetime.now(UTC)
        old_slot = Slot(start_at=now - timedelta(days=40), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=now + timedelta(days=25), status=SlotStatus.FREE)
        session.add_all([old_slot, new_slot])
        await session.flush()
        session.add(
            Booking(
                client_id=user.id,
                slot_id=old_slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=2400,
                has_variable_price=False,
                status=BookingStatus.COMPLETED,
            )
        )
        await session.commit()

        result = await attempt_booking_with_anti_abuse(
            session,
            user=user,
            slot_id=new_slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            tz_name="Europe/Moscow",
        )

        assert result.outcome == "confirmed"
        assert result.confirm_result is not None
        assert result.confirm_result.ok is True
        assert result.confirm_result.booking is not None
        assert result.confirm_result.booking.status == BookingStatus.CONFIRMED

    await engine.dispose()


@pytest.mark.asyncio
async def test_late_reschedule_creates_approval_request() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        now = datetime.now(UTC)
        old_slot = Slot(start_at=now + timedelta(days=5), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=now + timedelta(hours=20), status=SlotStatus.FREE)
        session.add_all([old_slot, new_slot])
        await session.flush()
        booking = Booking(
            client_id=user.id,
            slot_id=old_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.commit()

        result = await attempt_reschedule_with_anti_abuse(
            session,
            user=user,
            booking=booking,
            new_slot_id=new_slot.id,
            tz_name="Europe/Moscow",
        )

        assert result.outcome == "late_reschedule"
        assert result.approval is not None
        assert result.approval.kind == ApprovalRequestKind.LATE_RESCHEDULE

    await engine.dispose()


@pytest.mark.asyncio
async def test_repeated_late_reschedule_reuses_same_pending_approval() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        now = datetime.now(UTC)
        old_slot = Slot(start_at=now + timedelta(days=5), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=now + timedelta(hours=20), status=SlotStatus.FREE)
        session.add_all([old_slot, new_slot])
        await session.flush()
        booking = Booking(
            client_id=user.id,
            slot_id=old_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.commit()

        first = await attempt_reschedule_with_anti_abuse(
            session,
            user=user,
            booking=booking,
            new_slot_id=new_slot.id,
            tz_name="Europe/Moscow",
        )
        second = await attempt_reschedule_with_anti_abuse(
            session,
            user=user,
            booking=booking,
            new_slot_id=new_slot.id,
            tz_name="Europe/Moscow",
        )

        approval_count = await session.scalar(select(func.count(ApprovalRequest.id)))
        assert first.outcome == "late_reschedule"
        assert first.approval is not None
        assert second.outcome == "approval_existing"
        assert second.approval is not None
        assert second.approval.id == first.approval.id
        assert approval_count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_reschedule_outside_window_direct() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        now = datetime.now(UTC)
        old_slot = Slot(start_at=now + timedelta(days=10), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=now + timedelta(days=15), status=SlotStatus.FREE)
        session.add_all([old_slot, new_slot])
        await session.flush()
        booking = Booking(
            client_id=user.id,
            slot_id=old_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.commit()

        result = await attempt_reschedule_with_anti_abuse(
            session,
            user=user,
            booking=booking,
            new_slot_id=new_slot.id,
            tz_name="Europe/Moscow",
        )

        refreshed_booking = await session.get(Booking, booking.id)
        assert result.outcome == "rescheduled"
        assert result.reschedule_result is not None
        assert result.reschedule_result.ok is True
        assert refreshed_booking is not None
        assert refreshed_booking.slot_id == new_slot.id
        assert refreshed_booking.reschedules_count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_reschedule_count_limit_triggers_approval() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        now = datetime.now(UTC)
        old_slot = Slot(start_at=now + timedelta(days=10), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=now + timedelta(days=20), status=SlotStatus.FREE)
        session.add_all([old_slot, new_slot])
        await session.flush()
        booking = Booking(
            client_id=user.id,
            slot_id=old_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            reschedules_count=2,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.commit()

        result = await attempt_reschedule_with_anti_abuse(
            session,
            user=user,
            booking=booking,
            new_slot_id=new_slot.id,
            tz_name="Europe/Moscow",
        )

        assert result.outcome == "too_many_reschedules"
        assert result.approval is not None
        assert result.approval.kind == ApprovalRequestKind.MANUAL_APPROVAL_REQUIRED

    await engine.dispose()


@pytest.mark.asyncio
async def test_choose_reschedule_slot_does_not_resend_existing_pending_approval(
    monkeypatch,
) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        now = datetime.now(UTC)
        old_slot = Slot(start_at=now + timedelta(days=5), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=now + timedelta(hours=20), status=SlotStatus.FREE)
        session.add_all([old_slot, new_slot])
        await session.flush()
        booking = Booking(
            client_id=user.id,
            slot_id=old_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.flush()

        approval = ApprovalRequest(
            client_id=user.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            requested_text="18 мая, 20:00",
            preferred_day=(now + timedelta(days=1)).date(),
            kind=ApprovalRequestKind.LATE_RESCHEDULE,
            related_booking_id=booking.id,
            status=ApprovalRequestStatus.PENDING,
        )
        session.add(approval)
        await session.commit()

        resend_calls: list[int] = []
        shown: dict[str, object] = {}

        async def fake_attempt_reschedule_with_anti_abuse(*args, **kwargs):
            del args, kwargs
            loaded = await session.get(ApprovalRequest, approval.id)
            return RescheduleAttemptResult(outcome="approval_existing", approval=loaded)

        async def fake_send_approval_card_to_admins(*, approval, **kwargs):
            del kwargs
            resend_calls.append(approval.id)

        async def fake_show_booking_card_message(
            message,
            *,
            booking_id,
            db_session,
            user,
            settings,
            edit,
            prefix_text=None,
        ) -> None:
            del message, booking_id, db_session, user, settings, edit
            shown["prefix_text"] = prefix_text

        monkeypatch.setattr(
            my_bookings_handler,
            "attempt_reschedule_with_anti_abuse",
            fake_attempt_reschedule_with_anti_abuse,
        )
        monkeypatch.setattr(approvals_handler, "send_approval_card_to_admins", fake_send_approval_card_to_admins)
        monkeypatch.setattr(
            my_bookings_handler,
            "show_booking_card_message",
            fake_show_booking_card_message,
        )

        callback = FakeCallback(
            f"my_bookings:reschedule_slot:{booking.id}:{new_slot.id}",
            message=FakeMessage(),
        )
        state = FakeState()

        await my_bookings_handler.choose_reschedule_slot(
            callback,
            state,
            db_session=session,
            user=user,
            settings=settings,
        )

        assert callback.answered is True
        assert resend_calls == []
        assert shown["prefix_text"] == my_bookings_handler.texts.APPROVAL_RESCHEDULE_SENT_TEXT

    await engine.dispose()


@pytest.mark.asyncio
async def test_choose_reschedule_slot_notifies_admins_on_direct_success(
    monkeypatch,
) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        now = datetime.now(UTC)
        old_slot = Slot(start_at=now + timedelta(days=5, hours=2), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=now + timedelta(days=8, hours=4), status=SlotStatus.FREE)
        session.add_all([old_slot, new_slot])
        await session.flush()
        booking = Booking(
            client_id=user.id,
            slot_id=old_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.commit()

        shown: dict[str, object] = {}
        admin_notifications: list[dict[str, object]] = []

        async def fake_show_booking_card_message(
            message,
            *,
            booking_id,
            db_session,
            user,
            settings,
            edit,
            prefix_text=None,
        ) -> None:
            del message, db_session, user, settings, edit
            shown["booking_id"] = booking_id
            shown["prefix_text"] = prefix_text

        async def fake_send_text_to_admins(bot, *, admin_tg_ids, text, reply_markup=None) -> None:
            del bot
            admin_notifications.append(
                {
                    "admin_tg_ids": admin_tg_ids,
                    "text": text,
                    "reply_markup": reply_markup,
                }
            )

        monkeypatch.setattr(
            my_bookings_handler,
            "show_booking_card_message",
            fake_show_booking_card_message,
        )
        monkeypatch.setattr(
            my_bookings_handler,
            "send_text_to_admins",
            fake_send_text_to_admins,
        )

        callback = FakeCallback(
            f"my_bookings:reschedule_slot:{booking.id}:{new_slot.id}",
            message=FakeMessage(),
        )
        state = FakeState()

        await my_bookings_handler.choose_reschedule_slot(
            callback,
            state,
            db_session=session,
            user=user,
            settings=settings,
        )

        assert callback.answered is True
        assert shown["booking_id"] == booking.id
        assert shown["prefix_text"] == my_bookings_handler.texts.MY_BOOKINGS_RESCHEDULED_TEXT
        assert len(admin_notifications) == 1
        assert admin_notifications[0]["admin_tg_ids"] == settings.admin_tg_id_set
        assert "Клиентка перенесла запись" in str(admin_notifications[0]["text"])
        assert user.display_name in str(admin_notifications[0]["text"])
        assert service.name in str(admin_notifications[0]["text"])
        assert admin_notifications[0]["reply_markup"] is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_cancel_cooldown_blocks_new_booking() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        new_slot = Slot(start_at=datetime.now(UTC) + timedelta(days=20), status=SlotStatus.FREE)
        session.add(new_slot)
        await session.commit()

        await RateLimitEventRepository(session).create(
            user_id=user.id,
            kind="cancel",
            metadata={"hours_before": 1.5},
            created_at=utcnow() - timedelta(minutes=5),
        )
        await session.commit()

        result = await attempt_booking_with_anti_abuse(
            session,
            user=user,
            slot_id=new_slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            tz_name="Europe/Moscow",
        )

        assert result.outcome == "cooldown"
        assert result.cooldown_minutes == 25
        assert result.confirm_result is None
        assert result.approval is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_second_recent_cancel_extends_cooldown_to_one_hour() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        new_slot = Slot(start_at=datetime.now(UTC) + timedelta(days=20), status=SlotStatus.FREE)
        session.add(new_slot)
        await session.commit()

        await RateLimitEventRepository(session).create(
            user_id=user.id,
            kind="cancel",
            metadata={"hours_before": 12},
            created_at=utcnow() - timedelta(days=7),
        )
        await RateLimitEventRepository(session).create(
            user_id=user.id,
            kind="cancel",
            metadata={"hours_before": 2},
            created_at=utcnow() - timedelta(minutes=5),
        )
        await session.commit()

        result = await attempt_booking_with_anti_abuse(
            session,
            user=user,
            slot_id=new_slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            tz_name="Europe/Moscow",
        )

        assert result.outcome == "cooldown"
        assert result.cooldown_minutes == 55
        assert result.confirm_result is None
        assert result.approval is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_completed_visit_resets_repeat_cancel_escalation() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        completed_slot = Slot(start_at=utcnow() - timedelta(days=3), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=utcnow() + timedelta(days=20), status=SlotStatus.FREE)
        session.add_all([completed_slot, new_slot])
        await session.flush()
        session.add(
            Booking(
                client_id=user.id,
                slot_id=completed_slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=2400,
                has_variable_price=False,
                status=BookingStatus.COMPLETED,
            )
        )
        await session.flush()

        await RateLimitEventRepository(session).create(
            user_id=user.id,
            kind="cancel",
            metadata={"hours_before": 4},
            created_at=utcnow() - timedelta(days=10),
        )
        await RateLimitEventRepository(session).create(
            user_id=user.id,
            kind="cancel",
            metadata={"hours_before": 2},
            created_at=utcnow() - timedelta(minutes=5),
        )
        await session.commit()

        result = await attempt_booking_with_anti_abuse(
            session,
            user=user,
            slot_id=new_slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            tz_name="Europe/Moscow",
        )

        assert result.outcome == "cooldown"
        assert result.cooldown_minutes == 25

    await engine.dispose()


@pytest.mark.asyncio
async def test_duplicate_phone_blocks_onboarding_phone_step() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        existing = User(
            tg_id=2001,
            display_name="Старый клиент",
            phone="+79991112233",
            is_admin=False,
            is_blocked=False,
        )
        new_user = User(
            tg_id=2002,
            display_name="Новый клиент",
            is_admin=False,
            is_blocked=False,
        )
        session.add_all([existing, new_user])
        await session.commit()

        message = FakeMessage("+7 999 111 22 33")
        state = FakeState()

        await booking_flow_handler.onboarding_phone_text(
            message,
            state,
            db_session=session,
            user=new_user,
            settings=build_settings(),
        )

        refreshed = await session.get(User, new_user.id)
        assert refreshed is not None
        assert refreshed.phone is None
        assert refreshed.duplicate_phone_flag is False
        assert message.answers
        assert message.answers[-1][0] == booking_flow_handler.texts.ONBOARDING_PHONE_DUPLICATE_TEXT

    await engine.dispose()


@pytest.mark.asyncio
async def test_show_confirm_step_requests_phone_only_before_final_confirmation() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=3001,
            display_name="Новый клиент",
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
            start_at=datetime.now(UTC) + timedelta(days=2),
            status=SlotStatus.FREE,
        )
        session.add_all([user, service, slot])
        await session.commit()

        state = FakeState()
        await state.update_data(
            base_service_id=service.id,
            selected_addons=[],
            slot_id=slot.id,
            design_photos=[],
            design_comment=None,
            payment_method="transfer",
        )
        message = FakeMessage()

        await booking_flow_handler.show_confirm_step(
            message,
            db_session=session,
            state=state,
            settings=settings,
            user=user,
        )

        assert state.state == booking_flow_handler.Onboarding.input_phone
        assert message.answers
        assert message.answers[-1][0] == booking_flow_handler.texts.ONBOARDING_PHONE_TEXT

    await engine.dispose()


@pytest.mark.asyncio
async def test_continue_after_onboarding_returns_to_confirm_when_requested(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=3002,
            display_name="Новый клиент",
            phone="+79990000002",
            is_admin=False,
            is_blocked=False,
        )
        session.add(user)
        await session.commit()

        state = FakeState()
        await state.update_data(onboarding_resume_target="confirm")
        message = FakeMessage()
        calls: list[str] = []

        async def fake_show_confirm_step(*args, **kwargs) -> None:
            del args, kwargs
            calls.append("confirm")

        monkeypatch.setattr(booking_flow_handler, "show_confirm_step", fake_show_confirm_step)

        await booking_flow_handler.continue_after_onboarding(
            message,
            db_session=session,
            state=state,
            settings=settings,
            user=user,
        )

        assert calls == ["confirm"]
        assert state.data.get("onboarding_resume_target") is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_ask_master_daily_limit_shows_honest_limit_text() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, _ = await create_base_entities(session)
        events = RateLimitEventRepository(session)
        for _index in range(3):
            await events.create(
                user_id=user.id,
                kind="ask_master",
                metadata={"blocked": False},
                created_at=utcnow() - timedelta(hours=1),
            )
        await session.commit()

        message = FakeMessage("Можно ли такой дизайн?")
        state = FakeState()
        await state.set_state(ask_master_handler.AskingMaster.input_message)

        await ask_master_handler.submit_question_to_master(
            message,
            state,
            db_session=session,
            user=user,
            settings=settings,
        )

        approval_count = await session.scalar(select(func.count(ApprovalRequest.id)))
        assert approval_count == 0
        assert message.answers
        assert message.answers[-1][0] == ask_master_handler.texts.ASK_MASTER_LIMIT_TEXT

    await engine.dispose()


@pytest.mark.asyncio
async def test_proxy_message_rate_limit_shows_honest_limit_text(monkeypatch) -> None:
    forwarded_messages: list[str] = []

    async def fake_send_text_to_admins(bot, *, admin_tg_ids, text, reply_markup=None) -> None:
        del bot, admin_tg_ids, reply_markup
        forwarded_messages.append(text)

    monkeypatch.setattr(proxy_chat_handler, "send_text_to_admins", fake_send_text_to_admins)

    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, _ = await create_base_entities(session)
        approval = ApprovalRequest(
            client=user,
            kind=ApprovalRequestKind.QUESTION,
            status=ApprovalRequestStatus.PENDING,
            requested_text="Есть вопрос",
        )
        session.add(approval)
        await session.flush()

        events = RateLimitEventRepository(session)
        for _index in range(5):
            await events.create(
                user_id=user.id,
                kind="proxy_message",
                metadata={"blocked": False, "approval_id": approval.id},
                created_at=utcnow() - timedelta(minutes=10),
            )
        await session.commit()

        message = FakeMessage("Апдейт по вопросу")
        state = FakeState()
        await state.update_data(proxy_approval_id=approval.id)

        await proxy_chat_handler.submit_client_proxy_reply(
            message,
            state,
            db_session=session,
            user=user,
            settings=settings,
        )

        assert forwarded_messages == []
        assert message.answers
        assert message.answers[-1][0] == proxy_chat_handler.texts.PROXY_MESSAGE_LIMIT_TEXT

    await engine.dispose()


@pytest.mark.asyncio
async def test_blocked_user_booking_attempt_returns_blocked_outcome() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        user.is_blocked = True
        slot = Slot(start_at=datetime.now(UTC) + timedelta(days=5), status=SlotStatus.FREE)
        session.add(slot)
        await session.commit()

        result = await attempt_booking_with_anti_abuse(
            session,
            user=user,
            slot_id=slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            tz_name="Europe/Moscow",
        )

        assert result.outcome == "blocked"
        assert result.confirm_result is None
        assert result.approval is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_shadow_banned_user_booking_is_silent_noop(monkeypatch) -> None:
    success_calls: list[tuple[str, str]] = []
    admin_notifications: list[str] = []

    async def fake_send_booking_success_message(
        message,
        *,
        db_session,
        user,
        settings,
        start_at,
        base_service_name,
        payment_method=None,
        replace_current=False,
    ):
        del message, db_session, settings, start_at, payment_method, replace_current
        success_calls.append((user.display_name, base_service_name))

    async def fake_send_text_to_admins(bot, *, admin_tg_ids, text, reply_markup=None) -> None:
        del bot, admin_tg_ids, reply_markup
        admin_notifications.append(text)

    async def fake_safe_delete_message(message) -> None:
        del message

    monkeypatch.setattr(
        booking_flow_handler,
        "send_booking_success_message",
        fake_send_booking_success_message,
    )
    monkeypatch.setattr(booking_flow_handler, "send_text_to_admins", fake_send_text_to_admins)
    monkeypatch.setattr(booking_flow_handler, "safe_delete_message", fake_safe_delete_message)

    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        user.is_shadow_banned = True
        slot = Slot(start_at=datetime.now(UTC) + timedelta(days=5), status=SlotStatus.FREE)
        session.add(slot)
        await session.commit()

        state = FakeState()
        await state.update_data(
            slot_id=slot.id,
            base_service_id=service.id,
            selected_addons=[],
            design_photos=[],
            design_comment=None,
        )
        callback = FakeCallback("booking:confirm")

        await booking_flow_handler.finalize_booking(
            callback,
            state,
            db_session=session,
            user=user,
            settings=settings,
        )

        booking_count = await session.scalar(select(func.count(Booking.id)))
        assert booking_count == 0
        assert success_calls == [(user.display_name, service.name)]
        assert admin_notifications == []

    await engine.dispose()


def test_client_never_sees_rule_wording() -> None:
    banned = {
        "давно",
        "недавно",
        "17 дней",
        "2.5 недели",
        "rate-limit",
        "strike",
        "лимит",
        "ограничение",
    }
    texts_to_check = [
        booking_flow_handler.texts.BOOKING_RETRY_LATER_TEXT,
        booking_flow_handler.texts.BOOKING_PENDING_APPROVALS_LIMIT_TEXT,
        ask_master_handler.texts.ASK_MASTER_SENT_TEXT,
        ask_master_handler.texts.ASK_MASTER_LIMIT_TEXT,
        proxy_chat_handler.texts.PROXY_REPLY_SENT_TEXT,
        proxy_chat_handler.texts.PROXY_MESSAGE_LIMIT_TEXT,
    ]
    combined = "\n".join(texts_to_check).casefold()
    for word in banned:
        assert word not in combined


@pytest.mark.asyncio
async def test_admin_no_show_increments_strikes_double(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        user.strikes = 2
        slot = Slot(start_at=datetime.now(UTC) - timedelta(hours=1), status=SlotStatus.BOOKED)
        session.add(slot)
        await session.flush()
        booking = Booking(
            client_id=user.id,
            slot_id=slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.commit()

        callback = FakeCallback(f"admin_schedule:no_show:{slot.id}:page:0")
        state = FakeState()
        notified: list[tuple[int, str]] = []

        async def fake_send_text_to_user(_bot, *, tg_id: int, text: str, reply_markup=None) -> None:
            assert reply_markup is None
            notified.append((tg_id, text))

        monkeypatch.setattr(schedule_handler, "send_text_to_user", fake_send_text_to_user)

        await schedule_handler.schedule_mark_no_show(
            callback,
            state,
            db_session=session,
            settings=settings,
        )

        refreshed_booking = await session.get(Booking, booking.id)
        refreshed_user = await session.get(User, user.id)
        assert refreshed_booking is not None
        assert refreshed_user is not None
        assert refreshed_booking.status == BookingStatus.NO_SHOW
        assert refreshed_user.strikes == 4
        assert refreshed_user.requires_manual_approval is True
        assert callback.message.edits
        assert notified
        assert notified[0][0] == user.tg_id
        assert "ручное подтверждение" in notified[0][1]

    await engine.dispose()


@pytest.mark.asyncio
async def test_rate_limit_alert_is_aggregated(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        users = [
            User(
                tg_id=3000 + index,
                tg_username=f"user{index}",
                display_name=f"Клиент {index}",
                is_admin=False,
                is_blocked=False,
            )
            for index in range(3)
        ]
        session.add_all(users)
        await session.flush()
        events = RateLimitEventRepository(session)
        for user in users:
            await events.create(
                user_id=user.id,
                kind="proxy_message",
                metadata={"blocked": True},
                created_at=utcnow() - timedelta(minutes=10),
            )
        await session.commit()

    monkeypatch.setattr(
        anti_abuse_alerts, "session_scope", lambda settings: make_session_scope(session_factory)
    )

    bot = FakeBot()
    await anti_abuse_alerts.send_rate_limit_alerts(bot, settings)

    assert len(bot.sent_messages) == 1
    assert "RATE-LIMIT ПРЕВЫШЕН" in str(bot.sent_messages[0]["text"])
    assert "@user0" in str(bot.sent_messages[0]["text"])

    await engine.dispose()
