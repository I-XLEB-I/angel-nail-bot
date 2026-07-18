from __future__ import annotations

from src.bot.handlers.client import brand


class FakeMessage:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.photos: list[object] = []

    async def answer(self, text: str, **kwargs) -> None:
        del kwargs
        self.texts.append(text)

    async def answer_photo(self, photo, **kwargs) -> None:
        del kwargs
        self.photos.append(photo)


class FakeBot:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.photos: list[object] = []

    async def send_message(self, *, text: str, **kwargs) -> None:
        del kwargs
        self.texts.append(text)

    async def send_photo(self, *, photo, **kwargs) -> None:
        del kwargs
        self.photos.append(photo)


async def test_named_template_without_media_sends_plain_text(monkeypatch) -> None:
    monkeypatch.setattr(brand, "has_template_media", lambda key: False)
    message = FakeMessage()

    await brand.send_brand_message(
        message,
        caption="Публичный адрес",
        template_key="navigation_public",
    )

    assert message.texts == ["Публичный адрес"]
    assert message.photos == []


async def test_proactive_named_template_without_media_sends_plain_text(monkeypatch) -> None:
    monkeypatch.setattr(brand, "has_template_media", lambda key: False)
    bot = FakeBot()

    await brand.send_brand_bot_message(
        bot,
        chat_id=1,
        caption="Напоминание",
        template_key="reminder_24h",
    )

    assert bot.texts == ["Напоминание"]
    assert bot.photos == []
