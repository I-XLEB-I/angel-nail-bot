from __future__ import annotations

import importlib
import importlib.util
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot import texts
from src.bot.handlers.admin import settings_edit as settings_edit_handler
from src.bot.handlers.client import booking_confirmation as booking_confirmation_handler
from src.bot.handlers.client import booking_flow as booking_flow_handler
from src.bot.keyboards.client import PHONE_MANUAL_BUTTON_TEXT, build_no_slots_keyboard
from src.config import Settings
from src.db.base import Base
from src.db.models import (
    Booking,
    BookingStatus,
    Service,
    ServiceKind,
    Slot,
    SlotStatus,
    SystemJobStatus,
    User,
)
from src.db.repositories.bookings import BookingRepository
from src.db.repositories.settings import SettingRepository
from src.db.repositories.templates import TemplateRepository
from src.services.anti_abuse import attempt_booking_with_anti_abuse
from src.services.template_texts import ensure_late_policy_notice


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[tuple[str, object | None]] = []

    async def answer(self, text: str, reply_markup=None) -> None:
        self.answers.append((text, reply_markup))


class FakeCallback:
    def __init__(self, data: str, *, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message or FakeMessage()
        self.answered = False

    async def answer(self, *args, **kwargs) -> None:
        del args, kwargs
        self.answered = True


class FakeBrandTarget:
    def __init__(self) -> None:
        self.caption: str | None = None
        self.reply_markup = None


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


async def create_base_entities(session, *, tg_id: int = 1001, name: str = "Аня") -> tuple[User, Service]:
    user = User(
        tg_id=tg_id,
        tg_username=f"user_{tg_id}",
        display_name=name,
        phone=f"+7999{tg_id:07d}"[:12],
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


def legacy_menu_header() -> str:
    return """🤍 ANGELS NAIL SPACE

Маникюрная студия Ангелы — уютное место, где делают красиво и без спешки.

✨ Что можно здесь:

┣ 📅 Посмотреть окошки и записаться
┣ 💰 Открыть актуальный прайс
┣ 📍 Узнать адрес и как дойти
┣ 📸 Заглянуть в портфолио
┗ 💬 Написать Ангеле напрямую

Выбирай раздел ниже 👇"""


def test_ensure_late_policy_notice_does_not_duplicate_existing_text() -> None:
    text = "Запись подтверждена.\n\nЕсли опоздание будет больше 15 минут —\nзапись может отмениться 🤍"
    assert ensure_late_policy_notice(text) == text


@pytest.mark.asyncio
async def test_repeat_prompt_uses_real_latest_completed_booking() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        old_slot = Slot(start_at=datetime.now(UTC) - timedelta(days=100), status=SlotStatus.BOOKED)
        recent_slot = Slot(start_at=datetime.now(UTC) - timedelta(days=20), status=SlotStatus.BOOKED)
        session.add_all([old_slot, recent_slot])
        await session.flush()
        session.add_all(
            [
                Booking(
                    client_id=user.id,
                    slot_id=old_slot.id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
                Booking(
                    client_id=user.id,
                    slot_id=recent_slot.id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
            ]
        )
        await session.commit()

        due = await BookingRepository(session).list_due_repeat_prompts(
            now_utc=datetime.now(UTC),
            repeat_weeks=3,
        )

        assert due == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_winback_skips_blocked_shadow_banned_and_active_clients() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        blocked, service = await create_base_entities(session, tg_id=1002, name="Блок")
        blocked.is_blocked = True

        shadow, _ = await create_base_entities(session, tg_id=1003, name="Шэдоу")
        shadow.is_shadow_banned = True

        active, _ = await create_base_entities(session, tg_id=1004, name="Актив")
        fresh, _ = await create_base_entities(session, tg_id=1005, name="Свежая")

        old_slots = [
            Slot(start_at=datetime.now(UTC) - timedelta(days=90), status=SlotStatus.BOOKED),
            Slot(start_at=datetime.now(UTC) - timedelta(days=95), status=SlotStatus.BOOKED),
            Slot(start_at=datetime.now(UTC) - timedelta(days=91), status=SlotStatus.BOOKED),
            Slot(start_at=datetime.now(UTC) - timedelta(days=20), status=SlotStatus.BOOKED),
            Slot(start_at=datetime.now(UTC) + timedelta(days=5), status=SlotStatus.BOOKED),
        ]
        session.add_all(old_slots)
        await session.flush()
        session.add_all(
            [
                Booking(
                    client_id=blocked.id,
                    slot_id=old_slots[0].id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
                Booking(
                    client_id=shadow.id,
                    slot_id=old_slots[1].id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
                Booking(
                    client_id=active.id,
                    slot_id=old_slots[2].id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
                Booking(
                    client_id=active.id,
                    slot_id=old_slots[4].id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.CONFIRMED,
                ),
                Booking(
                    client_id=fresh.id,
                    slot_id=old_slots[3].id,
                    base_service_id=service.id,
                    addons=[],
                    design_photos=[],
                    fixed_price=2400,
                    has_variable_price=False,
                    status=BookingStatus.COMPLETED,
                ),
            ]
        )
        await session.commit()

        due_users = await BookingRepository(session).list_due_winback(
            now_utc=datetime.now(UTC),
            winback_days=60,
        )

        assert due_users == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_attempt_booking_missing_slot_returns_without_side_effects() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user, service = await create_base_entities(session)
        await session.commit()

        result = await attempt_booking_with_anti_abuse(
            session,
            user=user,
            slot_id=999999,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            tz_name="Europe/Moscow",
        )

        booking_count = await session.scalar(select(func.count(Booking.id)))
        assert result.outcome == "slot_unavailable"
        assert result.confirm_result is None
        assert booking_count == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_booking_success_message_respects_payment_placeholder(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    captured: list[str] = []

    async def fake_send_brand_message(message, *, caption, reply_markup, **kwargs) -> None:
        del message, reply_markup, kwargs
        captured.append(caption)

    async def fake_build_address_text(_session) -> str:
        return "Адрес"

    async def fake_load_runtime_button_configs(_session) -> dict[str, object]:
        return {}

    async with session_factory() as session:
        user, _ = await create_base_entities(session)
        await TemplateRepository(session).upsert(
            key="booking_confirm",
            content="Записала тебя 🌸\n\nОплата уже указана: {payment}",
        )
        await session.commit()

        monkeypatch.setattr(
            booking_confirmation_handler,
            "send_brand_message",
            fake_send_brand_message,
        )
        monkeypatch.setattr(
            booking_confirmation_handler,
            "build_address_text",
            fake_build_address_text,
        )
        monkeypatch.setattr(
            booking_confirmation_handler,
            "load_all_button_configs",
            fake_load_runtime_button_configs,
        )

        await booking_flow_handler.send_booking_success_message(
            FakeBrandTarget(),
            db_session=session,
            user=user,
            settings=build_settings(),
            start_at=datetime.now(UTC) + timedelta(days=1),
            base_service_name="Маникюр",
            payment_method="transfer",
            booking_id=1,
        )

    assert len(captured) == 1
    assert captured[0].count("Оплата") == 1
    assert "15 минут" not in captured[0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_booking_success_message_uses_compact_address_note_when_template_has_media(
    monkeypatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    captured: list[str] = []

    async def fake_send_brand_message(message, *, caption, reply_markup, **kwargs) -> None:
        del message, reply_markup, kwargs
        captured.append(caption)

    async def fake_build_address_text(_session) -> str:
        return "Очаковское шоссе, 5к3\nПодъезд 2"

    async def fake_load_runtime_button_configs(_session) -> dict[str, object]:
        return {}

    async with session_factory() as session:
        user, _ = await create_base_entities(session)

        monkeypatch.setattr(
            booking_confirmation_handler,
            "send_brand_message",
            fake_send_brand_message,
        )
        monkeypatch.setattr(
            booking_confirmation_handler,
            "build_address_text",
            fake_build_address_text,
        )
        monkeypatch.setattr(
            booking_confirmation_handler,
            "load_all_button_configs",
            fake_load_runtime_button_configs,
        )
        monkeypatch.setattr(
            booking_confirmation_handler,
            "has_template_media",
            lambda key: key == "booking_confirm",
        )

        await booking_flow_handler.send_booking_success_message(
            FakeBrandTarget(),
            db_session=session,
            user=user,
            settings=build_settings(),
            start_at=datetime.now(UTC) + timedelta(days=1),
            base_service_name="Маникюр",
            payment_method="transfer",
            booking_id=1,
        )

    assert len(captured) == 1
    assert "📍 Адрес — на картинке выше." in captured[0]
    assert "Очаковское шоссе" not in captured[0]
    assert "────────────" in captured[0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_booking_success_message_upgrades_legacy_default_template(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    captured: list[str] = []

    async def fake_send_brand_message(message, *, caption, reply_markup, **kwargs) -> None:
        del message, reply_markup, kwargs
        captured.append(caption)

    async def fake_build_address_text(_session) -> str:
        return "Тестовый адрес"

    async def fake_load_runtime_button_configs(_session) -> dict[str, object]:
        return {}

    legacy_template = """<b>✅ Записала тебя 🌸</b>

<b>👤 {name}</b>
<b>📅 {date}</b>
<b>⏰ {time}</b>
💅 {service}
💳 {payment}

<b>📍 Адрес</b>
{address}

✨ Напомню за сутки и за пару часов.

Если что-то изменится — жми «Мои записи» в меню.

До встречи 🌸"""

    async with session_factory() as session:
        user, _ = await create_base_entities(session)
        await TemplateRepository(session).upsert(
            key="booking_confirm",
            content=legacy_template,
        )
        await session.commit()

        monkeypatch.setattr(
            booking_confirmation_handler,
            "send_brand_message",
            fake_send_brand_message,
        )
        monkeypatch.setattr(
            booking_confirmation_handler,
            "build_address_text",
            fake_build_address_text,
        )
        monkeypatch.setattr(
            booking_confirmation_handler,
            "load_all_button_configs",
            fake_load_runtime_button_configs,
        )
        monkeypatch.setattr(
            booking_confirmation_handler,
            "has_template_media",
            lambda key: False,
        )

        await booking_flow_handler.send_booking_success_message(
            FakeBrandTarget(),
            db_session=session,
            user=user,
            settings=build_settings(),
            start_at=datetime.now(UTC) + timedelta(days=1),
            base_service_name="Маникюр",
            payment_method="transfer",
            booking_id=1,
        )

    assert len(captured) == 1
    assert "────────────" in captured[0]
    assert "<b>👤" not in captured[0]
    assert "Тестовый адрес" in captured[0]

    await engine.dispose()


@pytest.mark.asyncio
async def test_send_booking_success_message_upgrades_compact_saved_template(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    captured: list[str] = []

    async def fake_send_brand_message(message, *, caption, reply_markup, **kwargs) -> None:
        del message, reply_markup, kwargs
        captured.append(caption)

    async def fake_build_address_text(_session) -> str:
        return "Очаковское шоссе, 5к3"

    async def fake_load_runtime_button_configs(_session) -> dict[str, object]:
        return {}

    compact_template = """Записала тебя 🪄

📆 {date}, {time}

💅 {service}

{address}

Буду напоминать за сутки. Если что-то изменится — жми «Мои записи» в меню.

До встречи 🤍"""

    async with session_factory() as session:
        user, _ = await create_base_entities(session)
        await TemplateRepository(session).upsert(
            key="booking_confirm",
            content=compact_template,
        )
        await session.commit()

        monkeypatch.setattr(
            booking_confirmation_handler,
            "send_brand_message",
            fake_send_brand_message,
        )
        monkeypatch.setattr(
            booking_confirmation_handler,
            "build_address_text",
            fake_build_address_text,
        )
        monkeypatch.setattr(
            booking_confirmation_handler,
            "load_all_button_configs",
            fake_load_runtime_button_configs,
        )
        monkeypatch.setattr(
            booking_confirmation_handler,
            "has_template_media",
            lambda key: key == "booking_confirm",
        )

        await booking_flow_handler.send_booking_success_message(
            FakeBrandTarget(),
            db_session=session,
            user=user,
            settings=build_settings(),
            start_at=datetime.now(UTC) + timedelta(days=1),
            base_service_name="Маникюр",
            payment_method="transfer",
            booking_id=1,
        )

    assert len(captured) == 1
    assert "────────────" in captured[0]
    assert "📍 Адрес — на картинке выше." in captured[0]
    assert "Очаковское шоссе" not in captured[0]

    await engine.dispose()


def test_no_slots_keyboard_has_no_waitlist_button() -> None:
    keyboard = build_no_slots_keyboard()
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "🔔 В лист ожидания" not in labels


@pytest.mark.asyncio
async def test_confirm_back_uses_explicit_return_target(monkeypatch) -> None:
    calls: list[str] = []

    async def fake_show_base_service_step(*args, **kwargs) -> None:
        del args, kwargs
        calls.append("service")

    async def fake_show_time_step(*args, **kwargs) -> None:
        del args, kwargs
        calls.append("time")

    async def fake_show_day_step(*args, **kwargs) -> None:
        del args, kwargs
        calls.append("day")

    monkeypatch.setattr(booking_flow_handler, "show_base_service_step", fake_show_base_service_step)
    monkeypatch.setattr(booking_flow_handler, "show_time_step", fake_show_time_step)
    monkeypatch.setattr(booking_flow_handler, "show_day_step", fake_show_day_step)

    callback = FakeCallback("booking:confirm_back")

    await booking_flow_handler.confirm_back(
        callback,
        FakeState(
            {
                "confirm_return_target": "browse_service",
                "browse_mode": True,
                "slot_id": 42,
            }
        ),
        db_session=None,
        settings=build_settings(),
    )
    await booking_flow_handler.confirm_back(
        callback,
        FakeState(
            {
                "confirm_return_target": "time",
                "selected_day": "2026-05-20",
            }
        ),
        db_session=None,
        settings=build_settings(),
    )
    await booking_flow_handler.confirm_back(
        callback,
        FakeState({"confirm_return_target": "day"}),
        db_session=None,
        settings=build_settings(),
    )

    assert calls == ["service", "time", "day"]


@pytest.mark.asyncio
async def test_settings_diagnostics_show_effective_template_previews() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        await TemplateRepository(session).upsert(key="greeting_header", content=legacy_menu_header())
        await TemplateRepository(session).upsert(key="portfolio_intro", content="portfolio_intro")
        await TemplateRepository(session).upsert(key="about_master", content="about_master")
        await SettingRepository(session).upsert(key="button_config.one", value="{}")
        await SettingRepository(session).upsert(
            key="system.last_backup_at",
            value="2026-05-18T08:00:00+00:00",
        )
        session.add(
            SystemJobStatus(
                job_name="unconfirmed_alerts",
                last_outcome="success",
                consecutive_failures=0,
                last_succeeded_at=datetime(2026, 5, 18, 8, 5, tzinfo=UTC),
            )
        )
        await session.commit()

        text = await settings_edit_handler.render_settings_diagnostics_text(
            session,
            build_settings(),
        )

        assert "Эффективные шаблоны сейчас:" in text
        assert "greeting_header" in text
        assert "Привет, я бот Ангелы" in text
        assert "portfolio_intro" in text
        assert "Работы и настроение" in text
        assert "about_master" in text
        assert "Знакомься — это Ангела" in text
        assert "Последний backup" in text
        assert "SQLite runtime" in text
        assert "unconfirmed_alerts" in text

    await engine.dispose()


def test_phone_manual_button_text_has_single_source_of_truth() -> None:
    assert PHONE_MANUAL_BUTTON_TEXT == "✏️ Ввести вручную"
    assert texts.ONBOARDING_PHONE_SAVED_TEXT == "Супер, сохранила номер ✨"


def load_migration_module(filename: str):
    migration_path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / filename
    spec = importlib.util.spec_from_file_location(filename.replace(".py", ""), migration_path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Failed to load migration module from {migration_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_created_via_migration_is_idempotent_when_column_already_exists() -> None:
    migration = load_migration_module("0011_booking_created_via.py")
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    booking_table = sa.Table(
        "booking",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("created_via", sa.String(length=20), nullable=True),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(booking_table.insert().values(id=1, created_via=None))
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = migration.op
        migration.op = operations
        try:
            migration.upgrade()
        finally:
            migration.op = original_op

        columns = {column["name"] for column in sa.inspect(connection).get_columns("booking")}
        value = connection.execute(sa.text("SELECT created_via FROM booking WHERE id = 1")).scalar_one()

    assert "created_via" in columns
    assert value == "unknown"


def test_created_via_migration_adds_column_when_missing() -> None:
    migration = load_migration_module("0011_booking_created_via.py")
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    booking_table = sa.Table(
        "booking",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True),
    )
    metadata.create_all(engine)

    with engine.begin() as connection:
        connection.execute(booking_table.insert().values(id=1))
        context = MigrationContext.configure(connection)
        operations = Operations(context)
        original_op = migration.op
        migration.op = operations
        try:
            migration.upgrade()
        finally:
            migration.op = original_op

        columns = {column["name"] for column in sa.inspect(connection).get_columns("booking")}
        value = connection.execute(sa.text("SELECT created_via FROM booking WHERE id = 1")).scalar_one()

    assert "created_via" in columns
    assert value == "unknown"
