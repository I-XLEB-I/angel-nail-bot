from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.admin import menu as admin_menu_handler
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
    User,
)
from src.db.repositories.templates import TemplateRepository


class FakeState:
    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)


class FakeMessage:
    pass


def build_settings() -> Settings:
    return Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        TZ="Europe/Moscow",
        DATABASE_URL="sqlite+aiosqlite:///:memory:",
    )


@pytest.mark.asyncio
async def test_show_admin_menu_uses_template_text_and_brand_photo(monkeypatch) -> None:
    settings = build_settings()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        admin = User(tg_id=1, display_name="Ангела", is_admin=True, is_blocked=False)
        client = User(tg_id=2, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = Service(
            name="Маникюр",
            price=2400,
            price_variable=False,
            duration_min=120,
            kind=ServiceKind.BASE,
            is_active=True,
            display_order=10,
        )
        slot = Slot(start_at=datetime.now(UTC), status="booked")
        session.add_all([admin, client, service, slot])
        await session.flush()
        session.add(
            Booking(
                client_id=client.id,
                slot_id=slot.id,
                base_service_id=service.id,
                addons=[],
                design_photos=[],
                fixed_price=2400,
                has_variable_price=False,
                status=BookingStatus.CONFIRMED,
            )
        )
        session.add(
            ApprovalRequest(
                client_id=client.id,
                requested_text="Завтра в 18:00",
                kind=ApprovalRequestKind.NEW_BOOKING,
                status=ApprovalRequestStatus.PENDING,
                addons=[],
                design_photos=[],
            )
        )
        await TemplateRepository(session).upsert(
            key="admin_menu_text",
            content="Запросов: {pending_approvals} / Сегодня: {today_bookings}",
        )
        await session.commit()

        captured: dict[str, object] = {}

        async def fake_send_admin_photo_panel(
            message,
            state,
            *,
            photo_bytes,
            filename,
            caption,
            reply_markup=None,
            parse_mode=None,
        ):
            del message, state, reply_markup, parse_mode
            captured["photo_bytes"] = photo_bytes
            captured["filename"] = filename
            captured["caption"] = caption

        monkeypatch.setattr(admin_menu_handler, "load_brand_image_bytes", lambda: b"brand")
        monkeypatch.setattr(
            admin_menu_handler,
            "send_admin_photo_panel",
            fake_send_admin_photo_panel,
        )

        await admin_menu_handler.show_admin_menu(
            FakeMessage(),
            db_session=session,
            settings=settings,
            state=FakeState(),
        )

        assert captured["photo_bytes"] == b"brand"
        assert captured["filename"] == admin_menu_handler.BRAND_IMAGE_PATH.name
        assert captured["caption"] == "Запросов: 1 / Сегодня: 1"

    await engine.dispose()
