"""Tests for optional GC survivor census telemetry."""

from __future__ import annotations

import logging
import threading
from typing import Any

import pytest

from sase.ace.tui.util import _gc_policy_census as census_module
from sase.ace.tui.util import _gc_policy_policy as policy_module
from sase.ace.tui.util import gc_policy
from sase.ace.tui.util.bounded_lru import BoundedLRUCache
from sase.ace.tui.util.gc_policy import GCPolicy
from tests.ace.tui.util._gc_policy_test_support import (
    Clock,
    Collector,
    Recorder,
    idle_policy,
)


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def collector() -> Collector:
    return Collector()


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


def _run_idle_census(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
) -> tuple[GCPolicy, list[dict[str, Any]]]:
    emitted: list[dict[str, Any]] = []
    policy = idle_policy(clock, collector, recorder)
    policy._census_emit = emitted.append
    assert policy.tick(clock.now) == "startup_freeze"
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    return policy, emitted


def test_census_off_by_default(
    clock: Clock, collector: Collector, recorder: Recorder
) -> None:
    emitted: list[dict[str, Any]] = []
    policy = idle_policy(clock, collector, recorder)
    policy._census_emit = emitted.append
    assert policy.tick(clock.now) == "startup_freeze"
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert emitted == []
    assert collector.collections == 2


