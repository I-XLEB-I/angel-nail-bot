from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import approvals as approvals_handler
from src.bot.handlers.client import offer_confirm as offer_confirm_handler
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
from src.services import booking_completion as booking_completion_service
from src.services.aftercare import REPAIR_PAID_SENTINEL


class FakeChat:
    def __init__(self, chat_id: int = 700) -> None:
        self.id = chat_id


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object | None]] = []

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        reply_markup=None,
        parse_mode=None,
    ):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode,
        }
        self.sent_messages.append(payload)
        return type("SentMessage", (), {"chat": FakeChat(chat_id), "message_id": 100})()


class FakeMessage:
    def __init__(self, *, bot: FakeBot | None = None) -> None:
        self.bot = bot or FakeBot()
        self.chat = FakeChat()
        self.message_id = 55
        self.answers: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None):
        self.answers.append((text, reply_markup))
        return type("AnsweredMessage", (), {"chat": self.chat, "message_id": 56})()


class FakeCallback:
    def __init__(
        self,
        data: str,
        *,
        message: FakeMessage | None = None,
        bot: FakeBot | None = None,
    ):
        self.data = data
        self.bot = bot or FakeBot()
        self.message = message or FakeMessage(bot=self.bot)
        self.answered: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def answer(self, *args, **kwargs) -> None:
        self.answered.append((args, kwargs))


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="9001",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


async def setup_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, session_factory


def build_base_service() -> Service:
    return Service(
        name="Маникюр",
        price=2400,
        price_variable=False,
        duration_min=120,
        kind=ServiceKind.BASE,
        is_active=True,
        display_order=0,
    )


