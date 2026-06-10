from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.bot.handlers.client import aftercare as aftercare_handler
from src.config import Settings
from src.db.base import Base
from src.db.models import (
    ApprovalRequest,
    ApprovalRequestKind,
    Booking,
    BookingStatus,
    LateArrivalNotice,
    Service,
    ServiceKind,
    Slot,
    SlotStatus,
    User,
)
from src.services.aftercare import can_report_late_arrival


class FakeState:
    def __init__(self, data: dict[str, object] | None = None) -> None:
        self.data = dict(data or {})
        self.state: object | None = None

    async def get_data(self) -> dict[str, object]:
        return dict(self.data)

    async def update_data(self, **kwargs: object) -> None:
        self.data.update(kwargs)

    async def set_state(self, state: object) -> None:
        self.state = state


class FakeBot:
    def __init__(self) -> None:
        self.sent_messages: list[dict[str, object]] = []

    async def send_message(self, *, chat_id: int, text: str, reply_markup=None, parse_mode=None):
        self.sent_messages.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )
        return type("SentMessage", (), {"message_id": 1})()


class FakeChat:
    def __init__(self, chat_id: int = 700) -> None:
        self.id = chat_id


class FakeMessage:
    def __init__(self, *, bot: FakeBot | None = None, text: str | None = None) -> None:
        self.bot = bot or FakeBot()
        self.chat = FakeChat()
        self.message_id = 10
        self.text = text
        self.answers: list[dict[str, object]] = []

    async def answer(self, text: str, reply_markup=None, parse_mode=None):
        self.answers.append(
            {
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )
        return type("AnsweredMessage", (), {"message_id": 11, "chat": self.chat})()


class FakeCallback:
    def __init__(self, data: str, *, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message or FakeMessage()
        self.answered = False

    async def answer(self, *args, **kwargs) -> None:
        del args, kwargs
        self.answered = True


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
async def test_can_report_late_arrival_allows_same_day_booking() -> None:
    now = datetime(2026, 4, 26, 8, 0, tzinfo=UTC)
    booking = Booking(
        status=BookingStatus.CONFIRMED,
        slot=Slot(
            start_at=datetime(2026, 4, 26, 18, 0, tzinfo=UTC),
            status=SlotStatus.BOOKED,
        ),
        addons=[],
        design_photos=[],
        fixed_price=2400,
        has_variable_price=False,
    )

    assert can_report_late_arrival(booking, now_utc=now) is True


@pytest.mark.asyncio
async def test_submit_late_notice_updates_single_active_notice(monkeypatch) -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()
    sent_templates: list[dict[str, object]] = []
    sent_admin_texts: list[str] = []

    async def fake_clear_state(_state) -> None:
        return None

    async def fake_send_template_message(
        message,
        *,
        template_key: str,
        caption: str,
        reply_markup=None,
        replace_current: bool = False,
        parse_mode=None,
    ) -> None:
        del message, reply_markup, replace_current, parse_mode
        sent_templates.append({"template_key": template_key, "caption": caption})

    async def fake_send_text_to_admins(bot, *, admin_tg_ids, text: str, reply_markup=None) -> None:
        del bot, admin_tg_ids, reply_markup
        sent_admin_texts.append(text)

    monkeypatch.setattr(aftercare_handler, "clear_state_preserving_admin_mode", fake_clear_state)
    monkeypatch.setattr(aftercare_handler, "send_template_message", fake_send_template_message)
    monkeypatch.setattr(aftercare_handler, "send_text_to_admins", fake_send_text_to_admins)

    async with session_factory() as session:
        user = User(tg_id=5010, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = build_base_service()
        slot = Slot(start_at=datetime.now(UTC) + timedelta(hours=2), status=SlotStatus.BOOKED)
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
        session.add_all([user, service, slot, booking])
        await session.commit()

        state = FakeState()
        message = FakeMessage()

        await aftercare_handler.submit_late_notice(
            message=message,
            state=state,  # type: ignore[arg-type]
            db_session=session,
            user=user,
            settings=settings,
            booking_id=booking.id,
            minutes=10,
            reason_code="traffic",
            comment=None,
            replace_current=False,
        )
        await aftercare_handler.submit_late_notice(
            message=message,
            state=state,  # type: ignore[arg-type]
            db_session=session,
            user=user,
            settings=settings,
            booking_id=booking.id,
            minutes=20,
            reason_code="delayed",
            comment="Чуть застряла",
            replace_current=False,
        )

        assert await session.scalar(select(func.count(LateArrivalNotice.id))) == 1
        notice = await session.scalar(select(LateArrivalNotice))
        assert notice is not None
        assert notice.minutes == 20
        assert notice.reason_code == "delayed"
        assert notice.comment == "Чуть застряла"

    assert len(sent_admin_texts) == 2
    assert sent_templates[0]["template_key"] == "late_notice_client_sent"
    assert sent_templates[1]["template_key"] == "late_notice_client_risky"
    await engine.dispose()


@pytest.mark.asyncio
async def test_submit_repair_request_creates_repair_approval(monkeypatch) -> None:
    settings = build_settings()
    engine, session_factory = await setup_session()
    sent_templates: list[dict[str, object]] = []
    sent_approval_ids: list[int] = []

    async def fake_clear_state(_state) -> None:
        return None

    async def fake_send_template_message(
        message,
        *,
        template_key: str,
        caption: str,
        reply_markup=None,
        replace_current: bool = False,
        parse_mode=None,
    ) -> None:
        del message, reply_markup, replace_current, parse_mode
        sent_templates.append({"template_key": template_key, "caption": caption})

    async def fake_send_approval_card_to_admins(*, approval, **kwargs) -> None:
        del kwargs
        sent_approval_ids.append(approval.id)

    monkeypatch.setattr(aftercare_handler, "clear_state_preserving_admin_mode", fake_clear_state)
    monkeypatch.setattr(aftercare_handler, "send_template_message", fake_send_template_message)
    monkeypatch.setattr(
        aftercare_handler,
        "send_approval_card_to_admins",
        fake_send_approval_card_to_admins,
    )

    async with session_factory() as session:
        user = User(tg_id=5011, display_name="Клиентка", is_admin=False, is_blocked=False)
        service = build_base_service()
        slot = Slot(start_at=datetime.now(UTC) - timedelta(days=3), status=SlotStatus.BOOKED)
        booking = Booking(
            client=user,
            slot=slot,
            base_service=service,
            addons=[],
            design_photos=[],
            fixed_price=2400,
            has_variable_price=False,
            status=BookingStatus.COMPLETED,
        )
        session.add_all([user, service, slot, booking])
        await session.commit()

        state = FakeState(
            {
                "repair_booking_id": booking.id,
                "repair_issue_code": "chip",
                "repair_nails_count": 2,
                "repair_photos": ["file_1", "file_2"],
            }
        )
        message = FakeMessage(text="Скололся один уголок")

        await aftercare_handler.submit_repair_request(
            message,
            state,  # type: ignore[arg-type]
            db_session=session,
            user=user,
            settings=settings,
        )

        approval = await session.scalar(select(ApprovalRequest))
        assert approval is not None
        assert approval.kind == ApprovalRequestKind.REPAIR_REQUEST
        assert approval.related_booking_id == booking.id
        assert approval.repair_nails_count == 2
        assert approval.repair_issue_code == "chip"
        assert approval.design_photos == ["file_1", "file_2"]
        assert approval.design_comment == "Скололся один уголок"

    assert sent_approval_ids == [approval.id]
    assert sent_templates[-1]["template_key"] == "repair_request_received"
    await engine.dispose()


@pytest.mark.asyncio
async def test_back_to_repair_issue_clears_photo_step(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_replace_inline_message_text(message, text, reply_markup=None) -> None:
        del message
        captured["text"] = text
        captured["reply_markup"] = reply_markup

    async def fake_load_runtime_button_configs(db_session) -> dict[str, object]:
        del db_session
        return {}

    monkeypatch.setattr(aftercare_handler, "replace_inline_message_text", fake_replace_inline_message_text)
    monkeypatch.setattr(
        aftercare_handler,
        "load_runtime_button_configs",
        fake_load_runtime_button_configs,
    )

    state = FakeState(
        {
            "repair_booking_id": 42,
            "repair_nails_count": 2,
            "repair_issue_code": "chip",
            "repair_photos": ["file_1"],
        }
    )
    callback = FakeCallback("repair:photos_back:42")

    await aftercare_handler.back_to_repair_issue(
        callback,
        state,  # type: ignore[arg-type]
        db_session=None,
    )

    assert callback.answered is True
    assert state.state == aftercare_handler.RepairRequestFlow.choose_issue
    assert state.data["repair_photos"] == []
    assert "Что именно случилось" in str(captured["text"])


@pytest.mark.asyncio
async def test_back_to_repair_photos_restores_photo_step(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_replace_inline_message_text(message, text, reply_markup=None) -> None:
        del message
        captured["text"] = text
        captured["reply_markup"] = reply_markup

    async def fake_load_runtime_button_configs(db_session) -> dict[str, object]:
        del db_session
        return {}

    monkeypatch.setattr(aftercare_handler, "replace_inline_message_text", fake_replace_inline_message_text)
    monkeypatch.setattr(
        aftercare_handler,
        "load_runtime_button_configs",
        fake_load_runtime_button_configs,
    )

    state = FakeState(
        {
            "repair_booking_id": 42,
            "repair_issue_code": "chip",
            "repair_nails_count": 2,
            "repair_photos": ["file_1", "file_2"],
        }
    )
    callback = FakeCallback("repair:description_back:42")

    await aftercare_handler.back_to_repair_photos(
        callback,
        state,  # type: ignore[arg-type]
        db_session=None,
    )

    assert callback.answered is True
    assert state.state == aftercare_handler.RepairRequestFlow.upload_photos
    assert "Фото добавлены: 2/3" in str(captured["text"])
