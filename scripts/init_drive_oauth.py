from __future__ import annotations

from src.config import get_settings
from src.services.google_workspace import run_drive_oauth_flow


def main() -> None:
    """Run the local OAuth flow for Google Drive and save the token file."""
    settings = get_settings()
    token_path = run_drive_oauth_flow(settings)

    print("Drive OAuth token saved")
    print(f"Token path: {token_path}")


if __name__ == "__main__":
    main()
