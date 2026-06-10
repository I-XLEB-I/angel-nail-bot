from __future__ import annotations

import logging
import sys

from src.services.observability import JsonLogFormatter


def configure_logging(level: str = "INFO") -> None:
    """Configure application logging."""
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonLogFormatter())
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
