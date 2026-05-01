"""``ChangeSpecGroupingMode`` and date/status bucket helpers."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from enum import Enum

from sase.ace.changespec import ChangeSpec

from ..date_subgroups import (
    NO_TIMESTAMP_LABEL,
    day_subgroup_label,
    day_subgroup_sort_key,
    four_hour_window_label,
    four_hour_window_sort_key,
    week_subgroup_label,
    week_subgroup_sort_key,
)

#: Bucket used when no TIMESTAMPS entry is present or none parse cleanly.
_EARLIER = "Earlier"


class ChangeSpecGroupingMode(Enum):
    """How the CLs tab is bucketed at L0.

    * ``BY_PROJECT``: L0 is the project name, L1 is the sibling root
      shared by ``foobar_1`` / ``foobar_2`` style suffixed siblings.
    * ``BY_DATE``: L0 date bucket from the latest TIMESTAMPS entry,
      with conditional L1 subgroups for yesterday / this week / earlier.
    * ``BY_STATUS``: L0 only — bucket from the literal ``status`` field.
    """

    BY_PROJECT = "by_project"
    BY_DATE = "by_date"
    BY_STATUS = "by_status"


_DATE_BUCKETS: tuple[str, ...] = ("Today", "Yesterday", "This Week", "Earlier")

# Display order for the ``BY_STATUS`` group; surfaces actionable buckets
# first (``Mailed`` = awaiting response, ``Ready`` = next to mail) and
# keeps terminal states at the bottom.  Anything else sorts after this
# list, alphabetically by exact text — that keeps unfamiliar / suffixed
# labels stable instead of randomly shuffled.
_STATUS_DISPLAY_ORDER: tuple[str, ...] = (
    "Mailed",
    "Ready",
    "WIP",
    "Draft",
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


#: Per-refresh cache mapping ``id(cs)`` → latest parsed TIMESTAMPS value.
#: Populated once at the entry point of a tree build / key enumeration so
#: BY_DATE bucketing and date-anchored sorting share a single parse pass
#: instead of re-walking ``cs.timestamps`` two or three times per CS.
LatestTimestampMap = dict[int, "datetime | None"]


def precompute_latest_timestamps(
    changespecs: list[ChangeSpec],
) -> LatestTimestampMap:
    """Build a per-CS timestamp cache for one tree build / enumeration.

    Keys are ``id(cs)`` so the cache is safe to reuse across functions
    that share the same CS list within a single refresh, but does not
    leak across refreshes (the next call rebuilds with fresh ids).
    """
    return {id(cs): latest_changespec_timestamp(cs) for cs in changespecs}


def date_bucket_for_changespec(
    cs: ChangeSpec,
    now: datetime,
    latest_map: LatestTimestampMap | None = None,
) -> str:
    """Map ``cs``'s latest TIMESTAMPS entry to a date bucket.

    Buckets compare on calendar dates in ``now``'s local frame:

    - ``Today``: same calendar date as ``now``.
    - ``Yesterday``: the day before ``now``.
    - ``This Week``: within the prior six days, but not Today/Yesterday.
    - ``Earlier``: anything older, plus CLs with no parseable timestamps.

    Pass *latest_map* (from :func:`precompute_latest_timestamps`) when
    bucketing many CSs in the same refresh to skip a redundant parse.
    """
    if latest_map is not None and id(cs) in latest_map:
        latest = latest_map[id(cs)]
    else:
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


def latest_from_map(
    cs: ChangeSpec,
    latest_map: LatestTimestampMap | None = None,
) -> datetime | None:
    """Return *cs*'s latest timestamp, using *latest_map* when present."""
    if latest_map is not None and id(cs) in latest_map:
        return latest_map[id(cs)]
    return latest_changespec_timestamp(cs)


def date_subgroup_for_changespec(
    cs: ChangeSpec,
    date_bucket: str,
    latest_map: LatestTimestampMap | None = None,
) -> str:
    """Return the optional BY_DATE L1 subgroup label for *cs*.

    ``Today`` remains flat.  ``Yesterday`` groups by 4-hour windows,
    ``This Week`` by calendar day, and ``Earlier`` by Monday-start week;
    CLs without a parseable TIMESTAMPS entry land in
    :data:`NO_TIMESTAMP_LABEL`.
    """
    latest = latest_from_map(cs, latest_map)
    if date_bucket == "Today":
        return ""
    if latest is None:
        return NO_TIMESTAMP_LABEL if date_bucket == _EARLIER else ""
    if date_bucket == "Yesterday":
        return four_hour_window_label(latest)
    if date_bucket == "This Week":
        return day_subgroup_label(latest)
    if date_bucket == _EARLIER:
        return week_subgroup_label(latest)
    return ""


def date_subgroup_sort_key(
    date_bucket: str,
    subgroup: str,
    latest: datetime | None,
) -> tuple[int, int]:
    """Sort key for BY_DATE L1 subgroups.

    The key is neutral for flat buckets, newest-first for real date
    subgroups, and places ``(no timestamp)`` after all dated ``Earlier``
    weeks.
    """
    if not subgroup:
        return (0, 0)
    if date_bucket == _EARLIER and subgroup == NO_TIMESTAMP_LABEL:
        return (2, 0)
    if latest is None:
        return (1, 0)
    if date_bucket == "Yesterday":
        return four_hour_window_sort_key(subgroup)
    if date_bucket == "This Week":
        return day_subgroup_sort_key(latest)
    if date_bucket == _EARLIER:
        return week_subgroup_sort_key(latest)
    return (1, 0)


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
    """Display-order sort key for ``BY_STATUS`` L0 keys.

    See :data:`_STATUS_DISPLAY_ORDER` for the rationale behind the
    ordering.  Falls back to alphabetic ordering on the exact status text
    for unknown / suffixed values so two ``Ready - (...)`` variants don't
    randomly swap between refreshes.
    """
    base = _base_status(status)
    try:
        return (_STATUS_DISPLAY_ORDER.index(base), status)
    except ValueError:
        return (len(_STATUS_DISPLAY_ORDER), status)