@pytest.mark.asyncio
async def test_offer_slot_marks_request_offered_and_sends_client_keyboard() -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()

    async with session_factory() as session:
        user = User(tg_id=5010, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = build_base_service()
        slot = Slot(start_at=datetime.now(UTC) + timedelta(days=1), status=SlotStatus.FREE)
        approval = ApprovalRequest(
            client=user,
            base_service=service,
            requested_text="Завтра вечером",
            kind=ApprovalRequestKind.NEW_BOOKING,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        session.add_all([user, service, slot, approval])
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(
            f"approval:offer_slot:{approval.id}:{slot.id}",
            message=FakeMessage(bot=bot),
            bot=bot,
        )

        await approvals_handler.offer_slot_to_client(
            callback,
            state=None,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.OFFERED
        assert refreshed.offered_slot_id == slot.id
        assert any(message["chat_id"] == user.tg_id for message in bot.sent_messages)
        client_message = next(
            message for message in bot.sent_messages if message["chat_id"] == user.tg_id
        )
        assert client_message["reply_markup"] is not None
        assert (
            callback.message.answers[-1][0]
            == approvals_handler.texts.APPROVAL_TIME_OFFER_SENT_ADMIN_TEXT
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_accept_offer_creates_booking_and_approves_request() -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()

    async with session_factory() as session:
        user = User(tg_id=5011, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = build_base_service()
        slot = Slot(start_at=datetime.now(UTC) + timedelta(days=1), status=SlotStatus.FREE)
        approval = ApprovalRequest(
            client=user,
            base_service=service,
            requested_text="24.04 18:00",
            kind=ApprovalRequestKind.NEW_BOOKING,
            status=ApprovalRequestStatus.OFFERED,
            addons=[],
            design_photos=[],
            offered_slot=slot,
        )
        session.add_all([user, service, slot, approval])
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(
            f"approval:accept_offer:{approval.id}",
            message=FakeMessage(bot=bot),
            bot=bot,
        )

        await offer_confirm_handler.accept_time_offer(
            callback,
            db_session=session,
            user=user,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.APPROVED
        assert refreshed.offered_slot_id is None

        bookings = list((await session.execute(select(Booking))).scalars())
        assert len(bookings) == 1
        assert bookings[0].client_id == user.id
        assert bookings[0].slot_id == slot.id
        assert callback.message.answers
        client_text, client_markup = callback.message.answers[-1]
        assert "Записала" in client_text
        assert client_markup is not None
        callback_data = [
            button.callback_data
            for row in client_markup.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert "client_menu:my_bookings" in callback_data
        assert "client:to_menu" in callback_data
        assert any(message["chat_id"] == 9001 for message in bot.sent_messages)

    await engine.dispose()


@pytest.mark.asyncio
async def test_accept_offer_reschedules_related_booking() -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()

    async with session_factory() as session:
        user = User(tg_id=5012, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = build_base_service()
        old_slot = Slot(start_at=datetime.now(UTC) + timedelta(days=1), status=SlotStatus.BOOKED)
        new_slot = Slot(start_at=datetime.now(UTC) + timedelta(days=2), status=SlotStatus.FREE)
        session.add_all([user, service, old_slot, new_slot])
        await session.flush()

        booking = Booking(
            client_id=user.id,
            slot_id=old_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=service.price,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.flush()

        approval = ApprovalRequest(
            client_id=user.id,
            requested_text="Можно перенести?",
            kind=ApprovalRequestKind.RESCHEDULE,
            status=ApprovalRequestStatus.OFFERED,
            addons=[],
            design_photos=[],
            related_booking_id=booking.id,
            offered_slot_id=new_slot.id,
        )
        session.add(approval)
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(
            f"approval:accept_offer:{approval.id}",
            message=FakeMessage(bot=bot),
            bot=bot,
        )

        await offer_confirm_handler.accept_time_offer(
            callback,
            db_session=session,
            user=user,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        refreshed_booking = await session.get(Booking, booking.id)
        refreshed_old_slot = await session.get(Slot, old_slot.id)
        refreshed_new_slot = await session.get(Slot, new_slot.id)

        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.APPROVED
        assert refreshed_booking is not None
        assert refreshed_booking.slot_id == new_slot.id
        assert refreshed_booking.reschedules_count == 1
        assert refreshed_old_slot is not None and refreshed_old_slot.status == SlotStatus.FREE
        assert refreshed_new_slot is not None and refreshed_new_slot.status == SlotStatus.BOOKED
        assert callback.message.answers
        _, client_markup = callback.message.answers[-1]
        assert client_markup is not None
        callback_data = [
            button.callback_data
            for row in client_markup.inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert "client_menu:my_bookings" in callback_data
        assert "client:to_menu" in callback_data

    await engine.dispose()


@pytest.mark.asyncio
async def test_accept_repair_offer_with_custom_start_creates_warranty_booking(
    monkeypatch,
) -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()

    monkeypatch.setattr(
        booking_completion_service,
        "create_booking_event",
        lambda *args, **kwargs: None,
    )

    async with session_factory() as session:
        user = User(tg_id=5013, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = build_base_service()
        source_slot = Slot(
            start_at=datetime.now(UTC) - timedelta(days=2),
            status=SlotStatus.BOOKED,
        )
        session.add_all([user, service, source_slot])
        await session.flush()

        source_booking = Booking(
            client_id=user.id,
            slot_id=source_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=service.price,
            has_variable_price=False,
            status=BookingStatus.COMPLETED,
        )
        session.add(source_booking)
        await session.flush()

        approval = ApprovalRequest(
            client_id=user.id,
            base_service_id=service.id,
            requested_text="Ремонт: Скол",
            kind=ApprovalRequestKind.REPAIR_REQUEST,
            status=ApprovalRequestStatus.OFFERED,
            addons=[],
            design_photos=["file_1"],
            related_booking_id=source_booking.id,
            offered_start_at=datetime.now(UTC) + timedelta(days=1, hours=3),
            admin_response_text="__repair_warranty__",
        )
        session.add(approval)
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(
            f"approval:accept_offer:{approval.id}",
            message=FakeMessage(bot=bot),
            bot=bot,
        )

        await offer_confirm_handler.accept_time_offer(
            callback,
            db_session=session,
            user=user,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.APPROVED
        assert refreshed.offered_start_at is None

        bookings = list((await session.execute(select(Booking).order_by(Booking.id))).scalars())
        assert len(bookings) == 2
        warranty_booking = bookings[-1]
        assert warranty_booking.client_id == user.id
        assert warranty_booking.fixed_price == 0
        assert warranty_booking.status == BookingStatus.CONFIRMED

        services = list((await session.execute(select(Service).order_by(Service.id))).scalars())
        assert any(service.name == "Гарантийный ремонт" for service in services)

    await engine.dispose()


@pytest.mark.asyncio
async def test_accept_paid_repair_offer_with_custom_start_creates_paid_repair_booking(
    monkeypatch,
) -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()

    monkeypatch.setattr(
        booking_completion_service,
        "create_booking_event",
        lambda *args, **kwargs: None,
    )

    async with session_factory() as session:
        user = User(tg_id=5014, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = build_base_service()
        source_slot = Slot(
            start_at=datetime.now(UTC) - timedelta(days=2),
            status=SlotStatus.BOOKED,
        )
        session.add_all([user, service, source_slot])
        await session.flush()

        source_booking = Booking(
            client_id=user.id,
            slot_id=source_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=service.price,
            has_variable_price=False,
            status=BookingStatus.COMPLETED,
        )
        session.add(source_booking)
        await session.flush()

        approval = ApprovalRequest(
            client_id=user.id,
            base_service_id=service.id,
            requested_text="Ремонт: Трещина",
            kind=ApprovalRequestKind.REPAIR_REQUEST,
            status=ApprovalRequestStatus.OFFERED,
            addons=[],
            design_photos=["file_1"],
            related_booking_id=source_booking.id,
            offered_start_at=datetime.now(UTC) + timedelta(days=1, hours=2),
            admin_response_text=REPAIR_PAID_SENTINEL,
        )
        session.add(approval)
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(
            f"approval:accept_offer:{approval.id}",
            message=FakeMessage(bot=bot),
            bot=bot,
        )

        await offer_confirm_handler.accept_time_offer(
            callback,
            db_session=session,
            user=user,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.APPROVED
        assert refreshed.offered_start_at is None

        bookings = list((await session.execute(select(Booking).order_by(Booking.id))).scalars())
        assert len(bookings) == 2
        paid_repair_booking = bookings[-1]
        assert paid_repair_booking.client_id == user.id
        assert paid_repair_booking.fixed_price == 0
        assert paid_repair_booking.has_variable_price is True
        assert paid_repair_booking.status == BookingStatus.CONFIRMED

        services = list((await session.execute(select(Service).order_by(Service.id))).scalars())
        assert any(service.name == "Платный ремонт" for service in services)

    await engine.dispose()


@pytest.mark.asyncio
async def test_decline_offer_returns_request_to_pending() -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()

    async with session_factory() as session:
        user = User(tg_id=5013, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = build_base_service()
        slot = Slot(start_at=datetime.now(UTC) + timedelta(days=1), status=SlotStatus.FREE)
        approval = ApprovalRequest(
            client=user,
            base_service=service,
            requested_text="Завтра вечером",
            kind=ApprovalRequestKind.NEW_BOOKING,
            status=ApprovalRequestStatus.OFFERED,
            addons=[],
            design_photos=[],
            offered_slot=slot,
        )
        session.add_all([user, service, slot, approval])
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(
            f"approval:decline_offer:{approval.id}",
            message=FakeMessage(bot=bot),
            bot=bot,
        )

        await offer_confirm_handler.decline_time_offer(
            callback,
            db_session=session,
            user=user,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.PENDING
        assert refreshed.offered_slot_id is None
        assert callback.message.answers[-1][1] is not None
        assert any(message["chat_id"] == 9001 for message in bot.sent_messages)

    await engine.dispose()


@pytest.mark.asyncio
async def test_accept_offer_conflict_returns_request_to_pending() -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()

    async with session_factory() as session:
        user = User(tg_id=5014, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = build_base_service()
        taken_slot = Slot(start_at=datetime.now(UTC) + timedelta(days=1), status=SlotStatus.BOOKED)
        approval = ApprovalRequest(
            client=user,
            base_service=service,
            requested_text="Завтра вечером",
            kind=ApprovalRequestKind.NEW_BOOKING,
            status=ApprovalRequestStatus.OFFERED,
            addons=[],
            design_photos=[],
            offered_slot=taken_slot,
        )
        session.add_all([user, service, taken_slot, approval])
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(
            f"approval:accept_offer:{approval.id}",
            message=FakeMessage(bot=bot),
            bot=bot,
        )

        await offer_confirm_handler.accept_time_offer(
            callback,
            db_session=session,
            user=user,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        bookings = list((await session.execute(select(Booking))).scalars())
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.PENDING
        assert refreshed.offered_slot_id is None
        assert bookings == []
        assert (
            callback.message.answers[-1][0]
            == offer_confirm_handler.texts.APPROVAL_OFFER_EXPIRED_TEXT
        )
        assert any(message["chat_id"] == 9001 for message in bot.sent_messages)

    await engine.dispose()
