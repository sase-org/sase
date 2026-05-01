"""Timezone and timestamp utilities."""

from datetime import datetime
from zoneinfo import ZoneInfo

_cached_timezone: ZoneInfo | None = None


def get_timezone() -> ZoneInfo:
    """Get the configured timezone, cached after first call.

    Reads the ``timezone`` key from the merged sase config.
    Falls back to ``America/New_York`` if not configured.
    """
    global _cached_timezone
    if _cached_timezone is None:
        from sase.config.core import load_merged_config

        config = load_merged_config()
        tz_name = config.get("timezone", "America/New_York")
        _cached_timezone = ZoneInfo(tz_name)
    return _cached_timezone


def generate_timestamp() -> str:
    """Generate a timestamp in YYmmdd_HHMMSS format using the configured timezone.

    Returns:
        Timestamp string like "251227_143052"
    """
    return datetime.now(get_timezone()).strftime("%y%m%d_%H%M%S")
