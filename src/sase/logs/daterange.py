"""Date range parsing for the ``sase logs`` command.

Supports absolute dates (``YYmmdd``, ``YYmmddHHMMSS``), relative dates
(``-7d``, ``0d``), and ranges (``START..END``).  All dates resolve to Eastern
timezone (consistent with the rest of the codebase).
"""

import re
from datetime import datetime, timedelta

from sase.sase_utils import EASTERN_TZ


def _parse_datepoint(s: str) -> datetime:
    """Parse a single date point into a timezone-aware datetime.

    Accepted formats:
    - ``YYmmdd``          – e.g. ``260318``  → 2026-03-18 00:00:00 ET
    - ``YYmmddHHMMSS``    – e.g. ``260318143000`` → 2026-03-18 14:30:00 ET
    - ``-Nd``             – N days ago at midnight
    - ``0d``              – today at midnight
    - ``-Nm``             – N minutes ago
    - ``-Nh``             – N hours ago
    """
    s = s.strip()

    # Relative minutes: -Nm
    m = re.fullmatch(r"(-?\d+)m", s)
    if m:
        offset = int(m.group(1))
        now = datetime.now(EASTERN_TZ)
        return now + timedelta(minutes=offset)

    # Relative hours: -Nh
    m = re.fullmatch(r"(-?\d+)h", s)
    if m:
        offset = int(m.group(1))
        now = datetime.now(EASTERN_TZ)
        return now + timedelta(hours=offset)

    # Relative days: -Nd or 0d
    m = re.fullmatch(r"(-?\d+)d", s)
    if m:
        offset = int(m.group(1))
        today = datetime.now(EASTERN_TZ).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return today + timedelta(days=offset)

    # Absolute: YYmmddHHMMSS (12 digits)
    if re.fullmatch(r"\d{12}", s):
        return datetime.strptime(s, "%y%m%d%H%M%S").replace(tzinfo=EASTERN_TZ)

    # Absolute: YYmmdd (6 digits)
    if re.fullmatch(r"\d{6}", s):
        return datetime.strptime(s, "%y%m%d").replace(tzinfo=EASTERN_TZ)

    raise ValueError(f"Invalid date point: {s!r}")


def parse_daterange(s: str) -> tuple[datetime, datetime]:
    """Parse a date range specification into (start, end) datetimes.

    Accepted formats:
    - ``START..END`` – range between two date points
    - ``SINGLE``     – from that point to now

    The end datetime is clamped to *now* (never in the future).
    """
    s = s.strip()

    if ".." in s:
        left, right = s.split("..", 1)
        start = _parse_datepoint(left)
        end = _parse_datepoint(right)
    else:
        start = _parse_datepoint(s)
        end = datetime.now(EASTERN_TZ)

    # For date-only endpoints, set end to end-of-day
    if end.hour == 0 and end.minute == 0 and end.second == 0:
        end = end.replace(hour=23, minute=59, second=59)

    if start > end:
        raise ValueError(f"Start date {start} is after end date {end}")

    return start, end
