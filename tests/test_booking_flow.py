from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, SlotStatus, User
from src.db.repositories.bookings import BookingRepository
from src.services.booking import (
    build_addons_prompt_text,
    build_booking_summary_text,
    cancel_booking,
    confirm_booking,
    needs_late_cancellation_notice,
    needs_onboarding,
    normalize_phone,
    reschedule_booking,
)


def test_addons_prompt_heading_uses_sentence_case() -> None:
    addon = Service(
        id=1,
        name="Дизайн",
        price=250,
        price_variable=True,
        duration_min=0,
        kind=ServiceKind.ADDON,
        is_active=True,
        display_order=10,
    )

    text = build_addons_prompt_text([addon], [])

    assert text.startswith("💅 Дополнительные опции")
    assert "ДОПОЛНИТЕЛЬНЫЕ ОПЦИИ" not in text


@pytest.mark.parametrize(
    ("raw_phone", "expected"),
    [
        ("8 (999) 123-45-67", "+79991234567"),
        ("+7 999 123 45 67", "+79991234567"),
        ("9991234567", "+79991234567"),
        ("12345", None),
    ],
)
def test_normalize_phone(raw_phone: str, expected: str | None) -> None:
    assert normalize_phone(raw_phone) == expected


def test_needs_onboarding_no_longer_requires_phone() -> None:
    user = User(
        tg_id=999,
        display_name="Аня",
        phone=None,
        is_admin=False,
        is_blocked=False,
    )

    assert needs_onboarding(user) is False


def test_build_booking_summary_text_uses_structured_confirmation_copy() -> None:
    base_service = Service(
        name="Гелевая коррекция / укрепление",
        price=2800,
        price_variable=False,
        duration_min=120,
        kind=ServiceKind.BASE,
        is_active=True,
        display_order=10,
    )
    addon = Service(
        name="Дизайн",
        price=0,
        price_variable=True,
        duration_min=0,
        kind=ServiceKind.ADDON,
        is_active=True,
        display_order=20,
    )
    slot = Slot(
        start_at=datetime(2026, 5, 23, 13, 0, tzinfo=UTC),
        status=SlotStatus.FREE,
    )

    text = build_booking_summary_text(
        base_service=base_service,
        addons=[addon],
        slot=slot,
        tz_name="Europe/Moscow",
        design_photo_count=2,
        design_comment="Хочу аккуратный нюд",
        payment_method="cash",
    )

    assert "✨ Проверим запись" in text
    assert "┣ 💅 Услуга" in text
    assert "┣ 📅 Дата и время" in text
    assert "┣ 💵 Итого" in text
    assert "Если всё верно — жми «Подтвердить» 🤍" in text


