from __future__ import annotations

import argparse
import asyncio
import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from difflib import unified_diff
from pathlib import Path

from src.config import Settings
from src.db.base import make_database_url, session_scope
from src.db.repositories.templates import TemplateRepository
from src.services.admin_defaults import required_template_defaults

# Fingerprints of the defaults that were deployed before the client-copy refresh.
# A row is updated only when its current content still matches one of these exact values.
OLD_DEFAULT_SHA256 = {
    "portfolio_intro": "3bd9c8c0ac8a3a9a1f2b2a3f6c818198b0170c8cbe6fc4efc615c2543572b4a1",
    "navigation_public": "3b7457118d94262ec5554ead5dbc251e0de1540bf2dc49ae8f922f98b7d060bf",
    "navigation": "33fa9199b64eb11557e2c02ab9f0375857c5d95ca177e40f55b8bc60bae935c6",
    "address_post_confirm": "33fa9199b64eb11557e2c02ab9f0375857c5d95ca177e40f55b8bc60bae935c6",
    "rules": "f77a2005c0a70f8715c73ebb567c6bf54233445ef1c0230f8234b557f3c46a41",
    "vacation_notice": "957721d76ca99bf0894263f52e5c7ecfcc5b5db469dee4f7a38951a8b70f880a",
    "booking_confirm": "719c880eebd8fcd46fa87c3e48a15e33252c4942288765c1c5c7f6e2d644c8cd",
    "reminder_24h": "556a1bcf2e4282e7eee25c87683c8f51509f1ae9fd639537f14ca1fc5dbb4274",
    "reminder_2h": "d70b2c00363e9a67ca6150280a6801bc0212b9ca914acd2b39d319df8ac9169f",
    "late_notice_intro": "b5cef661940cc63e74cf03402fd54aa49f0bc0ddec1ec16c48ef14657d1fdf11",
    "repair_intro": "d2da26ca637f7292b1f00013bfa642779e8b1359661cab61fea2b7e1abfe8559",
    "repair_request_received": (
        "774082af59affb249c90d8371f492e0452cbe7621fdf3cdc89b64dddf262de56"
    ),
    "repair_warranty_offer": (
        "988db5088bd0d5ad4190cb4fdf1a5c320a4d3139d08a40df3aa882b433a5057f"
    ),
    "price": "a3c80d4c8679a46bf9a0d0b3a71647071f80beec750ad7fc2d8c81e6f9b08b42",
}


@dataclass(frozen=True, slots=True)
class TemplateSyncDecision:
    """Pure decision for one stored template row."""

    status: str
    should_update: bool


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def decide_template_sync(
    *,
    current: str | None,
    new_default: str,
    old_default_sha256: str,
) -> TemplateSyncDecision:
    """Choose an idempotent action without overwriting customized content."""
    if current is None:
        return TemplateSyncDecision(status="missing", should_update=True)
    if current == new_default:
        return TemplateSyncDecision(status="current", should_update=False)
    if _sha256(current) == old_default_sha256:
        return TemplateSyncDecision(status="outdated-default", should_update=True)
    return TemplateSyncDecision(status="customized", should_update=False)


def _render_diff(key: str, current: str, new_default: str) -> str:
    current_lines = [f"{line}\n" for line in current.splitlines()]
    default_lines = [f"{line}\n" for line in new_default.splitlines()]
    return "".join(
        unified_diff(
            current_lines,
            default_lines,
            fromfile=f"database/{key}",
            tofile=f"new-default/{key}",
        )
    )


def _backup_sqlite(settings: Settings) -> Path | None:
    database_url = make_database_url(settings)
    if not database_url.drivername.startswith("sqlite"):
        return None
    database_name = database_url.database
    if not database_name or database_name == ":memory:":
        return None
    source_path = Path(database_name).expanduser().resolve()
    if not source_path.exists():
        raise FileNotFoundError(f"SQLite database does not exist: {source_path}")
    backup_dir = Path("backups").resolve()
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = backup_dir / f"bot-before-template-sync-{timestamp}.db"
    with sqlite3.connect(source_path) as source, sqlite3.connect(backup_path) as target:
        source.backup(target)
    return backup_path


async def sync_templates(*, settings: Settings, apply: bool) -> int:
    """Print a sync plan and optionally apply only safe default updates."""
    defaults = required_template_defaults()
    updated = 0
    customized = 0
    unchanged = 0

    async with session_scope(settings) as session:
        repository = TemplateRepository(session)
        for key, old_hash in OLD_DEFAULT_SHA256.items():
            new_default = defaults[key]
            current = await repository.get_content(key)
            decision = decide_template_sync(
                current=current,
                new_default=new_default,
                old_default_sha256=old_hash,
            )
            if decision.should_update:
                action = "UPDATED" if apply else "WOULD UPDATE"
                print(f"{action:12} {key} ({decision.status})")
                if apply:
                    await repository.upsert(key=key, content=new_default)
                updated += 1
                continue
            if decision.status == "customized":
                customized += 1
                print(f"SKIPPED      {key} (customized)")
                print(_render_diff(key, current or "", new_default))
                continue
            unchanged += 1
            print(f"UNCHANGED    {key}")

        if apply:
            await session.commit()
        else:
            await session.rollback()

    mode = "applied" if apply else "dry-run"
    print(
        f"Summary ({mode}): updates={updated}, customized={customized}, "
        f"unchanged={unchanged}"
    )
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Safely synchronize untouched template defaults with the current code."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create a backup and write safe updates. The default is dry-run.",
    )
    parser.add_argument(
        "--skip-backup",
        action="store_true",
        help="Allow --apply without an automatic SQLite backup (for externally backed-up DBs).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings()
    if args.apply and not args.skip_backup:
        backup_path = _backup_sqlite(settings)
        if backup_path is None:
            raise RuntimeError(
                "Automatic backup is available only for file-based SQLite. "
                "Create an external backup and rerun with --skip-backup."
            )
        print(f"Backup: {backup_path}")
    asyncio.run(sync_templates(settings=settings, apply=args.apply))


if __name__ == "__main__":
    main()
