from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from src.db.models import (
    ApprovalRequest,
    ApprovalRequestKind,
    ApprovalRequestStatus,
    Service,
    ServiceKind,
    User,
)
from src.services.approvals import (
    build_admin_approval_card_text,
    extract_requested_slot_start_at,
)


def test_extract_requested_slot_start_at_from_full_datetime() -> None:
    start_at = extract_requested_slot_start_at(
        requested_text="Можно 22.04 в 13:30?",
        preferred_day=None,
        tz_name="Europe/Moscow",
        today=date(2026, 4, 20),
    )

    assert start_at is not None
    local = start_at.astimezone(ZoneInfo("Europe/Moscow"))
    assert local.date() == date(2026, 4, 22)
    assert local.hour == 13
    assert local.minute == 30


def test_extract_requested_slot_start_at_uses_preferred_day_for_time_only() -> None:
    start_at = extract_requested_slot_start_at(
        requested_text="После работы могу в 19",
        preferred_day=date(2026, 4, 22),
        tz_name="Europe/Moscow",
        today=date(2026, 4, 20),
    )

    assert start_at is not None
    local = start_at.astimezone(ZoneInfo("Europe/Moscow"))
    assert local.date() == date(2026, 4, 22)
    assert local.hour == 19


def test_build_admin_approval_card_text_includes_context() -> None:
    client = User(
        tg_id=1001,
        tg_username="client_name",
        display_name="Аня",
        is_admin=False,
        is_blocked=False,
    )
    base_service = Service(
        name="Маникюр",
        price=2400,
        price_variable=False,
        duration_min=120,
        kind=ServiceKind.BASE,
        is_active=True,
        display_order=10,
    )
    addon = Service(
        name="Дизайн",
        price=300,
        price_variable=False,
        duration_min=30,
        kind=ServiceKind.ADDON,
        is_active=True,
        display_order=20,
    )
    approval = ApprovalRequest(
        client_id=1,
        base_service_id=1,
        addons=[2],
        design_photos=["file-1"],
        requested_text="22.04 в 13:30",
        preferred_day=date(2026, 4, 22),
        kind=ApprovalRequestKind.NEW_BOOKING,
        created_at=datetime.now(UTC) - timedelta(minutes=20),
        status=ApprovalRequestStatus.PENDING,
    )
    approval.client = client
    approval.base_service = base_service

    rendered = build_admin_approval_card_text(
        approval=approval,
        client=client,
        base_service=base_service,
        addons=[addon],
        tz_name="Europe/Moscow",
        now_utc=datetime.now(UTC),
    )

    assert "Тип: Новая запись на нестандартное время" in rendered
    assert "Услуга: Маникюр + Дизайн" in rendered
    assert "Референсы: 1 фото" in rendered
    assert "Создано: 20 мин назад" in rendered