@pytest.mark.asyncio
async def test_confirm_booking_marks_slot_as_booked() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=1001,
            display_name="Аня",
            phone="+79991234567",
            is_admin=False,
            is_blocked=False,
        )
        base_service = Service(
            name="Покрытие гель-лак",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        addon_service = Service(
            name="Дизайн",
            price=0,
            price_variable=True,
            duration_min=0,
            kind=ServiceKind.ADDON,
            is_active=True,
            display_order=20,
        )
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.FREE,
        )
        session.add_all([user, base_service, addon_service, slot])
        await session.commit()

        result = await confirm_booking(
            session,
            client_id=user.id,
            slot_id=slot.id,
            base_service_id=base_service.id,
            addon_ids=[addon_service.id],
            design_photos=["file-1"],
            design_comment="Нравится нюд",
        )

        refreshed_slot = await session.get(Slot, slot.id)
        booking_count = await session.scalar(select(func.count(Booking.id)))

        assert result.ok is True
        assert result.reason is None
        assert result.booking is not None
        assert result.booking.status.value == "confirmed"
        assert result.booking.design_photos == ["file-1"]
        assert result.booking.design_comment == "Нравится нюд"
        assert result.fixed_price == 2400
        assert result.has_variable_price is True
        assert refreshed_slot is not None
        assert refreshed_slot.status == SlotStatus.BOOKED
        assert booking_count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_booking_rejects_already_taken_slot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        first_user = User(
            tg_id=1001,
            display_name="Аня",
            phone="+79991234567",
            is_admin=False,
            is_blocked=False,
        )
        second_user = User(
            tg_id=1002,
            display_name="Лена",
            phone="+79997654321",
            is_admin=False,
            is_blocked=False,
        )
        base_service = Service(
            name="Маникюр комбинированный без покрытия",
            price=1400,
            price_variable=False,
            duration_min=90,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=2),
            status=SlotStatus.FREE,
        )
        session.add_all([first_user, second_user, base_service, slot])
        await session.commit()

        first_result = await confirm_booking(
            session,
            client_id=first_user.id,
            slot_id=slot.id,
            base_service_id=base_service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
        )
        second_result = await confirm_booking(
            session,
            client_id=second_user.id,
            slot_id=slot.id,
            base_service_id=base_service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
        )

        booking_count = await session.scalar(select(func.count(Booking.id)))

        assert first_result.ok is True
        assert second_result.ok is False
        assert second_result.reason == "slot_unavailable"
        assert booking_count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_reschedule_booking_switches_slots() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=2001,
            display_name="Маша",
            phone="+79990000001",
            is_admin=False,
            is_blocked=False,
        )
        base_service = Service(
            name="Маникюр с покрытием",
            price=2500,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        old_slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=3),
            status=SlotStatus.BOOKED,
        )
        new_slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=4),
            status=SlotStatus.FREE,
        )
        session.add_all([user, base_service, old_slot, new_slot])
        await session.flush()

        booking = Booking(
            client_id=user.id,
            slot=old_slot,
            base_service=base_service,
            addons=[],
            design_photos=[],
            design_comment=None,
            fixed_price=2500,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.commit()

        result = await reschedule_booking(
            session,
            booking=booking,
            new_slot_id=new_slot.id,
        )

        refreshed_booking = await session.get(Booking, booking.id)
        refreshed_old_slot = await session.get(Slot, old_slot.id)
        refreshed_new_slot = await session.get(Slot, new_slot.id)

        assert result.ok is True
        assert refreshed_booking is not None
        assert refreshed_booking.slot_id == new_slot.id
        assert refreshed_old_slot is not None
        assert refreshed_old_slot.status == SlotStatus.FREE
        assert refreshed_new_slot is not None
        assert refreshed_new_slot.status == SlotStatus.BOOKED

    await engine.dispose()


@pytest.mark.asyncio
async def test_cancel_booking_releases_slot_and_keeps_late_notice() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=2002,
            display_name="Нина",
            phone="+79990000002",
            is_admin=False,
            is_blocked=False,
        )
        base_service = Service(
            name="Укрепление",
            price=2200,
            price_variable=False,
            duration_min=90,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        slot = Slot(
            start_at=datetime.now(UTC) + timedelta(hours=12),
            status=SlotStatus.BOOKED,
        )
        session.add_all([user, base_service, slot])
        await session.flush()

        booking = Booking(
            client_id=user.id,
            slot=slot,
            base_service=base_service,
            addons=[],
            design_photos=[],
            design_comment=None,
            fixed_price=2200,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(booking)
        await session.commit()

        loaded_booking = await session.scalar(
            select(Booking).options(selectinload(Booking.slot)).where(Booking.id == booking.id)
        )
        assert loaded_booking is not None
        assert needs_late_cancellation_notice(loaded_booking) is True

        await cancel_booking(
            session,
            booking=loaded_booking,
            reason_code="other",
            reason_text="Нужно срочно уехать",
        )

        refreshed_booking = await session.get(Booking, booking.id)
        refreshed_slot = await session.get(Slot, slot.id)

        assert refreshed_booking is not None
        assert refreshed_booking.status == BookingStatus.CANCELLED_BY_CLIENT
        assert refreshed_booking.cancel_reason_code == "other"
        assert refreshed_booking.cancel_reason_text == "Нужно срочно уехать"
        assert refreshed_slot is not None
        assert refreshed_slot.status == SlotStatus.FREE

    await engine.dispose()


@pytest.mark.asyncio
async def test_list_active_for_client_prioritizes_future_over_past_confirmed() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=2003,
            display_name="Соня",
            phone="+79990000003",
            is_admin=False,
            is_blocked=False,
        )
        base_service = Service(
            name="Маникюр",
            price=2200,
            price_variable=False,
            duration_min=90,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        past_slot = Slot(
            start_at=datetime.now(UTC) - timedelta(hours=2),
            status=SlotStatus.BOOKED,
        )
        future_slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.BOOKED,
        )
        session.add_all([user, base_service, past_slot, future_slot])
        await session.flush()

        past_booking = Booking(
            client_id=user.id,
            slot_id=past_slot.id,
            base_service_id=base_service.id,
            addons=[],
            design_photos=[],
            fixed_price=2200,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
            reminder_2h_sent_at=datetime.now(UTC) - timedelta(hours=3),
            reminder_2h_unconfirmed_alert_sent_at=datetime.now(UTC) - timedelta(hours=1),
        )
        future_booking = Booking(
            client_id=user.id,
            slot_id=future_slot.id,
            base_service_id=base_service.id,
            addons=[],
            design_photos=[],
            fixed_price=2200,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add_all([past_booking, future_booking])
        await session.commit()

        bookings = await BookingRepository(session).list_active_for_client(user.id)
        assert [booking.id for booking in bookings] == [future_booking.id, past_booking.id]

    await engine.dispose()
