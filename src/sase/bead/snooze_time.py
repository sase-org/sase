"""Wake-time parsing shared by every surface that snoozes a task bead.

The bead store stores one absolute RFC-3339 instant with an offset, but the
useful thing to type is a relative duration. Every surface that accepts a
snooze time -- the CLI's ``-u/--until``, the gate options that carry a
duration in their feedback field, and the ACE modal's custom field -- parses
it here, so ``3d`` cannot mean one thing in one place and something else in
another.

The relative vocabulary is :func:`sase.xprompt._directive_time.parse_duration`
(``30m``, ``2h``, ``1h30m``) widened with a leading day component (``3d``,
``1d12h``), because a bead snooze is routinely measured in days while a
notification snooze is not.

An absolute ISO-8601 timestamp with no offset has the configured timezone
attached rather than being rejected: that is what someone typing
``2026-08-09T09:00`` means, and the store rejects a wake time that names no
instant regardless.

The gate options and the ACE modal's custom field additionally accept a
compact ``"<duration> [+<N>]"`` request that sets a +1 wake target; the CLI
takes that target as its own ``-p/--plus-ones`` flag instead. Both forms
share :func:`parse_snooze_until`, one error type, and one accepted-forms
string, so a wake time cannot be read one way from the CLI and another way
from the gate or the ACE modal.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import re

from sase.core import time as core_time
from sase.core.time import get_timezone
from sase.xprompt._directive_time import parse_duration

ACCEPTED_SNOOZE_FORMS = (
    "accepted forms: a duration such as 30m, 2h, 1h30m, 3d, or 1d12h, or an "
    "absolute ISO-8601 timestamp such as 2026-08-09T09:00:00-04:00, "
    "optionally followed by a +N target such as '3d +2'"
)

_LEADING_DAYS_RE = re.compile(r"^(\d+)d(.*)$")
_PLUS_ONES_RE = re.compile(r"^\+(\d+)$")


class SnoozeTimeError(ValueError):
    """Raised when a snooze time argument cannot be used as a wake time."""


@dataclass(frozen=True)
class _SnoozeRequest:
    """A resolved wake time and optional +1 target for one snooze."""

    until: str
    plus_ones: int | None = None


def parse_snooze_until(value: str, *, now: datetime | None = None) -> str:
    """Resolve one snooze time argument to a stored RFC-3339 wake instant.

    *value* is either a relative duration or an absolute ISO-8601 timestamp.
    An absolute timestamp without an offset is read in the configured
    timezone, since that is what the person typing it meant; the returned
    string always carries an offset because the store rejects one without.

    Raises:
        SnoozeTimeError: If *value* is unparseable, non-positive, or in the
            past. The message always names the accepted forms, because this
            is the one argument a mistyped snooze would silently lose.
    """
    reference = core_time.local_now() if now is None else now
    if reference.tzinfo is None:
        # `local_now` is naive by repo convention, but the store rejects a
        # wake time that names no instant, so the configured zone is attached
        # here rather than left to each caller.
        reference = reference.replace(tzinfo=get_timezone())
    text = value.strip()
    if not text:
        raise SnoozeTimeError(f"snooze time cannot be empty; {ACCEPTED_SNOOZE_FORMS}")

    delta = _parse_snooze_duration(text)
    if delta is not None:
        # Seconds resolution: a wake time is compared against a five-minute
        # reconciliation tick, so sub-second precision is noise that only
        # makes the stored record and every rendering of it harder to read.
        return (reference + delta).replace(microsecond=0).isoformat()

    absolute = _parse_absolute(text)
    if absolute is None:
        raise SnoozeTimeError(
            f"invalid snooze time: {value!r}; {ACCEPTED_SNOOZE_FORMS}"
        )
    if absolute <= reference:
        raise SnoozeTimeError(
            f"snooze time is not in the future: {value!r}; {ACCEPTED_SNOOZE_FORMS}"
        )
    return absolute.replace(microsecond=0).isoformat()


def parse_snooze_request(text: str, *, now: datetime | None = None) -> _SnoozeRequest:
    """Parse ``"<duration> [+<N>]"`` into an absolute wake time.

    *now* exists so callers can resolve a relative duration against a fixed
    clock in tests; production callers omit it.
    """
    tokens = text.split()
    if not tokens:
        raise SnoozeTimeError(f"a snooze needs a wake time; {ACCEPTED_SNOOZE_FORMS}")
    plus_ones: int | None = None
    if len(tokens) > 1:
        match = _PLUS_ONES_RE.fullmatch(tokens[-1])
        if match is None:
            raise SnoozeTimeError(
                f"unrecognized snooze request {text!r}; {ACCEPTED_SNOOZE_FORMS}"
            )
        plus_ones = int(match.group(1))
        if plus_ones <= 0:
            raise SnoozeTimeError(
                f"a +1 target must be positive: {tokens[-1]!r}; {ACCEPTED_SNOOZE_FORMS}"
            )
        tokens = tokens[:-1]
    return _SnoozeRequest(
        until=parse_snooze_until(" ".join(tokens), now=now),
        plus_ones=plus_ones,
    )


def _parse_snooze_duration(value: str) -> timedelta | None:
    """Return the positive relative duration *value* names, else ``None``.

    ``None`` means "not a duration", which the caller retries as an absolute
    timestamp; a duration that parses but is not positive raises instead,
    since ``0m`` is a typo rather than another kind of input.
    """
    text = value.strip()
    days = 0
    match = _LEADING_DAYS_RE.match(text)
    if match is not None:
        days = int(match.group(1))
        text = match.group(2)

    seconds = 0.0
    if text:
        parsed = parse_duration(text)
        if parsed is None:
            return None
        seconds = parsed
    elif not days:
        return None

    delta = timedelta(days=days, seconds=seconds)
    if delta <= timedelta(0):
        raise SnoozeTimeError(
            f"snooze duration must be positive: {value!r}; {ACCEPTED_SNOOZE_FORMS}"
        )
    return delta


def _parse_absolute(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=get_timezone())
    return parsed


__all__ = [
    "ACCEPTED_SNOOZE_FORMS",
    "SnoozeTimeError",
    "parse_snooze_request",
    "parse_snooze_until",
]
