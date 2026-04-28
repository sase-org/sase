"""``ChangeSpecGroupingMode`` and date/status bucket helpers."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import Enum

from sase.ace.changespec import ChangeSpec

#: Bucket used when no TIMESTAMPS entry is present or none parse cleanly.
_EARLIER = "Earlier"


class ChangeSpecGroupingMode(Enum):
    """How the CLs tab is bucketed at L0.

    * ``FLAT``: no group rows; preserve the existing filtered list order.
    * ``BY_PROJECT``: L0 is the project name, L1 is the sibling root
      shared by ``foobar_1`` / ``foobar_2`` style suffixed siblings.
    * ``BY_DATE``: L0 only — date bucket from the latest TIMESTAMPS entry.
    * ``BY_STATUS``: L0 only — bucket from the literal ``status`` field.
    """

    FLAT = "flat"
    BY_PROJECT = "by_project"
    BY_DATE = "by_date"
    BY_STATUS = "by_status"


_DATE_BUCKETS: tuple[str, ...] = ("Today", "Yesterday", "This Week", "Earlier")

# Lifecycle order for known base statuses.  Anything else sorts after
# this list, alphabetically by exact text — that keeps unfamiliar /
# suffixed labels stable instead of randomly shuffled.
_STATUS_LIFECYCLE: tuple[str, ...] = (
    "WIP",
    "Draft",
    "Ready",
    "Mailed",
    "Submitted",
    "Reverted",
    "Archived",
)


def _base_status(status: str) -> str:
    """Strip any ``" - (...)"`` annotation suffix so ``"Ready - (!: X)"``
    sorts with the rest of the ``Ready`` lifecycle slot."""
    return status.split(" - ", 1)[0].strip()


def _parse_timestamp_value(raw: str) -> datetime | None:
    """Best-effort parse of a ``TimestampEntry.timestamp`` string.

    Supports:

    * ``"YYMMDD_HHMMSS"`` (current canonical format).
    * ``"YYYY-MM-DD HH:MM:SS"`` (legacy format kept around for old files).

    Anything that doesn't match either returns ``None`` so the caller can
    decide how to handle malformed data.
    """
    if not raw:
        return None
    raw = raw.strip()
    if re.fullmatch(r"\d{6}_\d{6}", raw):
        try:
            return datetime.strptime(raw, "%y%m%d_%H%M%S")
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", raw):
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return None


def latest_changespec_timestamp(cs: ChangeSpec) -> datetime | None:
    """Return the most recent parseable TIMESTAMPS entry, or ``None``.

    Walks the full ``cs.timestamps`` list rather than trusting input
    order — file-on-disk ordering is "append on event", but malformed or
    out-of-order entries shouldn't silently drop a CL into ``Earlier``.
    """
    if not cs.timestamps:
        return None
    latest: datetime | None = None
    for entry in cs.timestamps:
        parsed = _parse_timestamp_value(entry.timestamp)
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    return latest


def date_bucket_for_changespec(cs: ChangeSpec, now: datetime) -> str:
    """Map ``cs``'s latest TIMESTAMPS entry to a date bucket.

    Buckets compare on calendar dates in ``now``'s local frame:

    - ``Today``: same calendar date as ``now``.
    - ``Yesterday``: the day before ``now``.
    - ``This Week``: within the prior six days, but not Today/Yesterday.
    - ``Earlier``: anything older, plus CLs with no parseable timestamps.
    """
    latest = latest_changespec_timestamp(cs)
    if latest is None:
        return _EARLIER
    today = now.date()
    when = latest.date()
    if when == today:
        return "Today"
    if when == today - timedelta(days=1):
        return "Yesterday"
    if when > today - timedelta(days=7):
        return "This Week"
    return _EARLIER


def status_bucket_for_changespec(cs: ChangeSpec) -> str:
    """Map ``cs.status`` to a status bucket.

    Returns the literal ``status`` string so the heading text matches
    what is in the file (including any ``" - (!: ...)"`` annotation).
    Sorting is handled separately by :func:`status_sort_index`.
    """
    return cs.status or ""


def date_bucket_sort_index(bucket: str) -> int:
    """Fixed bucket ordering for ``BY_DATE`` L0 keys.

    Unknown bucket names sort last so a stale label can never silently
    clobber a valid one.
    """
    try:
        return _DATE_BUCKETS.index(bucket)
    except ValueError:
        return len(_DATE_BUCKETS)


def status_sort_index(status: str) -> tuple[int, str]:
    """Lifecycle-order sort key for ``BY_STATUS`` L0 keys.

    Falls back to alphabetic ordering on the exact status text for
    unknown / suffixed values so two ``Ready - (...)`` variants don't
    randomly swap between refreshes.
    """
    base = _base_status(status)
    try:
        return (_STATUS_LIFECYCLE.index(base), status)
    except ValueError:
        return (len(_STATUS_LIFECYCLE), status)
