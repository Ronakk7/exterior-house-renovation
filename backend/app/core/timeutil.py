"""UTC timestamp helpers."""

from datetime import datetime, timezone


def utc_now() -> str:
    """Return current UTC time as ISO 8601 string with Z suffix.
    
    Example: 2026-11-06T09:30:00Z
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

