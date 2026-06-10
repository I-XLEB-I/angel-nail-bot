from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.config import Settings
from src.db.base import Base
from src.db.models import (
    ApprovalRequest,
    ApprovalRequestKind,
    Service,
    ServiceKind,
    Slot,
    SlotStatus,
    User,
)
from src.services import direct_booking as direct_booking_service
from src.services.anti_abuse import BookingAttemptResult
from src.services.booking import ConfirmBookingResult
from src.services.booking_completion import ConfirmedBookingCompletionResult


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_finalize_direct_booking_attempt_resets_repeat_prompt_for_approval(
    monkeypatch,
) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=1001,
            display_name="Анна",
            is_admin=False,
            is_blocked=False,
            repeat_prompt_snoozed_until=datetime.now(UTC) + timedelta(days=3),
        )
        session.add(user)
        await session.commit()

        approval = ApprovalRequest(
            client_id=user.id,
            kind=ApprovalRequestKind.NEW_BOOKING,
            requested_text="19.05 18:00",
        )

        async def fake_attempt(*args, **kwargs):
            del args, kwargs
            return BookingAttemptResult(
                outcome="approval_existing",
                approval=approval,
            )

        monkeypatch.setattr(
            direct_booking_service,
            "attempt_booking_with_anti_abuse",
            fake_attempt,
        )

        result = await direct_booking_service.finalize_direct_booking_attempt(
            session,
            slot_id=1,
            base_service_id=1,
            user=user,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            payment_method="cash",
            settings=build_settings(),
        )

        refreshed = await session.get(User, user.id)
        assert refreshed is not None
        assert refreshed.repeat_prompt_snoozed_until is None
        assert result.attempt.outcome == "approval_existing"
        assert result.completion is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_finalize_direct_booking_attempt_runs_shared_completion(monkeypatch) -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        user = User(
            tg_id=1002,
            display_name="Анна",
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

        confirm_result = ConfirmBookingResult(
            ok=True,
            reason=None,
            booking=type(
                "BookingStub",
                (),
                {
                    "id": 17,
                    "payment_method": "transfer",
                    "design_comment": None,
                },
            )(),
            slot=slot,
            base_service=service,
            addons=[],
            fixed_price=2400,
            has_variable_price=False,
        )

        async def fake_attempt(*args, **kwargs):
            del args, kwargs
            return BookingAttemptResult(
                outcome="confirmed",
                confirm_result=confirm_result,
            )

        completion_calls: list[dict[str, object]] = []

        async def fake_finalize(*args, **kwargs):
            del args
            completion_calls.append(kwargs)
            return ConfirmedBookingCompletionResult(
                booking_id=17,
                origin="direct",
                calendar_event_id=None,
                client_confirmation=None,
            )

        monkeypatch.setattr(
            direct_booking_service,
            "attempt_booking_with_anti_abuse",
            fake_attempt,
        )
        monkeypatch.setattr(
            direct_booking_service,
            "finalize_confirmed_booking",
            fake_finalize,
        )

        result = await direct_booking_service.finalize_direct_booking_attempt(
            session,
            slot_id=slot.id,
            base_service_id=service.id,
            user=user,
            addon_ids=[],
            design_photos=[],
            design_comment=None,
            payment_method="transfer",
            settings=build_settings(),
        )

        assert result.attempt.outcome == "confirmed"
        assert result.completion is not None
        assert completion_calls
        assert completion_calls[0]["origin"] == "direct"
        assert completion_calls[0]["sync_calendar"] is True

    await engine.dispose()
