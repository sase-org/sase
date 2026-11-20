"""Test gc telemetry heartbeat tests."""

from __future__ import annotations

import gc
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.util.gc_telemetry import (
    GCTelemetry,
    default_executor_heartbeat_fields,
    register_heartbeat_provider,
    unregister_heartbeat_provider,
)
from ._gc_telemetry_test_support import (
    Clock,
    clock as clock,
    emitted as emitted,
    record,
    telemetry as telemetry,
)

__all__ = ("clock", "emitted", "telemetry")


def _write_proc_files(
    tmp_path: Path, *, rss_kb: int, swap_kb: int, major_faults: int = 42
) -> None:
    (tmp_path / "status").write_text(
        f"Name:\tsase\nVmRSS:\t{rss_kb} kB\nVmSwap:\t{swap_kb} kB\n",
        encoding="utf-8",
    )
    (tmp_path / "stat").write_text(
        f"1 (sase) S 0 0 0 0 0 0 0 0 {major_faults} 0 0 0 0 0 0 0 0 0 12345",
        encoding="utf-8",
    )


def test_heartbeat_reports_and_resets_young_notable_pauses(
    telemetry: GCTelemetry,
    emitted: list[dict[str, Any]],
    clock: Clock,
) -> None:
    record(telemetry, 0, 0.010)  # below NOTABLE_PAUSE_S: not counted
    record(telemetry, 0, 0.080)
    record(telemetry, 1, 0.120)
    record(telemetry, 1, 0.700)  # also earns a tui_gc_pause row
    record(telemetry, 2, 0.900)  # full collections never count as young

    telemetry._write_heartbeat(clock.now)
    young = emitted[-1]["gc_young_notable"]
    assert young["count"] == 3
    assert young["total_s"] == pytest.approx(0.9)
    assert young["max_s"] == pytest.approx(0.7)

    clock.advance(300.0)
    telemetry._write_heartbeat(clock.now)
    assert emitted[-1]["gc_young_notable"] == {
        "count": 0,
        "total_s": 0.0,
        "max_s": 0.0,
    }


def test_heartbeat_totals_stay_exact_despite_rate_cap(
    emitted: list[dict[str, Any]], clock: Clock, tmp_path: Path
) -> None:
    tel = GCTelemetry(
        app_instance_id="test-instance",
        monotonic=clock,
        emit=emitted.append,
        rate_limit_per_min=1,
        status_path=tmp_path / "missing-status",
        stat_path=tmp_path / "missing-stat",
    )
    for _ in range(3):
        record(tel, 2, 0.4)
    rows = [row for row in emitted if row["event"] == "tui_gc_pause"]
    assert rows == []
    tel._write_heartbeat(clock.now)
    heartbeats = [row for row in emitted if row["event"] == "tui_memory_heartbeat"]
    assert len(heartbeats) == 1
    assert heartbeats[0]["gc_generations"]["2"]["count"] == 3
    assert heartbeats[0]["gc_generations"]["2"]["total_s"] == pytest.approx(1.2)


def test_heartbeat_parses_proc_and_tracks_fault_delta(
    emitted: list[dict[str, Any]], clock: Clock, tmp_path: Path
) -> None:
    _write_proc_files(tmp_path, rss_kb=1523, swap_kb=11)
    tel = GCTelemetry(
        app_instance_id="test-instance",
        monotonic=clock,
        emit=emitted.append,
        status_path=tmp_path / "status",
        stat_path=tmp_path / "stat",
    )
    tel._write_heartbeat(clock.now)
    row = emitted[-1]
    assert row["event"] == "tui_memory_heartbeat"
    assert row["rss_bytes"] == 1523 * 1024
    assert row["vmswap_bytes"] == 11 * 1024
    assert row["major_faults"] == 42
    assert row["major_faults_delta"] is None
    assert row["uptime_s"] == pytest.approx(0.0)
    # Live collector counters can move between the heartbeat write and this
    # assertion, so only the shape is pinned here.
    assert len(row["gc_count"]) == 3
    assert all(isinstance(value, int) for value in row["gc_count"])
    assert row["gc_threshold"] == list(gc.get_threshold())
    assert isinstance(row["gc_freeze_count"], int)
    assert tel.latest_rss == 1523 * 1024

    clock.advance(300.0)
    tel._write_heartbeat(clock.now)
    assert emitted[-1]["major_faults_delta"] == 0
    assert emitted[-1]["uptime_s"] == pytest.approx(300.0)


