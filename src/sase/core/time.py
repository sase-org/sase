"""Timezone and timestamp utilities.

The *configured timezone* (see :func:`get_timezone`) is the single definition of
"local" everywhere in SASE. Wall-clock strings are generated in it, aware
timestamps are converted to it for display, and "now" references that compare
against naive configured-tz model datetimes come from :func:`local_now`. Never
use the bare system clock (argument-less ``datetime.now()`` / ``.astimezone()``
/ ``datetime.fromtimestamp()``) for any value that is compared against, or
displayed alongside, a configured-tz value.

Two conventions live side by side:

- **Display**: :func:`parse_local` / :func:`format_local` are the required entry
  points for turning a *stored* timestamp (aware-UTC ISO, naive ISO, or epoch)
  into an aware configured-tz value for showing to a human.
- **Arithmetic**: :func:`local_now` / :func:`to_local` remain the entry points
  for the naive-model convention, where "now" and stored model datetimes are
  both naive configured-tz wall time and compare directly.
"""

import os
from datetime import datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Process-wide cache of the resolved timezone. Runtime behavior is
# cache-once-per-process; tests that flip the configured/system timezone reset
# this global directly (see the ``_pin_configured_timezone`` conftest fixture),
# mirroring how the config caches are cleared.
_cached_timezone: tzinfo | None = None


def _system_timezone() -> tzinfo:
    """Resolve the host system timezone without assuming a specific zone.

    Resolution order: the ``TZ`` env var when it names a valid IANA zone, then
    the ``/etc/localtime`` symlink target (``.../zoneinfo/<Area>/<City>``), then
    a fixed-offset ``tzinfo`` from the system clock as a last resort.
    """
    tz_env = os.environ.get("TZ")
    if tz_env:
        try:
            return ZoneInfo(tz_env)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            pass

    try:
        target = os.readlink("/etc/localtime")
        marker = "zoneinfo/"
        index = target.find(marker)
        if index != -1:
            zone_name = target[index + len(marker) :]
            return ZoneInfo(zone_name)
    except (OSError, ZoneInfoNotFoundError, ValueError):
        pass

    return datetime.now().astimezone().tzinfo or ZoneInfo("UTC")


def get_timezone() -> tzinfo:
    """Get the configured timezone, cached after first call.

    Resolution order:

    1. The ``timezone`` key from the merged sase config, when set.
    2. Otherwise the host system timezone (see :func:`_system_timezone`), so
       machines that don't share our timezone assumptions get sensible behavior
       out of the box.
    """
    global _cached_timezone
    if _cached_timezone is None:
        from sase.config.core import load_merged_config

        config = load_merged_config()
        tz_name = config.get("timezone")
        if isinstance(tz_name, str) and tz_name:
            _cached_timezone = ZoneInfo(tz_name)
        else:
            _cached_timezone = _system_timezone()
    return _cached_timezone


def local_timezone_name() -> str | None:
    """Return the IANA key of the configured timezone, or ``None``.

    ``None`` when the resolved timezone has no IANA key (the fixed-offset
    fallback), in which case callers should inherit the system timezone rather
    than force a ``TZ=`` override.
    """
    return getattr(get_timezone(), "key", None)


def local_now() -> datetime:
    """Return the naive configured-timezone "now".

    This is the reference every mixed-domain site compares against naive
    configured-tz model datetimes; it replaces bare ``datetime.now()``.
    """
    return datetime.now(get_timezone()).replace(tzinfo=None)


def to_local(dt: datetime) -> datetime:
    """Normalize *dt* to a naive configured-timezone wall time.

    Aware datetimes are converted to the configured timezone and stripped of
    ``tzinfo``; naive datetimes are returned unchanged (already local by
    convention).
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(get_timezone()).replace(tzinfo=None)


def generate_timestamp() -> str:
    """Generate a timestamp in YYmmdd_HHMMSS format using the configured timezone.

    Returns:
        Timestamp string like "251227_143052"
    """
    return datetime.now(get_timezone()).strftime("%y%m%d_%H%M%S")


def parse_local(value: str | int | float | datetime | None) -> datetime | None:
    """Return *value* as an aware configured-tz datetime, or ``None`` when unparseable.

    Accepts the shapes a stored timestamp shows up in: an aware-UTC ISO string,
    a naive ISO string, or Unix epoch seconds. Naive inputs (whether a naive
    ``datetime`` or a naive ISO string) are treated as configured-tz wall time
    by repo convention, matching :func:`to_local`.
    """
    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(get_timezone())
        return value.replace(tzinfo=get_timezone())
    try:
        return datetime.fromtimestamp(value, get_timezone())
    except (OSError, OverflowError, ValueError):
        return None


def format_local(
    value: str | int | float | datetime | None,
    fmt: str = "%Y-%m-%d %H:%M:%S",
    *,
    default: str = "—",
) -> str:
    """Format *value* in the configured timezone, or *default* when unparseable."""
    parsed = parse_local(value)
    if parsed is None:
        return default
    return parsed.strftime(fmt)


__all__ = [
    "format_local",
    "generate_timestamp",
    "get_timezone",
    "local_now",
    "local_timezone_name",
    "parse_local",
    "to_local",
]
