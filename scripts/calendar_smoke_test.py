from __future__ import annotations

from src.config import get_settings
from src.services.calendar_sync import create_smoke_test_event


def main() -> None:
    """Create a Google Calendar smoke-test event and print its details."""
    settings = get_settings()
    result = create_smoke_test_event(settings)

    print("Calendar smoke test OK")
    print(f"Calendar: {result.calendar_summary}")
    print(f"Calendar ID: {result.calendar_id}")
    print(f"Event: {result.event_summary}")
    print(f"Start: {result.start_at}")
    print(f"End: {result.end_at}")
    print(f"Event ID: {result.event_id}")
    print(f"Link: {result.event_html_link}")


if __name__ == "__main__":
    main()
