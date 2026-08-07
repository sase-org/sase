"""The one wake-time vocabulary every bead snooze surface accepts.

A snooze can be requested from a gate's free-text feedback field, from the
CLI, and from the ACE duration modal. All three accept the same compact
``<duration> [+<N>]`` form so a user who learns it in one place can type it
in the others, and all three resolve it here so no surface can drift into
accepting a form the others reject.

``parse_duration`` owns the ``XhYmZs`` vocabulary the notification snooze
modal already uses; days are layered on top of it here because a task bead is
routinely deferred for longer than a day and ``3d`` is the form the epic's
design named.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from sase.core.time import get_timezone
from sase.xprompt._directive_time import parse_duration

SNOOZE_DURATION_FORMS = (
    "accepted forms: a duration such as 30m, 2h, 1h30m, or 3d, or an "
    "ISO-8601 timestamp with an offset, optionally followed by a +1 target "
    "such as '3d +2'"
)

_DAYS_RE = re.compile(r"^(\d+)d(.*)$")
_PLUS_ONES_RE = re.compile(r"^\+(\d+)$")


class SnoozeDurationError(ValueError):
    """One unparsable snooze request, described with its accepted forms."""


@dataclass(frozen=True)
class _SnoozeRequest:
    """A resolved wake time and optional +1 target for one snooze."""

    until: str
    plus_ones: int | None = None


def parse_snooze_request(text: str, *, now: datetime | None = None) -> _SnoozeRequest:
    """Parse ``"<duration> [+<N>]"`` into an absolute wake time.

    *now* exists so callers can resolve a relative duration against a fixed
    clock in tests; production callers omit it.
    """
    tokens = text.split()
    if not tokens:
        raise SnoozeDurationError(
            f"a snooze needs a wake time; {SNOOZE_DURATION_FORMS}"
        )
    plus_ones: int | None = None
    if len(tokens) > 1:
        match = _PLUS_ONES_RE.fullmatch(tokens[-1])
        if match is None:
            raise SnoozeDurationError(
                f"unrecognized snooze request {text!r}; {SNOOZE_DURATION_FORMS}"
            )
        plus_ones = int(match.group(1))
        if plus_ones <= 0:
            raise SnoozeDurationError(
                f"a +1 target must be positive: {tokens[-1]!r}; {SNOOZE_DURATION_FORMS}"
            )
        tokens = tokens[:-1]
    return _SnoozeRequest(
        until=_parse_snooze_until(" ".join(tokens), now=now),
        plus_ones=plus_ones,
    )


def _parse_snooze_until(text: str, *, now: datetime | None = None) -> str:
    """Resolve one duration or absolute timestamp to an offset-bearing wake time."""
    value = text.strip()
    if not value:
        raise SnoozeDurationError(
            f"a snooze needs a wake time; {SNOOZE_DURATION_FORMS}"
        )
    reference = datetime.now(get_timezone()) if now is None else now
    delta = _parse_relative_duration(value)
    if delta is not None:
        if delta <= timedelta(0):
            raise SnoozeDurationError(
                f"a snooze duration must be positive: {value!r}; "
                f"{SNOOZE_DURATION_FORMS}"
            )
        # Seconds resolution, matching the CLI's `-u/--until`: a wake time is
        # compared against a five-minute reconciliation tick, so sub-second
        # precision is noise in every surface that reads the record back.
        return (reference + delta).replace(microsecond=0).isoformat()
    absolute = _parse_absolute_timestamp(value)
    if absolute is None:
        raise SnoozeDurationError(
            f"unrecognized snooze wake time {value!r}; {SNOOZE_DURATION_FORMS}"
        )
    if absolute <= reference:
        raise SnoozeDurationError(
            f"a snooze wake time must be in the future: {value!r}; "
            f"{SNOOZE_DURATION_FORMS}"
        )
    return absolute.replace(microsecond=0).isoformat()


def _parse_relative_duration(value: str) -> timedelta | None:
    """Return the ``3d``/``1h30m`` duration *value* denotes, if it is one."""
    days_match = _DAYS_RE.match(value)
    if days_match is None:
        seconds = parse_duration(value)
        return None if seconds is None else timedelta(seconds=seconds)
    days = timedelta(days=int(days_match.group(1)))
    remainder = days_match.group(2)
    if not remainder:
        return days
    seconds = parse_duration(remainder)
    return None if seconds is None else days + timedelta(seconds=seconds)


def _parse_absolute_timestamp(value: str) -> datetime | None:
    """Return the instant an ISO-8601 timestamp with an offset denotes."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return None if parsed.tzinfo is None else parsed


__all__ = [
    "SNOOZE_DURATION_FORMS",
    "SnoozeDurationError",
    "parse_snooze_request",
]
