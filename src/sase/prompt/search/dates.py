"""Date-filter parsing and per-source date precedence for prompt search.

Two responsibilities:

- :func:`parse_search_date` turns a user ``--after``/``--before`` value into a
  comparable SASE ``YYmmdd_HHMMSS`` anchor, extending the prune parser with
  ``YYYYMM`` and relative ``Nd/Nw/Nm/Ny`` offsets.
- :func:`resolve_archive_date` implements the documented archive date precedence
  (frontmatter timestamp → ``YYYYMM`` path segment → file mtime); local entries
  use their ``last_used`` directly. :func:`hit_date` is the single accessor the
  engine and renderers use for a hit's comparable date.

Everything returns the same ``YYmmdd_HHMMSS`` shape used across SASE so date
comparison stays a plain lexicographic string compare.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, tzinfo
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.history.prompt import PromptDateError, parse_prune_date

if TYPE_CHECKING:
    from collections.abc import Mapping

    from sase.prompt.search.model import PromptHit

# Relative offsets like ``30d`` / ``2w`` / ``6m`` / ``1y``; case-insensitive.
_RELATIVE_RE = re.compile(r"^(\d+)([dwmy])$")
# A full ``YYYYMM`` month, e.g. ``202604``. Distinguished from a 6-digit
# ``YYmmdd`` by trying the SASE-native ``YYmmdd`` parse first (see below).
_YYYYMM_RE = re.compile(r"^(\d{4})(\d{2})$")
# Canonical archive month segment, e.g. ``prompts/202604/foo.md``.
_PATH_YYYYMM_RE = re.compile(r"^\d{6}$")

# Oldest-sortable floor for hits whose date cannot be resolved at all.
_DATE_FLOOR = "000000_000000"

_RELATIVE_HINT = "30d (last 30 days), 2w, 6m, 1y"
_ABSOLUTE_HINT = (
    "2026-01-01 (YYYY-MM-DD), 202601 (YYYYMM), 260101 (YYmmdd),"
    " or 260101_143000 (YYmmdd_HHMMSS)"
)


class PromptSearchDateError(ValueError):
    """Raised when an ``--after``/``--before`` value cannot be parsed."""

    def __init__(self, value: str) -> None:
        self.value = value
        super().__init__(
            f"Could not parse date {value!r}. Use an absolute date"
            f" ({_ABSOLUTE_HINT}) or a relative offset ({_RELATIVE_HINT})."
        )


def _timezone() -> tzinfo:
    """Return the configured timezone (indirection keeps tests deterministic)."""
    from sase.core.time import get_timezone

    return get_timezone()


def _now() -> datetime:
    """Return the current time in the configured timezone (test seam)."""
    return datetime.now(_timezone())


def parse_search_date(value: str) -> str:
    """Parse a search date filter into a comparable ``YYmmdd_HHMMSS`` anchor.

    Accepted forms, tried in order:

    - relative offsets ``Nd`` / ``Nw`` / ``Nm`` / ``Ny`` (days/weeks/months/years
      before now), anchored at the start of that day;
    - the SASE-native forms handled by :func:`parse_prune_date`
      (``YYYY-MM-DD``, ``YYmmdd``, ``YYmmdd_HHMMSS``);
    - a bare ``YYYYMM`` month, anchored at the first of that month.

    A 6-digit input is treated as ``YYmmdd`` first (the native format) and only
    falls back to ``YYYYMM`` when it is not a valid ``YYmmdd`` date, so
    ``260104`` reads as 2026-01-04 while ``202604`` reads as April 2026.

    Raises:
        PromptSearchDateError: the value matches none of the accepted forms.
    """
    raw = value.strip()
    if not raw:
        raise PromptSearchDateError(value)

    relative = _RELATIVE_RE.match(raw.lower())
    if relative:
        return _relative_anchor(int(relative.group(1)), relative.group(2))

    try:
        return parse_prune_date(raw)
    except PromptDateError:
        pass

    month = _YYYYMM_RE.match(raw)
    if month:
        year, mon = int(month.group(1)), int(month.group(2))
        if 1 <= mon <= 12:
            return datetime(year, mon, 1).strftime("%y%m%d_000000")

    raise PromptSearchDateError(value)


def _relative_anchor(amount: int, unit: str) -> str:
    """Return the ``YYmmdd_000000`` anchor *amount* units before now."""
    now = _now()
    if unit == "d":
        anchor = now - timedelta(days=amount)
    elif unit == "w":
        anchor = now - timedelta(weeks=amount)
    elif unit == "m":
        anchor = _subtract_months(now, amount)
    else:  # "y"
        anchor = _subtract_months(now, amount * 12)
    return anchor.strftime("%y%m%d_000000")


def _subtract_months(moment: datetime, months: int) -> datetime:
    """Subtract calendar *months* from *moment*, clamping the day-of-month."""
    index = moment.month - 1 - months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def resolve_archive_date(frontmatter: Mapping[str, Any], path: Path) -> str:
    """Resolve an archived prompt's comparable date via documented precedence.

    Precedence (highest first):

    1. frontmatter ``last_used`` then ``timestamp`` — archived prompt records
       carry these, so they are the most precise;
    2. the ``YYYYMM`` segment of the file's parent directory — the reliable
       fallback for the nested ``prompts/YYYYMM/`` layout;
    3. the file's mtime — last resort.
    """
    for key in ("last_used", "timestamp"):
        normalized = _normalize_date_value(frontmatter.get(key))
        if normalized is not None:
            return normalized

    path_date = _yyyymm_from_path(path)
    if path_date is not None:
        return path_date

    return _mtime_anchor(path)


def _normalize_date_value(value: Any) -> str | None:
    """Normalize a frontmatter date (str/date/datetime) to ``YYmmdd_HHMMSS``."""
    if isinstance(value, datetime):
        return value.strftime("%y%m%d_%H%M%S")
    if isinstance(value, date):
        return value.strftime("%y%m%d_000000")
    if isinstance(value, str) and value.strip():
        try:
            return parse_prune_date(value)
        except PromptDateError:
            return None
    return None


def _yyyymm_from_path(path: Path) -> str | None:
    """Return the first-of-month anchor from a nearby ``YYYYMM`` directory."""
    for parent in path.parents:
        segment = parent.name
        if not _PATH_YYYYMM_RE.match(segment):
            continue
        year, mon = int(segment[:4]), int(segment[4:])
        if not 1 <= mon <= 12:
            continue
        try:
            return datetime(year, mon, 1).strftime("%y%m%d_000000")
        except ValueError:
            continue
    return None


def _mtime_anchor(path: Path) -> str:
    """Return the file mtime as a ``YYmmdd_HHMMSS`` anchor, or the date floor."""
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return _DATE_FLOOR
    return datetime.fromtimestamp(mtime, _timezone()).strftime("%y%m%d_%H%M%S")


def hit_date(hit: PromptHit) -> str:
    """Return the comparable ``YYmmdd_HHMMSS`` date for *hit*.

    The single accessor the engine and renderers use, so the stored date
    representation can evolve without touching call sites.
    """
    return hit.date or _DATE_FLOOR
