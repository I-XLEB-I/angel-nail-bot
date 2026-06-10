from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.client import reminders as reminders_handler
from src.bot.handlers.client.address import build_address_copy_text
from src.config import Settings
from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, SlotStatus, User
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.morning_summary_deliveries import (
    MorningSummaryDeliveryRepository,
)
from src.db.repositories.reminder_admin_alert_deliveries import (
    ReminderAdminAlertDeliveryRepository,
)
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services import reminders


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []
        self.edits: list[dict[str, object]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None):
        payload = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
        }
        self.messages.append(payload)
        return type(
            "SentMessage",
            (),
            {
                "chat": type("Chat", (), {"id": chat_id})(),
                "message_id": len(self.messages) + 100,
            },
        )()

    async def edit_message_text(
        self,
        *,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup=None,
    ) -> None:
        self.edits.append(
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "reply_markup": reply_markup,
            }
        )


class FakeMessage:
    def __init__(self, *, bot: FakeBot | None = None) -> None:
        self.text = None
        self.bot = bot or FakeBot()
        self.chat = type("Chat", (), {"id": 500})()
        self.message_id = 77
        self.edits: list[tuple[str, object | None]] = []
        self.answers: list[tuple[str, object | None]] = []

    async def edit_text(self, text: str, reply_markup=None) -> None:
        self.edits.append((text, reply_markup))

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))


class FakeCallback:
    def __init__(
        self,
        data: str,
        *,
        message: FakeMessage | None = None,
        bot: FakeBot | None = None,
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
        FEATURE_REPEAT_PROMPT="true",
        FEATURE_POSTVISIT_FEEDBACK="true",
        FEATURE_REMINDER_2H="true",
    )


@asynccontextmanager
async def make_session_scope(session_factory):
    async with session_factory() as session:
        yield session


async def seed_booking(
    session_factory,
    *,
    start_at: datetime,
    status: BookingStatus = BookingStatus.CONFIRMED,
) -> int:
    async with session_factory() as session:
        user = User(
            tg_id=5001,
            display_name="Аня",
            phone="+79991234567",
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
        slot = Slot(start_at=start_at, status=SlotStatus.BOOKED)
        booking = Booking(
            client=user,
            slot=slot,
            base_service=service,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=status,
        )
        session.add_all([user, service, slot, booking])
        await session.commit()
        return booking.id


@pytest.mark.asyncio
async def test_send_due_reminders_marks_24h_sent(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) + timedelta(hours=24),
    )

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )

    async def fake_build_address_text(_session) -> str:
        return "Адрес"

    monkeypatch.setattr(reminders, "build_address_text", fake_build_address_text)
    bot = FakeBot()

    await reminders.send_due_reminders(bot, settings)

    assert len(bot.messages) == 1
    assert "напоминаю о записи" in str(bot.messages[0]["text"]).lower()
    assert "всё в силе?" in str(bot.messages[0]["text"]).lower()
    assert build_address_copy_text() in str(bot.messages[0]["text"])

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.reminder_24h_sent_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_build_24h_reminder_text_appends_late_policy_when_template_lacks_it() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) + timedelta(hours=24),
    )

    async with session_factory() as session:
        await TemplateRepository(session).upsert(
            key="reminder_24h",
            content="Напоминаю о записи: {date} {time}\n{service}",
        )
        await session.commit()

        booking = await BookingRepository(session).get_by_id(booking_id)
        assert booking is not None

        text = await reminders.build_24h_reminder_text(
            booking,
            template_repository=TemplateRepository(session),
            address_text="Очаковское шоссе, 5к3",
            tz_name="Europe/Moscow",
        )

    assert "15 минут" in text
    assert "запись может отмениться" in text.lower()
    assert text.count("15 минут") == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_build_2h_reminder_text_appends_late_policy_when_template_lacks_it() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) + timedelta(hours=2),
    )

    async with session_factory() as session:
        await TemplateRepository(session).upsert(
            key="reminder_2h",
            content="Сегодня в {time} жду тебя 🤍",
        )
        await session.commit()

        booking = await BookingRepository(session).get_by_id(booking_id)
        assert booking is not None

        text = await reminders.build_2h_reminder_text(
            booking,
            template_repository=TemplateRepository(session),
            tz_name="Europe/Moscow",
        )

    assert "15 минут" in text
    assert "запись может отмениться" in text.lower()
    assert text.count("15 минут") == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_unconfirmed_alerts_pings_master_for_24h_silence(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    booking_id = await seed_booking(
        session_factory,
        start_at=now + timedelta(hours=24),
    )
    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_24h_sent_at = now - timedelta(minutes=25)
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_unconfirmed_alerts(bot, settings)

    assert len(bot.messages) == 1
    assert "не нажала подтверждение за сутки" in str(bot.messages[0]["text"]).lower()
    assert "+79991234567" in str(bot.messages[0]["text"])
    keyboard = bot.messages[0]["reply_markup"]
    assert keyboard is not None
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "✕ Считать отменой" not in labels
    urls = [
        button.url
        for row in keyboard.inline_keyboard
        for button in row
        if getattr(button, "url", None) is not None
    ]
    assert urls == []

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.reminder_24h_unconfirmed_alert_sent_at is not None

    await reminders.send_unconfirmed_alerts(bot, settings)
    assert len(bot.messages) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_unconfirmed_alerts_skips_24h_warning_after_client_confirmation(
    monkeypatch,
) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    booking_id = await seed_booking(
        session_factory,
        start_at=now + timedelta(hours=24),
    )
    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_24h_sent_at = now - timedelta(minutes=25)
        booking.reminder_24h_confirmed_at = now - timedelta(minutes=5)
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_unconfirmed_alerts(bot, settings)

    assert bot.messages == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_mark_completed_updates_old_confirmed_bookings(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) - timedelta(hours=2),
    )

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    await reminders.mark_completed(FakeBot(), settings)

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.status == BookingStatus.COMPLETED

    await engine.dispose()


