from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from src.db.base import Base
from src.db.models import Booking, BookingStatus, Service, ServiceKind, Slot, SlotStatus, User
from src.db.repositories.bookings import BookingRepository
from src.services.booking import (
    apply_booking_no_show,
    cancel_booking,
    confirm_booking,
    filter_slots_without_booking_overlap,
    reschedule_booking,
)


async def _seed_booking(session) -> tuple[Booking, User, Service, Slot, Slot, Slot]:
    user = User(
        tg_id=7001,
        display_name="Аня",
        phone="+79990007001",
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
    old_slot = Slot(
        start_at=datetime.now(UTC) + timedelta(days=2),
        status=SlotStatus.BOOKED,
    )
    first_new_slot = Slot(
        start_at=datetime.now(UTC) + timedelta(days=3),
        status=SlotStatus.FREE,
    )
    second_new_slot = Slot(
        start_at=datetime.now(UTC) + timedelta(days=4),
        status=SlotStatus.FREE,
    )
    session.add_all([user, service, old_slot, first_new_slot, second_new_slot])
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
    await session.commit()
    return booking, user, service, old_slot, first_new_slot, second_new_slot


async def _load_booking(session, booking_id: int) -> Booking:
    booking = await session.scalar(
        select(Booking)
        .options(
            selectinload(Booking.slot),
            selectinload(Booking.client),
            selectinload(Booking.base_service),
        )
        .where(Booking.id == booking_id)
    )
    assert booking is not None
    return booking


@pytest.mark.asyncio
async def test_stale_reschedule_does_not_orphan_first_destination(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'reschedule.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as seed_session:
        booking, _, _, old_slot, first_new_slot, second_new_slot = await _seed_booking(seed_session)
        booking_id = booking.id
        old_slot_id = old_slot.id
        first_new_slot_id = first_new_slot.id
        second_new_slot_id = second_new_slot.id

    async with session_factory() as stale_session:
        stale_booking = await _load_booking(stale_session, booking_id)
        await stale_session.commit()

        async with session_factory() as current_session:
            current_booking = await _load_booking(current_session, booking_id)
            first_result = await reschedule_booking(
                current_session,
                booking=current_booking,
                new_slot_id=first_new_slot_id,
            )
            assert first_result.ok is True

        stale_result = await reschedule_booking(
            stale_session,
            booking=stale_booking,
            new_slot_id=second_new_slot_id,
        )
        assert stale_result.ok is False
        assert stale_result.reason == "booking_changed"

    async with session_factory() as verify_session:
        refreshed_booking = await verify_session.get(Booking, booking_id)
        refreshed_old_slot = await verify_session.get(Slot, old_slot_id)
        refreshed_first_new_slot = await verify_session.get(Slot, first_new_slot_id)
        refreshed_second_new_slot = await verify_session.get(Slot, second_new_slot_id)

        assert refreshed_booking is not None
        assert refreshed_booking.slot_id == first_new_slot_id
        assert refreshed_booking.reschedules_count == 1
        assert refreshed_old_slot is not None
        assert refreshed_old_slot.status == SlotStatus.FREE
        assert refreshed_first_new_slot is not None
        assert refreshed_first_new_slot.status == SlotStatus.BOOKED
        assert refreshed_second_new_slot is not None
        assert refreshed_second_new_slot.status == SlotStatus.FREE

    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_cancellation_does_not_release_rebooked_slot(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cancel.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as seed_session:
        booking, _, service, old_slot, _, _ = await _seed_booking(seed_session)
        second_user = User(
            tg_id=7002,
            display_name="Лена",
            phone="+79990007002",
            is_admin=False,
            is_blocked=False,
        )
        seed_session.add(second_user)
        await seed_session.commit()
        booking_id = booking.id
        service_id = service.id
        slot_id = old_slot.id
        second_user_id = second_user.id

    async with session_factory() as stale_session:
        stale_booking = await _load_booking(stale_session, booking_id)
        await stale_session.commit()

        async with session_factory() as current_session:
            current_booking = await _load_booking(current_session, booking_id)
            current_result = await cancel_booking(
                current_session,
                booking=current_booking,
                reason_code="other",
                reason_text="Планы изменились",
            )
            assert current_result.ok is True

            rebooked = await confirm_booking(
                current_session,
                client_id=second_user_id,
                slot_id=slot_id,
                base_service_id=service_id,
                addon_ids=[],
                design_photos=[],
                design_comment=None,
            )
            assert rebooked.ok is True

        stale_result = await cancel_booking(
            stale_session,
            booking=stale_booking,
            reason_code="other",
            reason_text="Устаревшее действие",
        )
        assert stale_result.ok is False
        assert stale_result.reason == "booking_changed"

    async with session_factory() as verify_session:
        slot = await verify_session.get(Slot, slot_id)
        active_count = await verify_session.scalar(
            select(Booking)
            .where(
                Booking.slot_id == slot_id,
                Booking.status == BookingStatus.CONFIRMED,
            )
            .with_only_columns(Booking.id)
        )
        assert slot is not None
        assert slot.status == SlotStatus.BOOKED
        assert active_count is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_no_show_is_idempotent_and_adds_one_penalty(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'no-show.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as seed_session:
        booking, user, _, _, _, _ = await _seed_booking(seed_session)
        booking_id = booking.id
        user_id = user.id

    async with session_factory() as stale_session:
        stale_booking = await _load_booking(stale_session, booking_id)
        await stale_session.commit()

        async with session_factory() as current_session:
            current_booking = await _load_booking(current_session, booking_id)
            first_result = await apply_booking_no_show(
                current_session,
                current_booking,
                no_show_strike_limit=2,
            )
            assert first_result.ok is True
            await current_session.commit()

        stale_result = await apply_booking_no_show(
            stale_session,
            stale_booking,
            no_show_strike_limit=2,
        )
        assert stale_result.ok is False
        assert stale_result.reason == "booking_changed"
        await stale_session.commit()

    async with session_factory() as verify_session:
        refreshed_booking = await verify_session.get(Booking, booking_id)
        refreshed_user = await verify_session.get(User, user_id)
        assert refreshed_booking is not None
        assert refreshed_booking.status == BookingStatus.NO_SHOW
        assert refreshed_user is not None
        assert refreshed_user.strikes == 2
        assert refreshed_user.requires_manual_approval is False

    await engine.dispose()


@pytest.mark.asyncio
async def test_confirm_rejects_free_slot_that_still_has_active_booking(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'guard.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        booking, _, service, old_slot, _, _ = await _seed_booking(session)
        second_user = User(
            tg_id=7003,
            display_name="Оля",
            phone="+79990007003",
            is_admin=False,
            is_blocked=False,
        )
        session.add(second_user)
        await session.flush()
        await session.execute(
            update(Slot).where(Slot.id == old_slot.id).values(status=SlotStatus.FREE)
        )
        await session.commit()

        result = await confirm_booking(
            session,
            client_id=second_user.id,
            slot_id=old_slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
        )

        assert result.ok is False
        assert result.reason == "slot_unavailable"
        active_bookings = await session.scalars(
            select(Booking).where(
                Booking.slot_id == old_slot.id,
                Booking.status == BookingStatus.CONFIRMED,
            )
        )
        assert [item.id for item in active_bookings] == [booking.id]

    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_confirmation_cannot_book_a_past_slot(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'past-confirm.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(tg_id=7004, display_name="Аня")
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
            start_at=datetime.now(UTC) - timedelta(minutes=1),
            status=SlotStatus.FREE,
        )
        session.add_all([user, service, slot])
        await session.commit()

        result = await confirm_booking(
            session,
            client_id=user.id,
            slot_id=slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
        )

        assert result.ok is False
        assert result.reason == "slot_unavailable"
        assert slot.status == SlotStatus.FREE
        assert list((await session.scalars(select(Booking))).all()) == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_two_clients_concurrently_confirm_only_one_booking(tmp_path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'concurrent-confirm.db'}",
        connect_args={"timeout": 5},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as setup_session:
        first_user = User(tg_id=7101, display_name="Первая")
        second_user = User(tg_id=7102, display_name="Вторая")
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
            start_at=datetime.now(UTC) + timedelta(days=1),
            status=SlotStatus.FREE,
        )
        setup_session.add_all([first_user, second_user, service, slot])
        await setup_session.commit()
        user_ids = [first_user.id, second_user.id]
        service_id = service.id
        slot_id = slot.id

    async def confirm_for(client_id: int):
        async with session_factory() as session:
            return await confirm_booking(
                session,
                client_id=client_id,
                slot_id=slot_id,
                base_service_id=service_id,
                addon_ids=[],
                design_photos=[],
                design_comment=None,
            )

    results = await asyncio.gather(*(confirm_for(client_id) for client_id in user_ids))

    assert [result.ok for result in results].count(True) == 1
    assert [result.ok for result in results].count(False) == 1
    async with session_factory() as verify_session:
        bookings = list((await verify_session.execute(select(Booking))).scalars())
        current_slot = await verify_session.get(Slot, slot_id)
        assert len(bookings) == 1
        assert current_slot is not None
        assert current_slot.status == SlotStatus.BOOKED

    await engine.dispose()


@pytest.mark.asyncio
async def test_different_slots_cannot_create_overlapping_appointments(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'overlap.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    start_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=2)
    async with session_factory() as session:
        first_user = User(tg_id=7201, display_name="Первая")
        second_user = User(tg_id=7202, display_name="Вторая")
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        first_slot = Slot(start_at=start_at, status=SlotStatus.FREE)
        overlapping_slot = Slot(
            start_at=start_at + timedelta(minutes=60),
            status=SlotStatus.FREE,
        )
        adjacent_slot = Slot(
            start_at=start_at + timedelta(minutes=120),
            status=SlotStatus.FREE,
        )
        session.add_all(
            [first_user, second_user, service, first_slot, overlapping_slot, adjacent_slot]
        )
        await session.commit()

        first = await confirm_booking(
            session,
            client_id=first_user.id,
            slot_id=first_slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
        )
        second = await confirm_booking(
            session,
            client_id=second_user.id,
            slot_id=overlapping_slot.id,
            base_service_id=service.id,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
        )
        visible_slots = await filter_slots_without_booking_overlap(
            session,
            slots=[overlapping_slot, adjacent_slot],
            duration_min=service.duration_min,
        )

        assert first.ok is True
        assert second.ok is False
        assert second.reason == "time_overlap"
        assert overlapping_slot.status == SlotStatus.FREE
        assert [slot.id for slot in visible_slots] == [adjacent_slot.id]

    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_overlapping_slots_create_only_one_booking(tmp_path) -> None:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'concurrent-overlap.db'}",
        connect_args={"timeout": 5},
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    start_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=2)
    async with session_factory() as setup_session:
        users = [
            User(tg_id=7301, display_name="Первая"),
            User(tg_id=7302, display_name="Вторая"),
        ]
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        slots = [
            Slot(start_at=start_at, status=SlotStatus.FREE),
            Slot(
                start_at=start_at + timedelta(minutes=60),
                status=SlotStatus.FREE,
            ),
        ]
        setup_session.add_all([*users, service, *slots])
        await setup_session.commit()
        user_ids = [user.id for user in users]
        slot_ids = [slot.id for slot in slots]
        service_id = service.id

    async def confirm_for(client_id: int, slot_id: int):
        async with session_factory() as session:
            return await confirm_booking(
                session,
                client_id=client_id,
                slot_id=slot_id,
                base_service_id=service_id,
                addon_ids=[],
                design_photos=[],
                design_comment=None,
            )

    results = await asyncio.gather(
        *(
            confirm_for(client_id, slot_id)
            for client_id, slot_id in zip(user_ids, slot_ids, strict=True)
        )
    )

    assert [result.ok for result in results].count(True) == 1
    assert [result.reason for result in results].count("time_overlap") == 1
    async with session_factory() as verify_session:
        bookings = list((await verify_session.scalars(select(Booking))).all())
        assert len(bookings) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_reschedule_rejects_overlapping_destination(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'move-overlap.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    start_at = datetime.now(UTC).replace(microsecond=0) + timedelta(days=3)
    async with session_factory() as session:
        first_user = User(tg_id=7401, display_name="Первая")
        second_user = User(tg_id=7402, display_name="Вторая")
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        occupied_slot = Slot(start_at=start_at, status=SlotStatus.BOOKED)
        old_slot = Slot(
            start_at=start_at + timedelta(days=1),
            status=SlotStatus.BOOKED,
        )
        destination = Slot(
            start_at=start_at + timedelta(minutes=60),
            status=SlotStatus.FREE,
        )
        session.add_all([first_user, second_user, service, occupied_slot, old_slot, destination])
        await session.flush()
        session.add(
            Booking(
                client_id=first_user.id,
                slot_id=occupied_slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=service.price,
                has_variable_price=False,
                status=BookingStatus.CONFIRMED,
            )
        )
        moving_booking = Booking(
            client_id=second_user.id,
            slot_id=old_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=service.price,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(moving_booking)
        await session.commit()
        loaded_booking = await _load_booking(session, moving_booking.id)

        result = await reschedule_booking(
            session,
            booking=loaded_booking,
            new_slot_id=destination.id,
        )

        assert result.ok is False
        assert result.reason == "time_overlap"
        assert loaded_booking.slot_id == old_slot.id
        assert destination.status == SlotStatus.FREE

    await engine.dispose()


@pytest.mark.asyncio
async def test_bulk_delete_keeps_slot_booked_when_an_active_booking_remains(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'delete.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        booking, second_user, service, old_slot, _, _ = await _seed_booking(session)
        booking.status = BookingStatus.CANCELLED_BY_CLIENT
        active_booking = Booking(
            client_id=second_user.id,
            slot_id=old_slot.id,
            base_service_id=service.id,
            addons=[],
            design_photos=[],
            fixed_price=service.price,
            has_variable_price=False,
            status=BookingStatus.CONFIRMED,
        )
        session.add(active_booking)
        await session.commit()

        deleted = await BookingRepository(session).delete_bookings([booking])
        await session.commit()

        refreshed_slot = await session.get(Slot, old_slot.id)
        assert deleted == 1
        assert refreshed_slot is not None
        assert refreshed_slot.status == SlotStatus.BOOKED
        assert await session.get(Booking, active_booking.id) is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_reschedule_cannot_move_booking_into_the_past(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'past-move.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        booking, _, _, old_slot, _, _ = await _seed_booking(session)
        past_slot = Slot(
            start_at=datetime.now(UTC) - timedelta(minutes=1),
            status=SlotStatus.FREE,
        )
        session.add(past_slot)
        await session.commit()

        result = await reschedule_booking(
            session,
            booking=booking,
            new_slot_id=past_slot.id,
        )

        assert result.ok is False
        assert result.reason == "slot_unavailable"
        assert booking.slot_id == old_slot.id
        assert old_slot.status == SlotStatus.BOOKED
        assert past_slot.status == SlotStatus.FREE

    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_completion_cannot_overwrite_concurrent_cancellation(tmp_path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'completion.db'}")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as seed_session:
        booking, _, _, _, _, _ = await _seed_booking(seed_session)
        booking_id = booking.id
        slot_id = booking.slot_id

    async with session_factory() as completion_session:
        stale_booking = await BookingRepository(completion_session).get_by_id(booking_id)
        assert stale_booking is not None

        async with session_factory() as cancellation_session:
            cancellation = await cancellation_session.execute(
                update(Booking)
                .where(
                    Booking.id == booking_id,
                    Booking.status == BookingStatus.CONFIRMED,
                )
                .values(status=BookingStatus.CANCELLED_BY_CLIENT)
            )
            assert cancellation.rowcount == 1
            await cancellation_session.commit()

        completed = await BookingRepository(completion_session).mark_completed_if_current(
            booking_id=booking_id,
            slot_id=slot_id,
        )
        await completion_session.commit()

    async with session_factory() as verify_session:
        current_booking = await verify_session.get(Booking, booking_id)
        assert completed is False
        assert current_booking is not None
        assert current_booking.status == BookingStatus.CANCELLED_BY_CLIENT

    await engine.dispose()