def test_pressure_sampler_caches_swap_and_recent_major_fault_rate(
    clock: Clock, tmp_path: Path
) -> None:
    _write_proc_files(tmp_path, rss_kb=100, swap_kb=0, major_faults=42)
    tel = GCTelemetry(
        app_instance_id="test-instance",
        monotonic=clock,
        status_path=tmp_path / "status",
        stat_path=tmp_path / "stat",
    )
    tel._sample_memory_pressure(clock.now)
    initial = tel.memory_pressure_snapshot()
    assert initial is not None
    assert initial["vmswap_bytes"] == 0
    assert initial["vmswap_growth_bytes"] is None
    assert initial["major_faults_per_s"] == 0.0

    _write_proc_files(tmp_path, rss_kb=200, swap_kb=16, major_faults=142)
    clock.advance(5.0)
    tel._sample_memory_pressure(clock.now)
    sample = tel.memory_pressure_snapshot()
    assert sample is not None
    assert sample["vmswap_bytes"] == 16 * 1024
    assert sample["vmswap_growth_bytes"] == 16 * 1024
    assert sample["major_faults_per_s"] == pytest.approx(20.0)
    assert sample["sample_age_s"] == 0.0
    assert tel.latest_rss == 200 * 1024

    # A residual level that stays flat reports zero growth.
    clock.advance(5.0)
    tel._sample_memory_pressure(clock.now)
    steady = tel.memory_pressure_snapshot()
    assert steady is not None
    assert steady["vmswap_bytes"] == 16 * 1024
    assert steady["vmswap_growth_bytes"] == 0


def test_heartbeat_window_spans_since_previous_heartbeat(
    emitted: list[dict[str, Any]], clock: Clock, tmp_path: Path
) -> None:
    tel = GCTelemetry(
        app_instance_id="test-instance",
        monotonic=clock,
        emit=emitted.append,
        status_path=tmp_path / "missing-status",
        stat_path=tmp_path / "missing-stat",
    )
    clock.advance(300.0)
    tel._write_heartbeat(clock.now)
    assert emitted[-1]["window_s"] == pytest.approx(300.0)
    assert emitted[-1]["uptime_s"] == pytest.approx(300.0)

    clock.advance(120.0)
    tel._write_heartbeat(clock.now)
    assert emitted[-1]["window_s"] == pytest.approx(120.0)
    assert emitted[-1]["uptime_s"] == pytest.approx(420.0)


def test_heartbeat_degrades_cleanly_without_proc(
    telemetry: GCTelemetry,
    emitted: list[dict[str, Any]],
    clock: Clock,
) -> None:
    telemetry._write_heartbeat(clock.now)
    row = emitted[-1]
    assert row["event"] == "tui_memory_heartbeat"
    assert row["rss_bytes"] is None
    assert row["vmswap_bytes"] is None
    assert row["major_faults"] is None
    assert row["major_faults_delta"] is None
    assert row["gc_generations"] == {}
    assert telemetry.latest_rss is None


def test_default_executor_heartbeat_gauge_reports_backlog() -> None:
    import queue
    from types import SimpleNamespace

    work_queue: queue.SimpleQueue[object] = queue.SimpleQueue()
    work_queue.put(object())
    executor = SimpleNamespace(
        _max_workers=1, _threads={object()}, _work_queue=work_queue
    )
    fields = default_executor_heartbeat_fields(
        SimpleNamespace(_default_executor=executor)
    )
    assert fields == {
        "default_executor_workers": 1,
        "default_executor_threads": 1,
        "default_executor_queue_depth": 1,
        "default_executor_saturated": True,
    }


def test_default_executor_heartbeat_gauge_reports_no_executor() -> None:
    from types import SimpleNamespace

    assert default_executor_heartbeat_fields(
        SimpleNamespace(_default_executor=None)
    ) == {
        "default_executor_workers": 0,
        "default_executor_threads": 0,
        "default_executor_queue_depth": 0,
        "default_executor_saturated": False,
    }


def test_default_executor_heartbeat_gauge_reports_missing_loop() -> None:
    assert default_executor_heartbeat_fields(None) == {
        "default_executor_workers": None,
        "default_executor_threads": None,
        "default_executor_queue_depth": None,
        "default_executor_saturated": None,
    }


def test_heartbeat_providers_contribute_without_clobbering_core(
    telemetry: GCTelemetry,
    emitted: list[dict[str, Any]],
    clock: Clock,
) -> None:
    register_heartbeat_provider("watchdog", lambda: {"hitch_seconds": 1.5})
    register_heartbeat_provider("greedy", lambda: {"event": "forged", "extra": True})
    telemetry._write_heartbeat(clock.now)
    row = emitted[-1]
    assert row["hitch_seconds"] == 1.5
    assert row["event"] == "tui_memory_heartbeat"
    assert row["extra"] is True

    unregister_heartbeat_provider("watchdog")
    unregister_heartbeat_provider("greedy")

    def _boom() -> dict[str, Any]:
        raise RuntimeError("boom")

    register_heartbeat_provider("exploding", _boom)
    telemetry._write_heartbeat(clock.now)
    assert emitted[-1]["event"] == "tui_memory_heartbeat"
    unregister_heartbeat_provider("exploding")


def test_heartbeat_includes_stats_blocks_and_python_version(
    telemetry: GCTelemetry,
    emitted: list[dict[str, Any]],
    clock: Clock,
) -> None:
    telemetry._write_heartbeat(clock.now)
    row = emitted[-1]
    assert isinstance(row["python_version"], str)
    assert row["python_version"]
    assert row["gc_stats"] is None or isinstance(row["gc_stats"], list)
    assert row["allocated_blocks"] is None or isinstance(row["allocated_blocks"], int)
