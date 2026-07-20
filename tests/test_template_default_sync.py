from __future__ import annotations

import hashlib

from scripts.sync_template_defaults import decide_template_sync


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def test_sync_updates_only_exact_old_default() -> None:
    old = "Старый стандарт"
    decision = decide_template_sync(
        current=old,
        new_default="Новый стандарт",
        old_default_sha256=_hash(old),
    )
    assert decision.status == "outdated-default"
    assert decision.should_update is True


def test_sync_skips_customized_template() -> None:
    decision = decide_template_sync(
        current="Текст Ангелы",
        new_default="Новый стандарт",
        old_default_sha256=_hash("Старый стандарт"),
    )
    assert decision.status == "customized"
    assert decision.should_update is False


def test_sync_is_idempotent_for_current_default() -> None:
    decision = decide_template_sync(
        current="Новый стандарт",
        new_default="Новый стандарт",
        old_default_sha256=_hash("Старый стандарт"),
    )
    assert decision.status == "current"
    assert decision.should_update is False
