"""Date-bound parsing for ``sase stitch list`` filters."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal, cast

DATE_HELP = (
    "Accepted DATE forms: Nh/Nd/Nw, today, yesterday, YYYY-MM-DD, or "
    "YYYY-MM-DDTHH:MM; day-granular until bounds include the full named day"
)

_RELATIVE_RE = re.compile(r"^(?P<amount>\d+)(?P<unit>[hdw])$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ISO_MINUTE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


class VcsLogDateError(ValueError):
    """Raised when a user-provided VCS-log date bound is invalid."""


TimeBoundary = Literal["since", "until"]
TimeBoundKind = Literal["relative", "today", "yesterday", "day", "instant"]
RelativeTimeUnit = Literal["h", "d", "w"]


@dataclass(frozen=True)
class TimeBound:
    """A stable date-bound specification resolved against an operation clock."""

    kind: TimeBoundKind
    amount: int | None = None
    unit: RelativeTimeUnit | None = None
    day: date | None = None
    instant: datetime | None = None

    @property
    def is_day_granular(self) -> bool:
        """Return whether ``until`` should include the full resolved day."""
        return self.kind in {"today", "yesterday", "day"}

    def resolve(
        self,
        *,
        now: datetime | None = None,
        boundary: TimeBoundary = "since",
    ) -> int:
        """Resolve this specification to epoch seconds in the configured timezone."""
        if boundary not in {"since", "until"}:
            raise ValueError(f"Unsupported time-bound direction: {boundary!r}")

        reference = normalize_reference_time(now)
        if self.kind == "relative":
            assert self.amount is not None and self.unit is not None
            if self.unit == "h":
                target = reference - timedelta(hours=self.amount)
            elif self.unit == "d":
                target = reference - timedelta(days=self.amount)
            else:
                target = reference - timedelta(weeks=self.amount)
            return int(target.timestamp())

        if self.kind in {"today", "yesterday"}:
            days_back = 1 if self.kind == "yesterday" else 0
            target_day = reference.date() - timedelta(days=days_back)
            return _resolve_day(target_day, reference, boundary=boundary)

        if self.kind == "day":
            assert self.day is not None
            return _resolve_day(self.day, reference, boundary=boundary)

        assert self.kind == "instant" and self.instant is not None
        target = self.instant.replace(tzinfo=reference.tzinfo)
        return int(target.timestamp())


def parse_time_bound(value: str) -> TimeBound:
    """Parse a VCS-log date bound into a stable semantic specification."""
    raw = value.strip()
    if not raw:
        raise _invalid(value)

    lower = raw.lower()

    relative = _RELATIVE_RE.match(lower)
    if relative:
        amount = int(relative.group("amount"))
        unit = cast(RelativeTimeUnit, relative.group("unit"))
        return TimeBound(kind="relative", amount=amount, unit=unit)

    if lower in {"today", "yesterday"}:
        return TimeBound(kind=cast(TimeBoundKind, lower))

    if _ISO_DATE_RE.match(raw):
        try:
            parsed_day = date.fromisoformat(raw)
        except ValueError as exc:
            raise _invalid(value) from exc
        return TimeBound(kind="day", day=parsed_day)

    if _ISO_MINUTE_RE.match(raw):
        try:
            parsed_instant = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise _invalid(value) from exc
        return TimeBound(kind="instant", instant=parsed_instant)

    raise _invalid(value)


def normalize_reference_time(now: datetime | None = None) -> datetime:
    """Return one aware operation reference in the configured timezone."""
    from sase.core.time import get_timezone

    tz = get_timezone()
    if now is None:
        return datetime.now(tz)
    if now.tzinfo is None:
        return now.replace(tzinfo=tz)
    return now.astimezone(tz)


def _resolve_day(
    target_day: date,
    reference: datetime,
    *,
    boundary: TimeBoundary,
) -> int:
    start = datetime.combine(target_day, time.min, tzinfo=reference.tzinfo)
    if boundary == "since":
        return int(start.timestamp())
    next_midnight = datetime.combine(
        target_day + timedelta(days=1),
        time.min,
        tzinfo=reference.tzinfo,
    )
    return int(next_midnight.timestamp()) - 1


def _invalid(value: str) -> VcsLogDateError:
    return VcsLogDateError(f"Invalid DATE {value!r}. {DATE_HELP}.")


__all__ = [
    "DATE_HELP",
    "TimeBound",
    "TimeBoundary",
    "VcsLogDateError",
    "normalize_reference_time",
    "parse_time_bound",
]
