"""Duration and absolute-time argument parsing for ``%wait`` directives.

Used by :func:`sase.xprompt.directives.extract_prompt_directives` to
interpret ``%wait:5m``, ``%wait:1h30m``, ``%wait:1430``, and
``%wait:260418/0900`` style arguments.
"""

import re
from datetime import datetime, timedelta

from ._exceptions import DirectiveError

_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")
_HHMM_RE = re.compile(r"^\d{4}$")
_YYMMDD_HHMM_RE = re.compile(r"^(\d{6})/(\d{4})$")


def parse_absolute_time(s: str) -> str | None:
    """Parse an absolute time string into an ISO 8601 target datetime.

    Supported formats:

    - **HHMM** — wait until that time today (wraps to tomorrow if past).
    - **yymmdd/HHMM** — wait until a specific date and time.

    Returns an ISO 8601 string (``YYYY-MM-DDTHH:MM:SS``) or ``None``
    if *s* does not match either format.

    Raises:
        DirectiveError: If the time is invalid or a dated target is in the past.
    """
    m = _YYMMDD_HHMM_RE.match(s)
    if m:
        date_part, time_part = m.group(1), m.group(2)
        hh, mm = int(time_part[:2]), int(time_part[2:])
        if hh > 23 or mm > 59:
            raise DirectiveError(
                f"Invalid time '{time_part}' in '%wait:{s}'"
                f" — hours must be 00-23 and minutes 00-59"
            )
        yy = int(date_part[:2])
        mo = int(date_part[2:4])
        dd = int(date_part[4:6])
        if mo < 1 or mo > 12:
            raise DirectiveError(
                f"Invalid month '{mo:02d}' in '%wait:{s}' — month must be 01-12"
            )
        if dd < 1 or dd > 31:
            raise DirectiveError(
                f"Invalid day '{dd:02d}' in '%wait:{s}' — day must be 01-31"
            )
        try:
            target = datetime(2000 + yy, mo, dd, hh, mm)
        except ValueError as exc:
            raise DirectiveError(f"Invalid date/time in '%wait:{s}' — {exc}") from exc
        if target <= datetime.now():
            raise DirectiveError(f"Target time '%wait:{s}' is in the past")
        return target.isoformat()

    if _HHMM_RE.match(s):
        hh, mm = int(s[:2]), int(s[2:])
        if hh > 23 or mm > 59:
            raise DirectiveError(
                f"Invalid time '{s}' in '%wait:{s}'"
                f" — hours must be 00-23 and minutes 00-59"
            )
        now = datetime.now()
        target = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target.isoformat()

    return None


def parse_duration(s: str) -> float | None:
    """Parse a duration string like ``5m``, ``1h30m``, ``1h30m15s`` into seconds.

    Returns total seconds as a float, or ``None`` if *s* does not match the
    ``XhYmZs`` pattern.  Units must appear in h > m > s order; each unit may
    appear at most once.
    """
    if not s or not s[0].isdigit():
        return None
    m = _DURATION_RE.match(s)
    if not m:
        return None
    hours_s, minutes_s, seconds_s = m.groups()
    if hours_s is None and minutes_s is None and seconds_s is None:
        return None
    hours = int(hours_s) if hours_s else 0
    minutes = int(minutes_s) if minutes_s else 0
    seconds = int(seconds_s) if seconds_s else 0
    return float(hours * 3600 + minutes * 60 + seconds)
