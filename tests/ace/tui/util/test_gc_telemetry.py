"""Tests for the GC pause recorder, memory heartbeat, and app identity."""

from __future__ import annotations

import gc
import inspect
import os
import time
from asyncio import Task
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions._startup_telemetry import StartupTelemetryMixin
from sase.ace.tui.util import gc_telemetry
from sase.ace.tui.util import startup_clock
from sase.ace.tui.util.gc_telemetry import (
    GCTelemetry,
    app_instance_id,
    gc_trigger,
    install_gc_telemetry,
    latest_rss_bytes,
    new_app_instance_id,
    recent_collections,
    register_heartbeat_provider,
    uninstall_gc_telemetry,
    unregister_heartbeat_provider,
)


class _Clock:
    """Manually advanced monotonic clock for deterministic telemetry tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


@pytest.fixture
def emitted() -> list[dict[str, Any]]:
    return []


@pytest.fixture
def clock() -> _Clock:
    return _Clock()


@pytest.fixture
def telemetry(
    emitted: list[dict[str, Any]], clock: _Clock, tmp_path: Path
) -> Iterator[GCTelemetry]:
    tel = GCTelemetry(
        app_instance_id="test-instance",
        monotonic=clock,
        emit=emitted.append,
        status_path=tmp_path / "missing-status",
        stat_path=tmp_path / "missing-stat",
    )
    previous_active = gc_telemetry._active
    previous_tag = gc_telemetry._trigger_tag
    previous_providers = dict(gc_telemetry._heartbeat_providers)
    gc_telemetry._active = tel
    try:
        yield tel
    finally:
        gc_telemetry._active = previous_active
        gc_telemetry._trigger_tag = previous_tag
        gc_telemetry._heartbeat_providers.clear()
        gc_telemetry._heartbeat_providers.update(previous_providers)
        gc_telemetry._pending_start.start_mono = None
        gc_telemetry._pending_start.thread = ""
        gc_telemetry._pending_start.trigger = gc_telemetry.UNTAGGED_TRIGGER


def _record(
    tel: GCTelemetry,
    generation: int,
    duration: float,
    *,
    start: float = 2000.0,
    trigger: str = "automatic",
    collected: int = 10,
) -> None:
    tel._record_stop(
        generation,
        start,
        start + duration,
        "MainThread",
        trigger,
        collected,
        0,
    )


def test_queue_keeps_gen2_and_slow_collections_only(
    telemetry: GCTelemetry,
) -> None:
    _record(telemetry, 0, 0.005)
    _record(telemetry, 1, 0.010)
    assert len(telemetry._queue) == 0
    # Short young collections still count toward the heartbeat totals.
    assert telemetry._gen_counts[0] == 1
    assert telemetry._gen_counts[1] == 1

    _record(telemetry, 1, 0.060)
    _record(telemetry, 2, 0.001)
    assert [row["generation"] for row in telemetry._queue] == [1, 2]
    assert telemetry._gen_counts[1] == 2
    assert telemetry._gen_counts[2] == 1


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
    for fn in (gc_telemetry._gc_callback, GCTelemetry._record_stop):
        source = inspect.getsource(fn)
        for token in forbidden:
            assert token not in source, f"{fn.__name__} contains {token!r}"


def test_rate_cap_reports_suppressed_count(
    emitted: list[dict[str, Any]], clock: _Clock, tmp_path: Path
) -> None:
    tel = GCTelemetry(
        app_instance_id="test-instance",
        monotonic=clock,
        emit=emitted.append,
        rate_limit_per_min=1,
        status_path=tmp_path / "missing-status",
        stat_path=tmp_path / "missing-stat",
    )
    _record(tel, 2, 0.4)
    tel._flush_queued(clock.now)
    assert len(emitted) == 1
    assert emitted[0]["event"] == "tui_gc_pause"
    assert emitted[0]["suppressed_count"] == 0
    assert emitted[0]["app_instance_id"] == "test-instance"

    _record(tel, 2, 0.5)
    _record(tel, 2, 0.6)
    tel._flush_queued(clock.now)
    assert len(emitted) == 1  # both suppressed inside the same window

    clock.advance(61.0)
    _record(tel, 2, 0.7)
    tel._flush_queued(clock.now)
    assert len(emitted) == 2
    assert emitted[1]["suppressed_count"] == 2


def test_heartbeat_totals_stay_exact_despite_rate_cap(
    emitted: list[dict[str, Any]], clock: _Clock, tmp_path: Path
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
        _record(tel, 2, 0.4)
    rows = [row for row in emitted if row["event"] == "tui_gc_pause"]
    assert rows == []
    tel._write_heartbeat(clock.now)
    heartbeats = [row for row in emitted if row["event"] == "tui_memory_heartbeat"]
    assert len(heartbeats) == 1
    assert heartbeats[0]["gc_generations"]["2"]["count"] == 3
    assert heartbeats[0]["gc_generations"]["2"]["total_s"] == pytest.approx(1.2)


def _write_proc_files(tmp_path: Path, *, rss_kb: int, swap_kb: int) -> None:
    (tmp_path / "status").write_text(
        f"Name:\tsase\nVmRSS:\t{rss_kb} kB\nVmSwap:\t{swap_kb} kB\n",
        encoding="utf-8",
    )
    (tmp_path / "stat").write_text(
        "1 (sase) S 0 0 0 0 0 0 0 0 42 0 0 0 0 0 0 0 0 0 12345",
        encoding="utf-8",
    )


def test_heartbeat_parses_proc_and_tracks_fault_delta(
    emitted: list[dict[str, Any]], clock: _Clock, tmp_path: Path
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


def test_heartbeat_window_spans_since_previous_heartbeat(
    emitted: list[dict[str, Any]], clock: _Clock, tmp_path: Path
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
    clock: _Clock,
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


def test_heartbeat_providers_contribute_without_clobbering_core(
    telemetry: GCTelemetry,
    emitted: list[dict[str, Any]],
    clock: _Clock,
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


def test_trigger_tag_lands_on_record(
    telemetry: GCTelemetry, emitted: list[dict[str, Any]], clock: _Clock
) -> None:
    with gc_trigger("idle"):
        gc_telemetry._gc_callback("start", {"generation": 2})
        gc_telemetry._gc_callback("stop", {"generation": 2, "collected": 7})
    gc_telemetry._gc_callback("start", {"generation": 0})
    gc_telemetry._gc_callback("stop", {"generation": 2, "collected": 3})
    telemetry._flush_queued(clock.now)
    assert [row["trigger"] for row in emitted] == ["idle", "automatic"]
    assert emitted[0]["collected"] == 7


def test_trigger_nesting_restores_outer_tag() -> None:
    with gc_trigger("outer"):
        with gc_trigger("inner"):
            assert gc_telemetry._trigger_tag == "inner"
        assert gc_telemetry._trigger_tag == "outer"
    assert gc_telemetry._trigger_tag == gc_telemetry.UNTAGGED_TRIGGER


def test_recent_collections_filters_by_time(telemetry: GCTelemetry) -> None:
    _record(telemetry, 2, 0.5, start=100.0)
    _record(telemetry, 1, 0.06, start=200.0)
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
    _record(telemetry, 1, 0.06, start=100.0)
    _record(telemetry, 1, 0.06, start=101.0)
    assert telemetry.gen1_since_last_full() == 2
    _record(telemetry, 2, 0.6, start=102.0)
    assert telemetry.last_full_collection_mono() == pytest.approx(102.6)
    assert telemetry.gen1_since_last_full() == 0


def test_queue_bound_drops_oldest_without_growing(
    telemetry: GCTelemetry,
) -> None:
    for index in range(gc_telemetry.QUEUE_MAX + 5):
        _record(telemetry, 2, 0.4, start=1000.0 + index)
    assert len(telemetry._queue) == gc_telemetry.QUEUE_MAX
    assert telemetry._queue_dropped == 5


def test_install_uninstall_restores_gc_callbacks() -> None:
    assert gc_telemetry._active is None
    before = list(gc.callbacks)
    assert gc_telemetry._gc_callback not in before
    handle = install_gc_telemetry()
    try:
        assert handle is not None
        assert gc_telemetry._active is handle
        assert gc_telemetry._gc_callback in gc.callbacks
        assert install_gc_telemetry() is handle
        thread = handle._thread
        assert thread is not None
        assert thread.name == gc_telemetry.THREAD_NAME
        assert thread.daemon is True
    finally:
        uninstall_gc_telemetry(handle)
    assert list(gc.callbacks) == before
    assert gc_telemetry._active is None


def test_install_respects_kill_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(gc_telemetry.ENV_DISABLE, "1")
    before = list(gc.callbacks)
    assert install_gc_telemetry() is None
    assert list(gc.callbacks) == before
    assert gc_telemetry._active is None


@pytest.mark.asyncio
async def test_testing_harness_does_not_auto_install() -> None:
    from contextlib import AsyncExitStack

    from sase.ace.testing import _startup as harness_startup

    assert (
        harness_startup._ORIGINAL_INSTALL_GC_TELEMETRY
        is gc_telemetry.install_gc_telemetry
    )
    before = list(gc.callbacks)
    async with AsyncExitStack() as stack:
        harness_startup._install_fast_startup_overrides(stack)
        assert harness_startup._gc_telemetry.install_gc_telemetry(object()) is None
        assert gc_telemetry._active is None
        assert list(gc.callbacks) == before


def test_exec_anchor_is_used_and_consumed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    anchor_ns = time.monotonic_ns() - 5_000_000_000
    monkeypatch.setenv(startup_clock.EXEC_MONO_NS_ENV, str(anchor_ns))
    startup_clock._process_start_mono = None
    try:
        assert startup_clock._ensure_process_start() == pytest.approx(
            anchor_ns / 1_000_000_000
        )
        assert startup_clock.EXEC_MONO_NS_ENV not in os.environ
    finally:
        startup_clock._process_start_mono = None
        startup_clock._cli_ready_mono = None
        startup_clock._app_imported_mono = None
        startup_clock._app_construct_start_mono = None
        startup_clock._app_construct_end_mono = None
        startup_clock._compose_start_mono = None
        startup_clock._compose_end_mono = None


def test_exec_anchor_rejects_garbage_and_future(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    startup_clock._process_start_mono = None
    try:
        monkeypatch.setenv(startup_clock.EXEC_MONO_NS_ENV, "not-a-number")
        fallback = startup_clock._ensure_process_start()
        assert isinstance(fallback, float)

        startup_clock._process_start_mono = None
        future_ns = time.monotonic_ns() + 60_000_000_000
        monkeypatch.setenv(startup_clock.EXEC_MONO_NS_ENV, str(future_ns))
        # /proc start time has 10ms resolution and the fallback spans I/O, so
        # compare with an absolute tolerance instead of the default relative one.
        assert startup_clock._ensure_process_start() == pytest.approx(
            fallback, abs=0.05
        )
    finally:
        startup_clock._process_start_mono = None


def test_app_instance_id_mint_and_accessor() -> None:
    first, second = new_app_instance_id(), new_app_instance_id()
    assert first and second and first != second
    assert app_instance_id(object()) is None
    assert app_instance_id(None) is None

    class _App:
        _app_instance_id = first

    assert app_instance_id(_App()) == first


def test_latest_rss_bytes_without_active() -> None:
    previous = gc_telemetry._active
    gc_telemetry._active = None
    try:
        assert latest_rss_bytes() is None
    finally:
        gc_telemetry._active = previous


class _StartupStub(StartupTelemetryMixin):
    def __init__(self) -> None:
        self.current_tab = "agents"
        self._startup_process_start_mono = 100.0
        self._startup_on_mount_mono: float | None = 101.0
        self._startup_first_paint_mono: float | None = 101.5
        self._startup_initial_tab = "agents"
        self._startup_agents_ready_mono: float | None = 102.0
        self._startup_axe_ready_mono: float | None = 103.0
        self._startup_visible_ready_mono: float | None = 102.0
        self._startup_telemetry_recorded = False
        self._startup_telemetry_async_tasks: set[Task[None]] = set()
        self._agents_first_load_done = True
        self._axe_first_load_done = True
        self._agents: list[Any] = []
        self._agents_refresh_active_source = "startup"
        self._agent_load_state = None
        self._app_instance_id = "stub-instance"


def test_startup_record_carries_instance_and_version() -> None:
    record = _StartupStub()._build_startup_telemetry_record()
    assert record["event"] == "tui_startup"
    assert record["app_instance_id"] == "stub-instance"
    assert record["sase_version"] is None or isinstance(record["sase_version"], str)