@pytest.mark.asyncio
async def test_mark_completed_skips_unresolved_unconfirmed_booking(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) - timedelta(hours=2),
    )

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_2h_sent_at = datetime.now(UTC) - timedelta(hours=3)
        booking.reminder_2h_unconfirmed_alert_sent_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    await reminders.mark_completed(FakeBot(), settings)

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.status == BookingStatus.CONFIRMED

    await engine.dispose()


@pytest.mark.asyncio
async def test_mark_completed_skips_unresolved_even_if_24h_was_confirmed(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) - timedelta(hours=2),
    )

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_24h_confirmed_at = datetime.now(UTC) - timedelta(days=1)
        booking.reminder_2h_sent_at = datetime.now(UTC) - timedelta(hours=3)
        booking.reminder_2h_unconfirmed_alert_sent_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    await reminders.mark_completed(FakeBot(), settings)

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.status == BookingStatus.CONFIRMED

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_postvisit_marks_timestamp(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) - timedelta(hours=4),
        status=BookingStatus.COMPLETED,
    )
    async with session_factory() as session:
        await SettingRepository(session).upsert(key="postvisit_delay_hours", value="2")
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_postvisit(bot, settings)

    assert len(bot.messages) == 1
    assert "как всё прошло" in str(bot.messages[0]["text"]).lower()

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.postvisit_sent_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_due_reminders_still_sends_2h_after_24h_confirmation(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) + timedelta(hours=2),
    )
    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_24h_confirmed_at = datetime.now(UTC)
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_due_reminders(bot, settings)

    assert len(bot.messages) == 1
    assert "через ~2 часа" in str(bot.messages[0]["text"]).lower()

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.reminder_2h_sent_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_due_reminders_attaches_2h_keyboard(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) + timedelta(hours=2),
    )

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_due_reminders(bot, settings)

    # Only the 2h reminder fires (slot is 2h away — outside the 24h window).
    assert len(bot.messages) == 1
    keyboard = bot.messages[0]["reply_markup"]
    assert keyboard is not None, "2h reminder must carry a keyboard so client can confirm"
    callback_data = keyboard.inline_keyboard[0][0].callback_data
    assert callback_data == f"reminder:ok2h:{booking_id}"

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.reminder_2h_sent_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_list_due_2h_reminders_uses_tight_two_hour_window() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime(2026, 5, 18, 15, 30, tzinfo=UTC)
    async with session_factory() as session:
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        session.add(service)
        await session.flush()

        bookings: list[Booking] = []
        for index, start_at in enumerate(
            [
                now + timedelta(hours=2),
                now + timedelta(hours=2, minutes=30),
                now + timedelta(hours=1, minutes=40),
            ],
            start=1,
        ):
            user = User(
                tg_id=6000 + index,
                display_name=f"Клиентка {index}",
                phone=f"+7999000000{index}",
                is_admin=False,
                is_blocked=False,
            )
            slot = Slot(start_at=start_at, status=SlotStatus.BOOKED)
            booking = Booking(
                client=user,
                slot=slot,
                base_service=service,
                addons=[],
                design_photos=[],
                fixed_price=2400,
                has_variable_price=False,
                status=BookingStatus.CONFIRMED,
            )
            session.add_all([user, slot, booking])
            bookings.append(booking)
        await session.commit()

        due = await BookingRepository(session).list_due_2h_reminders(now_utc=now)

    due_ids = {booking.id for booking in due}
    assert bookings[0].id in due_ids
    assert bookings[1].id not in due_ids
    assert bookings[2].id not in due_ids

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_unconfirmed_alerts_pings_master(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    booking_id = await seed_booking(
        session_factory,
        start_at=now + timedelta(hours=1, minutes=30),
    )
    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        # 2h reminder went out 25 min ago, still no confirmation from the client.
        booking.reminder_2h_sent_at = now - timedelta(minutes=25)
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_unconfirmed_alerts(bot, settings)

    assert len(bot.messages) == 1, "Master should receive exactly one alert"
    assert "не подтвердила" in str(bot.messages[0]["text"]).lower()
    assert "+79991234567" in str(bot.messages[0]["text"])
    assert bot.messages[0]["reply_markup"] is not None
    urls = [
        button.url
        for row in bot.messages[0]["reply_markup"].inline_keyboard
        for button in row
        if getattr(button, "url", None) is not None
    ]
    assert urls == []

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.reminder_2h_unconfirmed_alert_sent_at is not None

    # A second run must not duplicate the alert thanks to the dedupe flag.
    await reminders.send_unconfirmed_alerts(bot, settings)
    assert len(bot.messages) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_unconfirmed_alerts_skips_when_client_confirmed(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    booking_id = await seed_booking(
        session_factory,
        start_at=now + timedelta(hours=1, minutes=30),
    )
    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_2h_sent_at = now - timedelta(minutes=25)
        booking.reminder_2h_confirmed_at = now - timedelta(minutes=10)
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_unconfirmed_alerts(bot, settings)

    assert bot.messages == [], "Confirmation by client must suppress the alert"

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_unconfirmed_alerts_pings_master_when_2h_ignored_after_24h_confirmation(
    monkeypatch,
) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    booking_id = await seed_booking(
        session_factory,
        start_at=now + timedelta(hours=1, minutes=30),
    )
    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_24h_confirmed_at = now - timedelta(hours=20)
        booking.reminder_2h_sent_at = now - timedelta(minutes=25)
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_unconfirmed_alerts(bot, settings)

    assert len(bot.messages) == 1
    assert "не подтвердила" in str(bot.messages[0]["text"]).lower()

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.reminder_2h_unconfirmed_alert_sent_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_unconfirmed_alerts_respects_delay_setting(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    booking_id = await seed_booking(
        session_factory,
        start_at=now + timedelta(hours=1, minutes=30),
    )
    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        # 2h reminder went out only 5 min ago — under the default 20-minute grace period.
        booking.reminder_2h_sent_at = now - timedelta(minutes=5)
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_unconfirmed_alerts(bot, settings)

    assert bot.messages == [], "Alert must wait for the configured delay"

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_unconfirmed_alerts_waits_until_final_window(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    booking_id = await seed_booking(
        session_factory,
        start_at=now + timedelta(hours=2, minutes=10),
    )
    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_2h_sent_at = now - timedelta(minutes=40)
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_unconfirmed_alerts(bot, settings)

    assert bot.messages == [], "Alert must wait until the visit enters the final window"

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_repeat_prompt_marks_booking(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) - timedelta(weeks=4),
        status=BookingStatus.COMPLETED,
    )
    async with session_factory() as session:
        await SettingRepository(session).upsert(key="repeat_prompt_weeks", value="3")
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_repeat_prompt(bot, settings)

    assert len(bot.messages) == 1
    assert "быстро повторить запись" in str(bot.messages[0]["text"]).lower()

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.repeat_prompt_sent_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_repeat_prompt_respects_vacation_mode(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) - timedelta(weeks=4),
        status=BookingStatus.COMPLETED,
    )
    async with session_factory() as session:
        await SettingRepository(session).upsert(key="repeat_prompt_weeks", value="3")
        await SettingRepository(session).upsert(key="vacation_mode", value="1")
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_repeat_prompt(bot, settings)

    assert bot.messages == []

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        assert booking.repeat_prompt_sent_at is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_winback_prompts_respects_vacation_mode(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    _booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) - timedelta(days=90),
        status=BookingStatus.COMPLETED,
    )
    async with session_factory() as session:
        await SettingRepository(session).upsert(key="vacation_mode", value="1")
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    bot = FakeBot()
    await reminders.send_winback_prompts(bot, settings)

    assert bot.messages == []

    async with session_factory() as session:
        user = await session.get(User, 1)
        assert user is not None
        assert user.winback_sent_at is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_reminder_shows_followup_keyboard() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) + timedelta(hours=20),
    )

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        user = await session.get(User, booking.client_id)
        assert user is not None

        callback = FakeCallback(f"reminder:ok:{booking_id}")
        await reminders_handler.confirm_reminder(
            callback,
            db_session=session,
            user=user,
            settings=build_settings(),
        )

        refreshed = await session.get(Booking, booking_id)
        assert refreshed is not None
        assert refreshed.reminder_24h_confirmed_at is not None
        assert refreshed.reminder_2h_confirmed_at is None
        assert callback.message.edits
        text, keyboard = callback.message.edits[-1]
        assert text == reminders_handler.texts.REMINDER_CONFIRMED_TEXT
        assert keyboard is not None
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        assert labels == ["📍 Адрес", "⏰ Опаздываю", "✏️ Перенести"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_reminder_ignores_stale_booking() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) + timedelta(hours=20),
    )

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.status = BookingStatus.CANCELLED_BY_CLIENT
        await session.commit()

        user = await session.get(User, booking.client_id)
        assert user is not None

        callback = FakeCallback(f"reminder:ok:{booking_id}")
        await reminders_handler.confirm_reminder(
            callback,
            db_session=session,
            user=user,
            settings=build_settings(),
        )

        refreshed = await session.get(Booking, booking_id)
        assert refreshed is not None
        assert refreshed.reminder_24h_confirmed_at is None
        assert refreshed.reminder_2h_confirmed_at is None
        assert callback.message.edits == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_reminder_24h_updates_only_24h_timestamp() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) + timedelta(hours=20),
    )

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        user = await session.get(User, booking.client_id)
        assert user is not None

        callback = FakeCallback(f"reminder:ok24h:{booking_id}")
        await reminders_handler.confirm_reminder(
            callback,
            db_session=session,
            user=user,
            settings=build_settings(),
        )

        refreshed = await session.get(Booking, booking_id)
        assert refreshed is not None
        assert refreshed.reminder_24h_confirmed_at is not None
        assert refreshed.reminder_2h_confirmed_at is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_reminder_2h_updates_only_2h_timestamp() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) + timedelta(hours=2),
    )

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_24h_confirmed_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()

        user = await session.get(User, booking.client_id)
        assert user is not None

        callback = FakeCallback(f"reminder:ok2h:{booking_id}")
        await reminders_handler.confirm_reminder(
            callback,
            db_session=session,
            user=user,
            settings=build_settings(),
        )

        refreshed = await session.get(Booking, booking_id)
        assert refreshed is not None
        assert refreshed.reminder_24h_confirmed_at is not None
        assert refreshed.reminder_2h_confirmed_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_reminder_2h_updates_admin_alert_message_live(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    booking_id = await seed_booking(
        session_factory,
        start_at=now + timedelta(hours=1, minutes=30),
    )
    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_2h_sent_at = now - timedelta(minutes=25)
        await session.commit()

    monkeypatch.setattr(
        reminders, "session_scope", lambda _settings: make_session_scope(session_factory)
    )
    admin_bot = FakeBot()
    local_today = datetime.now(ZoneInfo(settings.tz)).date()
    await reminders.send_unconfirmed_alerts(admin_bot, settings)
    assert len(admin_bot.messages) == 1

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        user = await session.get(User, booking.client_id)
        assert user is not None
        await MorningSummaryDeliveryRepository(session).upsert(
            admin_tg_id=1,
            chat_id=1,
            message_id=777,
            summary_local_date=local_today,
            sent_at=now,
        )
        await session.commit()
        callback_bot = admin_bot
        callback = FakeCallback(
            f"reminder:ok2h:{booking_id}",
            bot=callback_bot,
        )
        await reminders_handler.confirm_reminder(
            callback,
            db_session=session,
            user=user,
            settings=settings,
        )

        refreshed = await session.get(Booking, booking_id)
        assert refreshed is not None
        assert refreshed.reminder_2h_confirmed_at is not None
        deliveries = await ReminderAdminAlertDeliveryRepository(
            session
        ).list_open_by_booking_kind(
            booking_id=booking_id,
            reminder_kind="2h",
        )
        assert deliveries == []

    assert admin_bot.edits
    assert any("подтвердила запись" in str(edit["text"]).lower() for edit in admin_bot.edits)
    assert any("к концу дня" in str(edit["text"]).lower() for edit in admin_bot.edits)

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_reminder_legacy_prefers_actual_2h_confirmation() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    booking_id = await seed_booking(
        session_factory,
        start_at=datetime.now(UTC) + timedelta(hours=2),
    )

    async with session_factory() as session:
        booking = await session.get(Booking, booking_id)
        assert booking is not None
        booking.reminder_24h_confirmed_at = datetime.now(UTC) - timedelta(hours=10)
        booking.reminder_2h_sent_at = datetime.now(UTC) - timedelta(minutes=5)
        await session.commit()

        user = await session.get(User, booking.client_id)
        assert user is not None

        callback = FakeCallback(f"reminder:ok:{booking_id}")
        await reminders_handler.confirm_reminder(
            callback,
            db_session=session,
            user=user,
            settings=build_settings(),
        )

        refreshed = await session.get(Booking, booking_id)
        assert refreshed is not None
        assert refreshed.reminder_24h_confirmed_at is not None
        assert refreshed.reminder_2h_confirmed_at is not None

    await engine.dispose()
