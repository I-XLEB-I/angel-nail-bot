from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import approvals as approvals_handler
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
)


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def clear(self) -> None:
        self.data.clear()

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[tuple[str, object | None]] = []
        self.chat = type("Chat", (), {"id": 900})()
        self.message_id = 55

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None, **kwargs) -> None:
        self.messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )


class FakeCallback:
    def __init__(self, data: str, *, bot: FakeBot, message: FakeMessage | None = None) -> None:
        self.data = data
        self.bot = bot
        self.message = message or FakeMessage()
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
        GCAL_ENABLED="true",
        GCAL_CALENDAR_ID="calendar-id",
        GCAL_CREDENTIALS_PATH="./secrets/gcal_service_account.json",
    )


@pytest.mark.asyncio
async def test_finish_cancellation_releases_slot_and_clears_calendar_link(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=1001,
            tg_username="daridts",
            display_name="Дарина",
            phone="+79991234567",
            is_admin=False,
            is_blocked=False,
        )
        service = Service(
            name="Покрытие гель-лак",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
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
            status=BookingStatus.CONFIRMED,
            gcal_event_id="event-123",
        )
        session.add_all([user, service, slot, booking])
        await session.commit()

        deleted_event_ids: list[str] = []
        admin_notifications: list[str] = []

        monkeypatch.setattr(
            my_bookings_handler,
            "delete_booking_event",
            lambda _settings, *, event_id: deleted_event_ids.append(event_id),
        )

        async def fake_send_text_to_admins(_bot, *, admin_tg_ids, text, reply_markup=None) -> None:
            del _bot, admin_tg_ids, reply_markup
            admin_notifications.append(text)

        monkeypatch.setattr(my_bookings_handler, "send_text_to_admins", fake_send_text_to_admins)

        message = FakeMessage()
        state = FakeState()
        bot = FakeBot()

        await my_bookings_handler.finish_cancellation(
            message=message,
            state=state,
            booking_id=booking.id,
            reason_code="other",
            reason_text="Нужно срочно уехать",
            db_session=session,
            user=user,
            settings=settings,
            edit=False,
            bot=bot,
        )

        refreshed_booking = await session.get(Booking, booking.id)
        refreshed_slot = await session.get(Slot, slot.id)

        assert refreshed_booking is not None
        assert refreshed_slot is not None
        assert refreshed_booking.status == BookingStatus.CANCELLED_BY_CLIENT
        assert refreshed_booking.gcal_event_id is None
        assert refreshed_booking.cancel_reason_text == "Нужно срочно уехать"
        assert refreshed_slot.status == SlotStatus.FREE
        assert deleted_event_ids == ["event-123"]
        assert len(admin_notifications) == 1
        assert "Отмена записи" in admin_notifications[0]
        assert message.answers

    await engine.dispose()


