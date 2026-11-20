"""Test gc telemetry collection tests."""

from __future__ import annotations

import gc
import inspect
import os
from typing import Any

import pytest

from sase.ace.tui.util import _gc_telemetry_lifecycle as lifecycle_module
from sase.ace.tui.util import gc_telemetry
from sase.ace.tui.util.gc_telemetry import (
    GCTelemetry,
    gc_trigger,
    note_last_input_mono,
    recent_collections,
)
from ._gc_telemetry_test_support import (
    Clock,
    clock as clock,
    emitted as emitted,
    record,
    telemetry as telemetry,
)

__all__ = ("clock", "emitted", "telemetry")


def test_queue_keeps_gen2_and_slow_collections_only(
    telemetry: GCTelemetry,
) -> None:
    record(telemetry, 0, 0.005)
    record(telemetry, 1, 0.010)
    assert len(telemetry._queue) == 0
    # Short young collections still count toward the heartbeat totals.
    assert telemetry._gen_counts[0] == 1
    assert telemetry._gen_counts[1] == 1

    # A notable young pause below the row threshold rolls into the heartbeat
    # counters instead of writing a row.
    record(telemetry, 1, 0.060)
    assert len(telemetry._queue) == 0
    assert telemetry._young_notable_count == 1

    record(telemetry, 1, gc_telemetry.YOUNG_PAUSE_ROW_MIN_S)
    record(telemetry, 2, 0.001)
    assert [row["generation"] for row in telemetry._queue] == [1, 2]
    assert telemetry._gen_counts[1] == 3
    assert telemetry._gen_counts[2] == 1
    assert telemetry._young_notable_count == 2


def test_callback_body_performs_no_io_or_locking() -> None:
    forbidden = (
        "threading.Lock",
        "Lock(",
        "acquire(",
        "open(",
        "json",
        "logging",
        "print(",
        "subprocess",
        "socket",
        ".write(",
        "log_tui",
        "Path(",
        "sleep",
    )
    for fn in (lifecycle_module._gc_callback, GCTelemetry._record_stop):
        source = inspect.getsource(fn)
        for token in forbidden:
            assert token not in source, f"{fn.__name__} contains {token!r}"


