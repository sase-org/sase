"""Tests for the core latest-version fetch/lookup helpers."""

from __future__ import annotations

import pytest

from sase.plugins.latest_cache import CachedLatest
from sase.updates import status as status_mod
from sase.updates.status import (
    make_cached_core_latest_lookup,
    make_core_latest_fetch_fn,
)


def test_cached_core_lookup_ignores_ttl_and_never_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        status_mod,
        "_read_latest_cache",
        lambda: {"sase": CachedLatest("9.9.9", 1.0)},
    )
    monkeypatch.setattr(
        status_mod,
        "_fetch_latest_version",
        lambda _dist: (_ for _ in ()).throw(
            AssertionError("cached lookup must not fetch")
        ),
    )

    lookup = make_cached_core_latest_lookup()

    assert lookup("sase") == CachedLatest("9.9.9", 1.0)
    assert lookup("sase-core-rs") is None


def test_forced_core_fetcher_always_fetches_and_writes_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[dict[str, CachedLatest]] = []
    monkeypatch.setattr(
        status_mod, "_read_latest_cache", lambda: {"sase": CachedLatest("1.0.0", 1.0)}
    )
    monkeypatch.setattr(status_mod, "_write_latest_cache", written.append)
    monkeypatch.setattr(status_mod, "_fetch_latest_version", lambda _dist: "2.0.0")

    fetch = make_core_latest_fetch_fn(100.0, force=True)

    assert fetch("sase") == "2.0.0"
    assert written[-1]["sase"] == CachedLatest("2.0.0", 100.0)


def test_unforced_core_fetcher_keeps_ttl_behavior(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[dict[str, CachedLatest]] = []
    monkeypatch.setattr(
        status_mod, "_read_latest_cache", lambda: {"sase": CachedLatest("1.0.0", 99.0)}
    )
    monkeypatch.setattr(status_mod, "_write_latest_cache", written.append)
    monkeypatch.setattr(
        status_mod,
        "_fetch_latest_version",
        lambda _dist: (_ for _ in ()).throw(
            AssertionError("fresh entries must not refetch")
        ),
    )
    monkeypatch.setattr(status_mod, "_latest_cache_is_fresh", lambda _item, _now: True)

    fetch = make_core_latest_fetch_fn(100.0, force=False)

    assert fetch("sase") == "1.0.0"
    assert written == []
