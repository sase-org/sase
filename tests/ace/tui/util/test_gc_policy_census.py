"""Tests for optional GC survivor census telemetry."""

from __future__ import annotations

from sase.ace.tui.models import _agent_stranded_cache as stranded_cache_module


import importlib
import logging
import sys
import threading
import weakref
from collections import OrderedDict
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.util import _gc_policy_census as census_module
from sase.ace.tui.util import _gc_policy_sweep as sweep_module
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


def test_census_watchlist_tracks_retained_skill_use_events() -> None:
    """heap_retainers: the census must track the top TUI-owned retainer type."""
    assert "sase.skills.use_log.SkillUseEvent" in set(gc_policy.CENSUS_WATCHLIST)


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
    assert collector.collections == 1


def test_census_rate_limited_on_idle(
    clock: Clock,
    collector: Collector,
    recorder: Recorder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(gc_policy.ENV_CENSUS, "1")
    monkeypatch.setattr(sweep_module, "CENSUS_INTERVAL_S", 100.0)
    monkeypatch.setattr(sweep_module, "survivor_census_safe", lambda: True)
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
    monkeypatch.setattr(sweep_module, "CENSUS_INTERVAL_S", 100.0)
    monkeypatch.setattr(sweep_module, "survivor_census_safe", lambda: False)
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
    monkeypatch.setattr(sweep_module, "CENSUS_INTERVAL_S", 100.0)
    monkeypatch.setattr(sweep_module, "survivor_census_safe", lambda: True)
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
    monkeypatch.setattr(sweep_module, "CENSUS_INTERVAL_S", 100.0)
    monkeypatch.setattr(sweep_module, "survivor_census_safe", lambda: False)
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
    monkeypatch.setattr(sweep_module, "CENSUS_INTERVAL_S", 100.0)
    monkeypatch.setattr(sweep_module, "survivor_census_safe", lambda: True)
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


def test_known_cache_census_reports_current_bounded_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_files = importlib.import_module("sase.core.artifact_file_explicit")
    artifact_reads = importlib.import_module("sase.ace.tui.artifact_reads")
    memory_reads = importlib.import_module("sase.ace.tui.memory_reads")
    bead_touches = importlib.import_module("sase.ace.tui._bead_touches_loader")
    projected_record = importlib.import_module(
        "sase.ace.tui.models._projected_record_detail"
    )

    class _Entry:
        def __init__(self, count: int) -> None:
            self.events = tuple(range(count))

    def _result_cache(counts: dict[str, int]) -> BoundedLRUCache[str, _Entry]:
        cache: BoundedLRUCache[str, _Entry] = BoundedLRUCache(128)
        for key, count in counts.items():
            cache[key] = _Entry(count)
        return cache

    association_cache: OrderedDict[str, Any] = OrderedDict(
        selected=SimpleNamespace(rows=(object(), object()))
    )
    monkeypatch.setattr(
        artifact_files, "_artifact_file_association_cache", association_cache
    )
    monkeypatch.setattr(
        artifact_reads,
        "_artifact_reads_cache",
        _result_cache({"selected": 3}),
    )
    monkeypatch.setattr(
        artifact_reads,
        "_artifact_reads_context_cache",
        _result_cache({"session": 4}),
    )
    monkeypatch.setattr(
        memory_reads,
        "_memory_reads_cache",
        _result_cache({"selected": 5}),
    )
    monkeypatch.setattr(
        memory_reads,
        "_memory_reads_context_cache",
        _result_cache({"session": 6}),
    )
    monkeypatch.setattr(
        bead_touches,
        "_bead_touches_cache",
        _result_cache({"selected": 7}),
    )
    monkeypatch.setattr(
        bead_touches,
        "_bead_touches_context_cache",
        _result_cache({"session": 8}),
    )
    stranded_cache = SimpleNamespace(
        _entries={
            "project": SimpleNamespace(
                snapshot=SimpleNamespace(
                    report=SimpleNamespace(
                        verdicts=(object(), object()),
                        stranded_ids=("bead-1",),
                        blocked_ids=("bead-2",),
                    ),
                    titles={"bead-1": "one", "bead-2": "two", "parent": "p"},
                ),
                verdict_index={"bead-1": object(), "bead-2": object()},
            )
        },
        _max_entries=stranded_cache_module._CACHE_MAX_ENTRIES,
        _lock=threading.RLock(),
    )
    monkeypatch.setattr(stranded_cache_module, "_STRANDED_REPORT_CACHE", stranded_cache)

    class _HydratedRow:
        record_shape = "full"

    class _CompactRow:
        record_shape = "list"

    hydrated_row = _HydratedRow()
    compact_row = _CompactRow()
    detail_owner = OrderedDict(
        (
            (id(hydrated_row), weakref.ref(hydrated_row)),
            (id(compact_row), weakref.ref(compact_row)),
        )
    )
    monkeypatch.setattr(projected_record, "_detail_owner", detail_owner)

    rows = {row["name"]: row for row in census_module.known_cache_census()}
    association = rows[
        "sase.core.artifact_file_explicit._artifact_file_association_cache"
    ]
    assert association["status"] == "present"
    assert association["entries"] == 1
    assert association["row_total"] == 2
    assert association["max_entries"] == 128
    assert association["max_rows_per_entry"] == 1024
    assert association["max_bytes_per_entry"] == 256 * 1024

    expected_counts = {
        "sase.ace.tui.artifact_reads._artifact_reads_cache": 3,
        "sase.ace.tui.artifact_reads._artifact_reads_context_cache": 4,
        "sase.ace.tui.memory_reads._memory_reads_cache": 5,
        "sase.ace.tui.memory_reads._memory_reads_context_cache": 6,
        "sase.ace.tui._bead_touches_loader._bead_touches_cache": 7,
        "sase.ace.tui._bead_touches_loader._bead_touches_context_cache": 8,
    }
    for name, count in expected_counts.items():
        row = rows[name]
        assert row["status"] == "present"
        assert row["entries"] == 1
        assert row["max_entries"] == 128
        assert row["event_total"] == count
        assert row["max_rows_per_entry"] == 50
        assert row["max_retained_rows"] == 128 * 50

    stranded = rows["sase.ace.tui.models._agent_stranded_cache._STRANDED_REPORT_CACHE"]
    assert stranded["status"] == "present"
    assert stranded["entries"] == 1
    assert stranded["max_entries"] == stranded_cache_module._CACHE_MAX_ENTRIES
    assert stranded["candidate_verdict_total"] == 2
    assert stranded["title_total"] == 3
    assert stranded["verdict_index_total"] == 2
    assert stranded["stranded_id_total"] == 1
    assert stranded["blocked_id_total"] == 1

    detail = rows["sase.ace.tui.models._projected_record_detail._detail_owner"]
    assert detail["status"] == "present"
    assert detail["entries"] == 2
    assert detail["live_rows"] == 2
    assert detail["hydrated_rows"] == 1
    assert detail["max_entries"] == 2

    names = set(rows)
    assert "sase.ace.tui.artifact_reads._artifact_reads_snapshot_cache" not in names
    assert "sase.ace.tui._bead_touches_loader._bead_touches_snapshot_cache" not in names
    # heap_retainers removed the whole-file skill-use snapshot cache: only
    # the bounded per-agent tables may retain SkillUseEvent rows.
    assert "sase.ace.tui.skill_uses._skill_uses_snapshot_cache" not in names


def test_missing_expected_cache_is_not_reported_as_a_zero_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "sase.ace.tui.artifact_reads"
    monkeypatch.setitem(sys.modules, module_name, ModuleType(module_name))

    rows = {
        row["name"]: row
        for row in census_module.known_cache_census()
        if row["name"].startswith(f"{module_name}.")
    }
    assert rows[f"{module_name}._artifact_reads_cache"]["status"] == (
        "missing_expected_owner"
    )
    assert rows[f"{module_name}._artifact_reads_context_cache"]["status"] == (
        "missing_expected_owner"
    )
    assert "event_total" not in rows[f"{module_name}._artifact_reads_cache"]


def test_known_cache_census_does_not_import_unloaded_owners(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module_name = "sase.ace.tui._bead_touches_loader"
    monkeypatch.delitem(sys.modules, module_name, raising=False)

    rows = {
        row["name"]: row
        for row in census_module.known_cache_census()
        if row["name"].startswith(f"{module_name}.")
    }
    assert module_name not in sys.modules
    assert rows[f"{module_name}._bead_touches_cache"]["status"] == (
        "module_not_imported"
    )


__all__ = [
    "test_census_off_by_default",
    "test_census_payload_includes_owner_fields",
    "test_census_rate_limited_on_idle",
    "test_lru_cache_census_counts_events",
    "test_known_cache_census_reports_current_bounded_owners",
    "test_known_cache_census_does_not_import_unloaded_owners",
    "test_missing_expected_cache_is_not_reported_as_a_zero_owner",
    "test_snapshot_cache_census_counts_records",
    "test_survivor_census_runs_when_safe",
    "test_survivor_census_skip_warning_logged_once",
    "test_survivor_census_skipped_on_unsafe_python",
    "test_top_types_uses_module_qualname",
    "test_top_types_watchlist_includes_zero_counts",
]