def test_rate_cap_reports_suppressed_count(
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
    record(tel, 2, 0.4)
    tel._flush_queued(clock.now)
    assert len(emitted) == 1
    assert emitted[0]["event"] == "tui_gc_pause"
    assert emitted[0]["suppressed_count"] == 0
    assert emitted[0]["app_instance_id"] == "test-instance"

    record(tel, 2, 0.5)
    record(tel, 2, 0.6)
    tel._flush_queued(clock.now)
    assert len(emitted) == 1  # both suppressed inside the same window

    clock.advance(61.0)
    record(tel, 2, 0.7)
    tel._flush_queued(clock.now)
    assert len(emitted) == 2
    assert emitted[1]["suppressed_count"] == 2


def test_auxiliary_rows_are_flushed_off_the_calling_thread(
    emitted: list[dict[str, Any]], clock: Clock, tmp_path: Path
) -> None:
    tel = GCTelemetry(
        app_instance_id="test-instance",
        monotonic=clock,
        wall=clock,
        emit=emitted.append,
        status_path=tmp_path / "missing-status",
        stat_path=tmp_path / "missing-stat",
    )
    tel.queue_row("tui_gc_memory_pressure", {"reason": "swapping"})
    assert emitted == []
    tel._flush_queued(clock.now)
    assert emitted == [
        {
            "event": "tui_gc_memory_pressure",
            "ts": clock.now,
            "pid": os.getpid(),
            "app_instance_id": "test-instance",
            "reason": "swapping",
        }
    ]


def test_trigger_tag_lands_on_record(
    telemetry: GCTelemetry, emitted: list[dict[str, Any]], clock: Clock
) -> None:
    with gc_trigger("idle"):
        lifecycle_module._gc_callback("start", {"generation": 2})
        lifecycle_module._gc_callback("stop", {"generation": 2, "collected": 7})
    lifecycle_module._gc_callback("start", {"generation": 0})
    lifecycle_module._gc_callback("stop", {"generation": 2, "collected": 3})
    telemetry._flush_queued(clock.now)
    assert [row["trigger"] for row in emitted] == ["idle", "automatic"]
    assert emitted[0]["collected"] == 7


def test_trigger_nesting_restores_outer_tag() -> None:
    with gc_trigger("outer"):
        with gc_trigger("inner"):
            assert lifecycle_module._trigger_tag == "inner"
        assert lifecycle_module._trigger_tag == "outer"
    assert lifecycle_module._trigger_tag == gc_telemetry.UNTAGGED_TRIGGER


def test_recent_collections_filters_by_time(telemetry: GCTelemetry) -> None:
    record(telemetry, 2, 0.5, start=100.0)
    record(telemetry, 1, 0.06, start=200.0)
    entries = recent_collections(150.0)
    assert len(entries) == 1
    assert entries[0]["generation"] == 1
    assert entries[0]["trigger"] == "automatic"
    assert entries == recent_collections(150.0)[:1]


def test_full_collection_markers_for_idle_policy(
    telemetry: GCTelemetry,
) -> None:
    assert telemetry.last_full_collection_mono() is None
    assert telemetry.gen1_since_last_full() == 0
    record(telemetry, 1, 0.06, start=100.0)
    record(telemetry, 1, 0.06, start=101.0)
    assert telemetry.gen1_since_last_full() == 2
    record(telemetry, 2, 0.6, start=102.0)
    assert telemetry.last_full_collection_mono() == pytest.approx(102.6)
    assert telemetry.gen1_since_last_full() == 0


def test_queue_bound_drops_oldest_without_growing(
    telemetry: GCTelemetry,
) -> None:
    for index in range(gc_telemetry.QUEUE_MAX + 5):
        record(telemetry, 2, 0.4, start=1000.0 + index)
    assert len(telemetry._queue) == gc_telemetry.QUEUE_MAX
    assert telemetry._queue_dropped == 5


def test_pause_row_carries_start_ts_input_age_and_fault_delta(
    emitted: list[dict[str, Any]], clock: Clock, tmp_path: Path
) -> None:
    tel = GCTelemetry(
        app_instance_id="test-instance",
        monotonic=clock,
        wall=lambda: 5000.0,
        emit=emitted.append,
        status_path=tmp_path / "missing-status",
        stat_path=tmp_path / "missing-stat",
    )
    tel._record_stop(
        2,
        2000.0,
        2000.4,
        "MainThread",
        "idle",
        10,
        0,
        3.5,
        17,
    )
    tel._flush_queued(clock.now)
    row = emitted[0]
    assert row["event"] == "tui_gc_pause"
    assert row["start_ts"] == pytest.approx(5000.0 + (2000.0 - clock.now))
    assert row["input_age_s"] == pytest.approx(3.5)
    assert row["major_faults_delta"] == 17


def test_callback_records_input_age_and_majflt(
    telemetry: GCTelemetry,
    emitted: list[dict[str, Any]],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    faults = iter((10, 25))
    monkeypatch.setattr(lifecycle_module, "_majflt", lambda: next(faults))
    monkeypatch.setattr(lifecycle_module.time, "monotonic", clock)
    note_last_input_mono(clock.now - 2.5)
    lifecycle_module._gc_callback("start", {"generation": 2})
    clock.advance(0.4)
    lifecycle_module._gc_callback("stop", {"generation": 2, "collected": 1})
    telemetry._flush_queued(clock.now)
    assert emitted
    row = emitted[0]
    assert row["major_faults_delta"] == 15
    assert row["input_age_s"] == pytest.approx(2.5)
    assert row["duration_s"] == pytest.approx(0.4)
