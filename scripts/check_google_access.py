from __future__ import annotations

from src.config import get_settings
from src.services.google_workspace import build_drive_service, build_sheets_service


def main() -> None:
    """Verify that the configured service account can access Sheets and Drive."""
    settings = get_settings()

    if not settings.gsheets_spreadsheet_id:
        raise RuntimeError("GSHEETS_SPREADSHEET_ID is empty in .env")
    if not settings.gdrive_folder_id:
        raise RuntimeError("GDRIVE_FOLDER_ID is empty in .env")

    sheets_service = build_sheets_service(settings)
    drive_service = build_drive_service(settings)

    spreadsheet = (
        sheets_service.spreadsheets().get(spreadsheetId=settings.gsheets_spreadsheet_id).execute()
    )
    folder = (
        drive_service.files()
        .get(
            fileId=settings.gdrive_folder_id,
            fields="id,name,mimeType,webViewLink",
            supportsAllDrives=True,
        )
        .execute()
    )

    print("Google access OK")
    print(f"Spreadsheet: {spreadsheet.get('properties', {}).get('title', '<unknown>')}")
    print(f"Spreadsheet ID: {settings.gsheets_spreadsheet_id}")
    print(f"Drive folder: {folder.get('name', '<unknown>')}")
    print(f"Drive folder ID: {settings.gdrive_folder_id}")


if __name__ == "__main__":
    main()
