"""Performance-correctness tests for ChangeSpec grouping.

Phase 5 polish: BY_DATE bucketing reads the latest TIMESTAMPS entry both
to assign a date bucket and to anchor the within-bucket sort.  The naive
implementation parses each CS's timestamps three times per refresh
(``keys_for_changespecs`` for the L0 label, ``walk_order`` for the date
anchor, ``enumerate_changespec_group_keys`` for the registry GC pass) —
under load that meant 3N parses per j/k refresh.  These tests pin the
per-refresh parse count at one-per-CS by counting calls into
:func:`latest_changespec_timestamp` from a monkey-patched module shim.
"""

from __future__ import annotations

from typing import Any

from sase.ace.changespec import TimestampEntry
from sase.ace.tui.models.changespec_groups import (
    ChangeSpecGroupingMode,
    build_changespec_tree,
    enumerate_changespec_group_keys,
)
from sase.ace.tui.models.changespec_groups import _buckets, _keys

from ._changespec_groups_helpers import _NOW, _cs


def _ts(timestamp: str) -> TimestampEntry:
    return TimestampEntry(timestamp=timestamp, event_type="STATUS", detail="x")


def _patch_parse_counter(monkeypatch: Any) -> list[int]:
    """Replace ``_parse_timestamp_value`` with a counting wrapper.

    Returns a list whose only element is the call count; the count is
    incremented on every individual entry parse, so a CS with three
    TIMESTAMPS entries contributes three to the count when its latest
    timestamp is computed.  The cache check is therefore "did we walk
    the same CS's entries more than once" — for a CS with one entry,
    the call count for that CS is exactly 1.
    """
    counter = [0]
    real = _buckets._parse_timestamp_value

    def _counted(raw: str) -> Any:
        counter[0] += 1
        return real(raw)

    monkeypatch.setattr(_buckets, "_parse_timestamp_value", _counted)
    return counter


def test_by_date_build_parses_each_cs_once(monkeypatch: Any) -> None:
    """One ``build_changespec_tree`` call ⇒ one parse per CS in BY_DATE."""
    counter = _patch_parse_counter(monkeypatch)
    css = [_cs(f"cs_{i}", timestamps=[_ts("260426_120000")]) for i in range(20)]

    build_changespec_tree(css, ChangeSpecGroupingMode.BY_DATE, now=_NOW)

    # 20 CSs * 1 timestamp entry each * 1 parse pass = 20 parses.
    # Without caching this would be 60 (bucket + walk-order + nothing
    # else, since the tree builder no longer re-enumerates keys).
    assert counter[0] == 20


def test_by_date_enumerate_parses_each_cs_once(monkeypatch: Any) -> None:
    """``enumerate_changespec_group_keys`` shares the same one-pass cache."""
    counter = _patch_parse_counter(monkeypatch)
    css = [_cs(f"cs_{i}", timestamps=[_ts("260426_120000")]) for i in range(15)]

    enumerate_changespec_group_keys(css, ChangeSpecGroupingMode.BY_DATE, now=_NOW)

    assert counter[0] == 15


def test_by_status_build_does_not_parse_timestamps(monkeypatch: Any) -> None:
    """BY_STATUS doesn't read TIMESTAMPS — the cache should never run."""
    counter = _patch_parse_counter(monkeypatch)
    css = [
        _cs(f"cs_{i}", status="WIP", timestamps=[_ts("260426_120000")])
        for i in range(10)
    ]

    build_changespec_tree(css, ChangeSpecGroupingMode.BY_STATUS, now=_NOW)

    # Status-mode bucketing reads ``cs.status`` only.  A non-zero count
    # would mean the BY_DATE precompute leaked into a non-date mode.
    assert counter[0] == 0


def test_precompute_cache_is_keyed_by_id_not_value() -> None:
    """Two CSs with identical timestamps still get cached separately.

    Sanity check on the cache keying: ``id(cs)`` rather than CS value /
    name means that mutating one CS's timestamps between refreshes does
    not silently re-use a sibling's cache slot.
    """
    a = _cs("a", timestamps=[_ts("260426_120000")])
    b = _cs("b", timestamps=[_ts("260426_120000")])

    cache = _buckets.precompute_latest_timestamps([a, b])

    assert id(a) in cache
    assert id(b) in cache
    assert cache[id(a)] == cache[id(b)]


def test_walk_order_uses_supplied_latest_map(monkeypatch: Any) -> None:
    """``walk_order`` must trust the supplied map and skip its own parse."""
    counter = _patch_parse_counter(monkeypatch)
    css = [_cs(f"cs_{i}", timestamps=[_ts("260426_120000")]) for i in range(5)]
    cache = _buckets.precompute_latest_timestamps(css)
    # Reset the counter — only the walk's parses should count below.
    counter[0] = 0
    keys = _keys.keys_for_changespecs(
        css, ChangeSpecGroupingMode.BY_DATE, _NOW, latest_map=cache
    )
    counter[0] = 0
    _keys.walk_order(css, keys, ChangeSpecGroupingMode.BY_DATE, latest_map=cache)
    assert counter[0] == 0