def test_census_rate_limited_on_idle(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(gc_policy.ENV_CENSUS, "1")
    monkeypatch.setattr(policy_module, "CENSUS_INTERVAL_S", 100.0)
    monkeypatch.setattr(policy_module, "survivor_census_safe", lambda: True)
    emitted: list[dict[str, Any]] = []
    policy = idle_policy(clock, collector, recorder)
    policy._census_emit = emitted.append
    assert policy.tick(clock.now) == "startup_freeze"
    assert emitted == []
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert len(emitted) == 1
    assert emitted[0]["event"] == "tui_gc_census"
    assert "garbage_top" in emitted[0]
    assert "survivor_top" in emitted[0]
    assert emitted[0]["census_duration_s"] >= 0.0
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert len(emitted) == 1
    recorder.gen1 = 150
    clock.advance(61.0)
    assert policy.tick(clock.now) == "idle"
    assert len(emitted) == 2


def test_survivor_census_skipped_on_unsafe_python(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector.objects = [object(), object()]
    monkeypatch.setenv(gc_policy.ENV_CENSUS, "1")
    monkeypatch.setattr(policy_module, "CENSUS_INTERVAL_S", 100.0)
    monkeypatch.setattr(policy_module, "survivor_census_safe", lambda: False)
    _policy, emitted = _run_idle_census(clock, collector, recorder)
    assert collector.get_objects_calls == 0
    row = emitted[0]
    assert row["survivor_census"] == "skipped_unsafe_python"
    assert row["survivor_top"] == []
    assert row["survivor_count"] is None
    assert "garbage_top" in row


def test_survivor_census_runs_when_safe(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector.objects = [object(), object(), object()]
    monkeypatch.setenv(gc_policy.ENV_CENSUS, "1")
    monkeypatch.setattr(policy_module, "CENSUS_INTERVAL_S", 100.0)
    monkeypatch.setattr(policy_module, "survivor_census_safe", lambda: True)
    _policy, emitted = _run_idle_census(clock, collector, recorder)
    assert collector.get_objects_calls == 1
    row = emitted[0]
    assert row["survivor_census"] == "ok"
    assert row["survivor_count"] == len(collector.objects)


def test_survivor_census_skip_warning_logged_once(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv(gc_policy.ENV_CENSUS, "1")
    monkeypatch.setattr(policy_module, "CENSUS_INTERVAL_S", 100.0)
    monkeypatch.setattr(policy_module, "survivor_census_safe", lambda: False)
    emitted: list[dict[str, Any]] = []
    policy = idle_policy(clock, collector, recorder)
    policy._census_emit = emitted.append
    assert policy.tick(clock.now) == "startup_freeze"
    with caplog.at_level(logging.WARNING, logger=gc_policy.__name__):
        recorder.gen1 = 150
        clock.advance(61.0)
        assert policy.tick(clock.now) == "idle"
        recorder.gen1 = 150
        clock.advance(61.0)
        assert policy.tick(clock.now) == "idle"
        recorder.gen1 = 150
        clock.advance(61.0)
        assert policy.tick(clock.now) == "idle"
    assert len(emitted) == 2
    warnings = [
        record
        for record in caplog.records
        if record.levelno == logging.WARNING
        and "Survivor type census skipped" in record.message
    ]
    assert len(warnings) == 1


def test_top_types_uses_module_qualname() -> None:
    class _Probe:
        pass

    census = census_module.top_types([_Probe(), _Probe(), object()], n=10)
    assert census.total == 3
    assert census.top[0]["count"] == 2
    assert census.top[0]["bytes"] > 0
    assert census.bytes_total >= census.top[0]["bytes"]
    assert census.top[0]["type"].endswith(
        "test_top_types_uses_module_qualname.<locals>._Probe"
    )


def test_top_types_watchlist_includes_zero_counts() -> None:
    class _Probe:
        pass

    watch = frozenset(
        {
            "builtins.object",
            "missing.Type",
        }
    )
    census = census_module.top_types([object(), object()], n=1, watch=watch)
    by_type = {row["type"]: row for row in census.watch}
    assert by_type["missing.Type"] == {
        "type": "missing.Type",
        "count": 0,
        "bytes": 0,
    }
    assert by_type["builtins.object"]["count"] == 2
    assert by_type["builtins.object"]["bytes"] > 0


def test_census_payload_includes_owner_fields(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector.objects = [object(), object()]
    monkeypatch.setenv(gc_policy.ENV_CENSUS, "1")
    monkeypatch.setattr(policy_module, "CENSUS_INTERVAL_S", 100.0)
    monkeypatch.setattr(policy_module, "survivor_census_safe", lambda: True)
    _policy, emitted = _run_idle_census(clock, collector, recorder)
    row = emitted[0]
    assert "bytes" in row["survivor_top"][0]
    assert {item["type"] for item in row["survivor_watch"]} == set(
        gc_policy.CENSUS_WATCHLIST
    )
    assert row["survivor_bytes"] > 0
    assert row["garbage_bytes"] >= 0
    assert isinstance(row["known_caches"], list)
    names = {item["name"] for item in row["known_caches"]}
    assert (
        "sase.ace.tui.models._agent_loader_artifact_cache.ARTIFACT_SNAPSHOT_CACHE"
        in names
    )


def test_snapshot_cache_census_counts_records() -> None:
    class _Snapshot:
        def __init__(self, n: int) -> None:
            self.records = [object()] * n

    class _Cache:
        def __init__(self) -> None:
            self._lock = threading.Lock()
            self._max_entries = 8
            self._entries = {
                ("q", "cached", "full", "limit"): (("sig",), _Snapshot(4), None)
            }

    summary = census_module._snapshot_cache_census(_Cache())
    assert summary["entries"] == 1
    assert summary["max_entries"] == 8
    assert summary["record_total"] == 4
    assert summary["generations"][0]["records"] == 4


def test_lru_cache_census_counts_events() -> None:
    class _Entry:
        def __init__(self, n: int) -> None:
            self.events = tuple(range(n))

    cache = BoundedLRUCache[str, _Entry](8)
    cache["sase"] = _Entry(3)
    cache["bob"] = _Entry(5)
    summary = census_module._lru_cache_census(cache)
    assert summary["entries"] == 2
    assert summary["max_entries"] == 8
    assert summary["event_total"] == 8


__all__ = [
    "test_census_off_by_default",
    "test_census_payload_includes_owner_fields",
    "test_census_rate_limited_on_idle",
    "test_lru_cache_census_counts_events",
    "test_snapshot_cache_census_counts_records",
    "test_survivor_census_runs_when_safe",
    "test_survivor_census_skip_warning_logged_once",
    "test_survivor_census_skipped_on_unsafe_python",
    "test_top_types_uses_module_qualname",
    "test_top_types_watchlist_includes_zero_counts",
]
