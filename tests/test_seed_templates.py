from __future__ import annotations

from scripts.seed import build_template_seed
from src.services.admin_defaults import required_template_defaults


def test_build_template_seed_matches_required_template_defaults() -> None:
    assert build_template_seed() == required_template_defaults()
