"""Shard a topic search into sub-queries that each fit GitHub's result cap.

GitHub's REST search API hard-caps any one query at 1000 results. When the
topic search reports more than that, the fetch driver walks the shard tree
built here: stable ``stars:`` buckets first, then ``created:`` date ranges when
a single star value still overflows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sase.plugins._github_source_gh import GH_SEARCH_QUERY

#: Stable first-level star shards. These never become the cache key
#: (``GH_SEARCH_QUERY`` stays ``topic:sase--plugin``); adding a high-end
#: bucket later does not invalidate previously cached catalogs.
_STAR_BUCKETS: tuple[tuple[int, int | None], ...] = (
    (0, 0),
    (1, 1),
    (2, 4),
    (5, 9),
    (10, 24),
    (25, 49),
    (50, 99),
    (100, 249),
    (250, 499),
    (500, 999),
    (1000, None),
)

#: Floor used when bisecting an unbounded ``created:<DATE`` prefix.
_CREATED_FLOOR = date(2008, 1, 1)


@dataclass(frozen=True)
class _StarRange:
    lo: int
    hi: int | None

    def qualifier(self) -> str:
        if self.hi is None:
            return f"stars:>={self.lo}"
        if self.lo == self.hi:
            return f"stars:{self.lo}"
        return f"stars:{self.lo}..{self.hi}"

    def split(self) -> tuple[_StarRange, _StarRange] | None:
        if self.hi is None:
            mid = self.lo * 2 if self.lo > 0 else 1
            if mid <= self.lo:
                return None
            return _StarRange(self.lo, mid - 1), _StarRange(mid, None)
        if self.lo >= self.hi:
            return None
        mid = (self.lo + self.hi) // 2
        return _StarRange(self.lo, mid), _StarRange(mid + 1, self.hi)


@dataclass(frozen=True)
class _CreatedRange:
    start: date | None
    end: date | None

    def qualifier(self) -> str:
        start, end = self.start, self.end
        if start is None and end is None:
            return ""
        if start is None and end is not None:
            return f"created:<{end.isoformat()}"
        if start is not None and end is None:
            return f"created:>={start.isoformat()}"
        if start is None or end is None:
            return ""
        last = end - timedelta(days=1)
        if last == start:
            return f"created:{start.isoformat()}"
        return f"created:{start.isoformat()}..{last.isoformat()}"

    def split(self, *, today: date) -> tuple[_CreatedRange, _CreatedRange] | None:
        if self.start is None and self.end is None:
            mid = date(2020, 1, 1)
            return _CreatedRange(None, mid), _CreatedRange(mid, None)
        if self.start is None:
            if self.end is None:
                return None
            return _split_created_prefix(self.end)
        if self.end is None:
            return _split_created_suffix(self.start, today=today)
        days = (self.end - self.start).days
        if days <= 1:
            return None
        mid = self.start + timedelta(days=days // 2)
        if mid <= self.start or mid >= self.end:
            return None
        return _CreatedRange(self.start, mid), _CreatedRange(mid, self.end)


@dataclass(frozen=True)
class Shard:
    """One sub-query of the topic search, narrowed by stars and/or creation date."""

    stars: _StarRange | None = None
    created: _CreatedRange | None = None

    def query(self) -> str:
        parts = [GH_SEARCH_QUERY]
        if self.stars is not None:
            parts.append(self.stars.qualifier())
        if self.created is not None:
            qualifier = self.created.qualifier()
            if qualifier:
                parts.append(qualifier)
        return " ".join(parts)

    def children(self, *, today: date) -> list[Shard] | None:
        if self.stars is None and self.created is None:
            return [Shard(stars=_StarRange(lo, hi)) for lo, hi in _STAR_BUCKETS]
        if self.stars is not None:
            star_split = self.stars.split()
            if star_split is not None:
                low, high = star_split
                return [
                    Shard(stars=low, created=self.created),
                    Shard(stars=high, created=self.created),
                ]
        created = (
            self.created if self.created is not None else _CreatedRange(None, None)
        )
        created_split = created.split(today=today)
        if created_split is None:
            return None
        earlier, later = created_split
        return [
            Shard(stars=self.stars, created=earlier),
            Shard(stars=self.stars, created=later),
        ]


def _split_created_prefix(end: date) -> tuple[_CreatedRange, _CreatedRange] | None:
    if end <= _CREATED_FLOOR + timedelta(days=1):
        mid = end - timedelta(days=1)
        if mid <= _CREATED_FLOOR:
            return None
        return _CreatedRange(None, mid), _CreatedRange(mid, end)
    span_days = (end - _CREATED_FLOOR).days
    mid = _CREATED_FLOOR + timedelta(days=max(span_days // 2, 1))
    if mid >= end:
        mid = end - timedelta(days=1)
    if mid <= _CREATED_FLOOR:
        return None
    return _CreatedRange(None, mid), _CreatedRange(mid, end)


def _split_created_suffix(
    start: date, *, today: date
) -> tuple[_CreatedRange, _CreatedRange] | None:
    horizon = max(today + timedelta(days=1), start + timedelta(days=2))
    mid_days = max((horizon - start).days // 2, 1)
    mid = start + timedelta(days=mid_days)
    if mid <= start:
        return None
    if mid >= horizon:
        mid = start + timedelta(days=1)
    return _CreatedRange(start, mid), _CreatedRange(mid, None)
