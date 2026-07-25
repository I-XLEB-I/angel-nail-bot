from __future__ import annotations

from pathlib import Path
from stat import S_IMODE

from src.config import Settings
from src.main import ensure_runtime_secret_files


def test_runtime_secret_files_are_owner_only(tmp_path: Path) -> None:
    credentials_path = tmp_path / "secrets/google.json"
    settings = Settings(
        BOT_TOKEN="test-token",
        ADMIN_TG_IDS="1",
        GOOGLE_SERVICE_ACCOUNT_JSON='{"private_key":"sensitive"}',
        GOOGLE_SERVICE_ACCOUNT_PATH=credentials_path,
    )

    ensure_runtime_secret_files(settings)

    assert credentials_path.read_text(encoding="utf-8") == '{"private_key":"sensitive"}'
    assert S_IMODE(credentials_path.stat().st_mode) == 0o600
