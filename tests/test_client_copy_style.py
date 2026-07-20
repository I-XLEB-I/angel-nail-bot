from __future__ import annotations

import re

from src.bot import texts

CLIENT_HEADING_TEXTS = (
    texts.PORTFOLIO_INTRO,
    texts.DEFAULT_RULES,
    texts.DEFAULT_VACATION_NOTICE,
    texts.DEFAULT_LATE_NOTICE_INTRO_TEMPLATE,
    texts.DEFAULT_REPAIR_INTRO_TEMPLATE,
    texts.DEFAULT_REPAIR_REQUEST_RECEIVED_TEMPLATE,
    texts.DEFAULT_REPAIR_WARRANTY_OFFER_TEMPLATE,
    texts.NO_BOOKINGS_YET_TEXT,
    texts.ONBOARDING_NAME_CONFIRM_TEXT,
    texts.ONBOARDING_PHONE_TEXT,
    texts.BOOKING_CHOOSE_DAY_TEXT,
    texts.BOOKING_CHOOSE_TIME_TEXT,
    texts.BOOKING_CHOOSE_PAYMENT_TEXT,
    texts.BOOKING_REFERENCE_PROMPT_TEXT,
    texts.BOOKING_CUSTOM_TIME_NEW_BOOKING_PROMPT_TEXT,
    texts.BOOKING_CUSTOM_TIME_RESCHEDULE_PROMPT_TEXT,
    texts.APPROVAL_NEW_BOOKING_SENT_TEXT,
    texts.APPROVAL_RESCHEDULE_SENT_TEXT,
    texts.APPROVAL_CUSTOM_TIME_SENT_TEXT,
    texts.ASK_MASTER_PROMPT_TEXT,
    texts.LATE_NOTICE_REASON_PROMPT_TEXT,
    texts.POSTVISIT_PROMPT_TEXT,
    texts.MY_BOOKINGS_CANCEL_WARNING_TEXT,
    texts.MY_BOOKINGS_RESCHEDULE_DAY_TEXT,
    texts.MY_BOOKINGS_RESCHEDULE_TIME_TEXT,
    texts.MY_BOOKINGS_REPAIR_PHOTO_PROMPT_TEXT,
    texts.DEFAULT_PRICE_TEMPLATE,
    texts.BOOKING_SCHEDULE_IMAGE_CAPTION_TEXT,
)


def _first_line(value: str) -> str:
    return re.sub(r"<[^>]+>", "", value.splitlines()[0])


def test_client_headings_use_sentence_case() -> None:
    for value in CLIENT_HEADING_TEXTS:
        heading = _first_line(value)
        letters = "".join(character for character in heading if character.isalpha())
        assert not (letters and letters == letters.upper()), heading


def test_late_policy_appears_in_2h_copy_but_not_earlier_messages() -> None:
    assert "15 минут" not in texts.DEFAULT_BOOKING_CONFIRM_TEMPLATE
    assert "15 минут" not in texts.DEFAULT_REMINDER_24H_TEMPLATE
    assert "15 минут" in texts.DEFAULT_REMINDER_2H_TEMPLATE
    assert "15 минут" in texts.DEFAULT_RULES
