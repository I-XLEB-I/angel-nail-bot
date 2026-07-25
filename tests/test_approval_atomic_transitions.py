from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import Settings
from src.db.base import Base
from src.db.models import (
    ApprovalRequest,
    ApprovalRequestKind,
    ApprovalRequestStatus,
    Booking,
    Service,
    ServiceKind,
    Slot,
    SlotStatus,
    User,
)
from src.db.repositories.approvals import ApprovalRequestRepository
from src.services.admin_approvals import (
    commit_quiet_approval_resolution,
    finalize_approval_with_slot,
    reset_approval_offer_to_pending,
)


def _settings(database_url: str) -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL=database_url,
    )


@pytest.mark.asyncio
async def test_stale_approval_card_cannot_create_second_booking(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'approval.db'}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as seed_session:
        user = User(
            tg_id=8101,
            display_name="Клиентка",
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
        first_slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=2),
            status=SlotStatus.FREE,
        )
        second_slot = Slot(
            start_at=datetime.now(UTC) + timedelta(days=3),
            status=SlotStatus.FREE,
        )
        approval = ApprovalRequest(
            client=user,
            base_service=service,
            requested_text="Можно записаться?",
            kind=ApprovalRequestKind.NEW_BOOKING,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        seed_session.add_all([user, service, first_slot, second_slot, approval])
        await seed_session.commit()
        approval_id = approval.id
        first_slot_id = first_slot.id
        second_slot_id = second_slot.id

    async with session_factory() as stale_session:
        stale_approval = await ApprovalRequestRepository(stale_session).get_by_id(approval_id)
        assert stale_approval is not None
        await stale_session.commit()

        async with session_factory() as current_session:
            current_approval = await ApprovalRequestRepository(current_session).get_by_id(
                approval_id
            )
            assert current_approval is not None
            current_result = await finalize_approval_with_slot(
                approval=current_approval,
                slot_id=first_slot_id,
                db_session=current_session,
                settings=_settings(database_url),
            )
            assert current_result.ok is True

        stale_result = await finalize_approval_with_slot(
            approval=stale_approval,
            slot_id=second_slot_id,
            db_session=stale_session,
            settings=_settings(database_url),
        )
        assert stale_result.ok is False
        assert stale_result.reason == "approval_changed"

    async with session_factory() as verify_session:
        refreshed_approval = await verify_session.get(ApprovalRequest, approval_id)
        first_slot = await verify_session.get(Slot, first_slot_id)
        second_slot = await verify_session.get(Slot, second_slot_id)
        booking_count = await verify_session.scalar(select(func.count(Booking.id)))
        booking = await verify_session.scalar(select(Booking))

        assert refreshed_approval is not None
        assert refreshed_approval.status == ApprovalRequestStatus.APPROVED
        assert booking_count == 1
        assert booking is not None
        assert booking.slot_id == first_slot_id
        assert first_slot is not None
        assert first_slot.status == SlotStatus.BOOKED
        assert second_slot is not None
        assert second_slot.status == SlotStatus.FREE

    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_offer_decline_cannot_reopen_approved_request(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'offer.db'}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as seed_session:
        user = User(
            tg_id=8201,
            display_name="Клиентка",
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
        approval = ApprovalRequest(
            client=user,
            base_service=service,
            requested_text="Можно записаться?",
            kind=ApprovalRequestKind.NEW_BOOKING,
            status=ApprovalRequestStatus.OFFERED,
            offered_slot=slot,
            addons=[],
            design_photos=[],
        )
        seed_session.add_all([user, service, slot, approval])
        await seed_session.commit()
        approval_id = approval.id
        slot_id = slot.id

    async with session_factory() as stale_session:
        stale_approval = await ApprovalRequestRepository(stale_session).get_by_id(approval_id)
        assert stale_approval is not None
        await stale_session.commit()

        async with session_factory() as current_session:
            current_approval = await ApprovalRequestRepository(current_session).get_by_id(
                approval_id
            )
            assert current_approval is not None
            result = await finalize_approval_with_slot(
                approval=current_approval,
                slot_id=slot_id,
                db_session=current_session,
                settings=_settings(database_url),
            )
            assert result.ok is True

        reset = await reset_approval_offer_to_pending(
            approval=stale_approval,
            db_session=stale_session,
        )
        assert reset is False

    async with session_factory() as verify_session:
        refreshed = await verify_session.get(ApprovalRequest, approval_id)
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.APPROVED
        assert await verify_session.scalar(select(func.count(Booking.id))) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_stale_quiet_close_cannot_overwrite_approved_request(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'quiet-close.db'}"
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as seed_session:
        user = User(
            tg_id=8301,
            display_name="Клиентка",
            is_admin=False,
            is_blocked=False,
        )
        approval = ApprovalRequest(
            client=user,
            requested_text="Можно записаться?",
            kind=ApprovalRequestKind.QUESTION,
            status=ApprovalRequestStatus.PENDING,
            addons=[],
            design_photos=[],
        )
        seed_session.add_all([user, approval])
        await seed_session.commit()
        approval_id = approval.id

    async with session_factory() as stale_session:
        stale_approval = await ApprovalRequestRepository(stale_session).get_by_id(approval_id)
        assert stale_approval is not None
        await stale_session.commit()

        async with session_factory() as current_session:
            await current_session.execute(
                update(ApprovalRequest)
                .where(ApprovalRequest.id == approval_id)
                .values(status=ApprovalRequestStatus.APPROVED)
            )
            await current_session.commit()

        resolved = await commit_quiet_approval_resolution(
            approval=stale_approval,
            db_session=stale_session,
            allowed_statuses=(ApprovalRequestStatus.PENDING,),
            response_text="Прочитано",
        )
        assert resolved is False

    async with session_factory() as verify_session:
        refreshed = await verify_session.get(ApprovalRequest, approval_id)
        assert refreshed is not None
        assert refreshed.status == ApprovalRequestStatus.APPROVED

    await engine.dispose()
