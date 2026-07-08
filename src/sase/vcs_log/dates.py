"""Date-bound parsing for ``sase vcs log`` filters."""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta

DATE_HELP = (
    "Accepted DATE forms: Nh/Nd/Nw, today, yesterday, YYYY-MM-DD, or YYYY-MM-DDTHH:MM"
)

_RELATIVE_RE = re.compile(r"^(?P<amount>\d+)(?P<unit>[hdw])$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MINUTE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


class VcsLogDateError(ValueError):
    """Raised when a user-provided VCS-log date bound is invalid."""


def parse_time_bound(value: str, *, now: datetime | None = None) -> int:
    """Parse a VCS-log date bound into epoch seconds in the configured timezone."""
    raw = value.strip()
    if not raw:
        raise _invalid(value)

    lower = raw.lower()
    reference = _reference_now(now)

    relative = _RELATIVE_RE.match(lower)
    if relative:
        amount = int(relative.group("amount"))
        unit = relative.group("unit")
        if unit == "h":
            target = reference - timedelta(hours=amount)
        elif unit == "d":
            target = reference - timedelta(days=amount)
        else:
            target = reference - timedelta(weeks=amount)
        return int(target.timestamp())

    if lower in {"today", "yesterday"}:
        days_back = 1 if lower == "yesterday" else 0
        target_date = reference.date() - timedelta(days=days_back)
        target = datetime.combine(target_date, time.min, tzinfo=reference.tzinfo)
        return int(target.timestamp())

    if _ISO_DATE_RE.match(raw) or _ISO_MINUTE_RE.match(raw):
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise _invalid(value) from exc
        target = parsed.replace(tzinfo=reference.tzinfo)
        return int(target.timestamp())

    raise _invalid(value)


def _reference_now(now: datetime | None) -> datetime:
    from sase.core.time import get_timezone

    tz = get_timezone()
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def _invalid(value: str) -> VcsLogDateError:
    return VcsLogDateError(f"Invalid DATE {value!r}. {DATE_HELP}.")


__all__ = ["DATE_HELP", "VcsLogDateError", "parse_time_bound"]