@pytest.mark.asyncio
async def test_decline_with_template_reason_updates_status_and_notifies_client() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=2001,
            tg_username="client_name",
            display_name="Аня",
            is_admin=False,
            is_blocked=False,
        )
        approval = ApprovalRequest(
            client=user,
            requested_text="Можно в четверг?",
            kind=ApprovalRequestKind.QUESTION,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        session.add_all([user, approval])
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(
            f"approval:decline_reason:{approval.id}:busy",
            bot=bot,
        )

        await approvals_handler.decline_with_template_reason(
            callback,
            db_session=session,
            is_admin=True,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.PENDING
        assert refreshed.admin_response_text is None
        assert bot.messages
        assert "Точно отказать клиентке" in str(bot.messages[0]["text"])

        commit_callback = FakeCallback(
            f"approval:decline_commit:{approval.id}:busy",
            bot=bot,
        )
        await approvals_handler.decline_with_template_reason_commit(
            commit_callback,
            db_session=session,
            is_admin=True,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.DECLINED
        assert refreshed.admin_response_text == "Уже занято"
        client_messages = [message for message in bot.messages if message["chat_id"] == user.tg_id]
        assert len(client_messages) == 1
        assert "Причина: Уже занято" in str(client_messages[0]["text"])

    await engine.dispose()


@pytest.mark.asyncio
async def test_decline_with_custom_reason_commit_updates_status_and_notifies_client() -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=2002,
            tg_username="client_name_2",
            display_name="Лена",
            is_admin=False,
            is_blocked=False,
        )
        approval = ApprovalRequest(
            client=user,
            requested_text="Можно в субботу?",
            kind=ApprovalRequestKind.QUESTION,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        session.add_all([user, approval])
        await session.commit()

        bot = FakeBot()
        callback = FakeCallback(
            f"approval:decline_custom_commit:{approval.id}",
            bot=bot,
        )
        state = FakeState({"decline_pending_reason": "На эту дату не смогу"})

        await approvals_handler.decline_with_custom_reason_commit(
            callback,
            state,
            db_session=session,
            is_admin=True,
            settings=settings,
        )

        refreshed = await session.get(ApprovalRequest, approval.id)
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.DECLINED
        assert refreshed.admin_response_text == "На эту дату не смогу"
        assert len(bot.messages) == 1
        assert bot.messages[0]["chat_id"] == user.tg_id
        assert "Причина: На эту дату не смогу" in str(bot.messages[0]["text"])

    await engine.dispose()


@pytest.mark.asyncio
async def test_resolve_with_slot_reschedules_related_booking_and_updates_calendar(
    monkeypatch,
) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=3001,
            tg_username="daridts",
            display_name="Дарина",
            phone="+79991234567",
            is_admin=False,
            is_blocked=False,
        )
        service = Service(
            name="Покрытие гель-лак",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        old_slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=2),
            status=SlotStatus.BOOKED,
        )
        new_slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=3),
            status=SlotStatus.FREE,
        )
        booking = Booking(
            client=user,
            slot=old_slot,
            base_service=service,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
            gcal_event_id="event-456",
        )
        approval = ApprovalRequest(
            client=user,
            requested_text="Перенесите, пожалуйста, на другое время",
            kind=ApprovalRequestKind.RESCHEDULE,
            related_booking=booking,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
            preferred_day=date.today() + timedelta(days=3),
        )
        session.add_all([user, service, old_slot, new_slot, booking, approval])
        await session.commit()

        updated_calendar_payloads: list[tuple[str, str]] = []

        monkeypatch.setattr(
            approvals_handler,
            "update_booking_event",
            lambda _settings, *, event_id, booking: updated_calendar_payloads.append(
                (event_id, booking.base_service_name)
            ),
        )

        async def fake_build_address_text(_session) -> str:
            return "Адрес"

        monkeypatch.setattr(approvals_handler, "build_address_text", fake_build_address_text)

        bot = FakeBot()
        callback = FakeCallback(
            data="approval:book_slot:ignored",
            bot=bot,
        )

        loaded_approval = await approvals_handler.ApprovalRequestRepository(session).get_by_id(
            approval.id
        )
        assert loaded_approval is not None

        await approvals_handler.resolve_with_slot(
            callback=callback,
            approval=loaded_approval,
            slot_id=new_slot.id,
            db_session=session,
            settings=settings,
        )

        refreshed_booking = await session.get(Booking, booking.id)
        refreshed_old_slot = await session.get(Slot, old_slot.id)
        refreshed_new_slot = await session.get(Slot, new_slot.id)
        refreshed_approval = await session.get(ApprovalRequest, approval.id)

        assert refreshed_booking is not None
        assert refreshed_old_slot is not None
        assert refreshed_new_slot is not None
        assert refreshed_approval is not None
        assert refreshed_booking.slot_id == new_slot.id
        assert refreshed_old_slot.status == SlotStatus.FREE
        assert refreshed_new_slot.status == SlotStatus.BOOKED
        assert refreshed_approval.status == ApprovalRequestStatus.APPROVED
        assert updated_calendar_payloads == [("event-456", "Покрытие гель-лак")]
        assert len(bot.messages) == 1
        assert "Записала тебя" in str(bot.messages[0]["text"])
        assert bot.messages[0]["reply_markup"] is not None
        callback_data = [
            button.callback_data
            for row in bot.messages[0]["reply_markup"].inline_keyboard
            for button in row
            if button.callback_data is not None
        ]
        assert "client_menu:my_bookings" in callback_data
        assert "client:to_menu" in callback_data

    await engine.dispose()
