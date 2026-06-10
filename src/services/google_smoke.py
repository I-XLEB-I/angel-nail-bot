from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.config import Settings
from src.services.google_drive import upload_bytes_file
from src.services.google_sheets import append_row, ensure_sheet_tab


@dataclass(slots=True)
class GoogleSmokeResult:
    """Result of a combined Google Sheets and Drive smoke check."""

    sheet_title: str
    updated_range: str
    drive_file_name: str
    drive_file_id: str


def run_google_smoke_test(settings: Settings) -> GoogleSmokeResult:
    """Write a test row to Google Sheets and upload a text file to Drive."""
    timestamp = datetime.now().isoformat(timespec="seconds")

    sheet_title = ensure_sheet_tab(
        settings,
        title="SmokeTests",
        headers=["timestamp", "status", "note"],
    )
    append_result = append_row(
        settings,
        sheet_title=sheet_title,
        values=[timestamp, "ok", "Smoke test from bot"],
    )

    file_name = f"smoke_test_{timestamp.replace(':', '-')}.txt"
    drive_result = upload_bytes_file(
        settings,
        file_name=file_name,
        content=f"Smoke test created at {timestamp}\n".encode(),
        mime_type="text/plain",
    )

    return GoogleSmokeResult(
        sheet_title=sheet_title,
        updated_range=append_result.get("updates", {}).get("updatedRange", "<unknown>"),
        drive_file_name=drive_result.get("name", "<unknown>"),
        drive_file_id=drive_result.get("id", "<unknown>"),
    )
