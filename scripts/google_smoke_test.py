from __future__ import annotations

from src.config import get_settings
from src.services.google_smoke import run_google_smoke_test


def main() -> None:
    """Write a test row to Google Sheets and upload a text file to Drive."""
    settings = get_settings()
    result = run_google_smoke_test(settings)

    print("Google smoke test OK")
    print(f"Sheet tab: {result.sheet_title}")
    print(f"Updated range: {result.updated_range}")
    print(f"Drive file: {result.drive_file_name}")
    print(f"Drive file ID: {result.drive_file_id}")


if __name__ == "__main__":
    main()
