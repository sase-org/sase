"""Watchdog-truth hitch additions (sase-1ez.2) for the stall watchdog.

Covers late polls with a serviced beacon, loop-gap/lateness single
recording, GC overlap attribution on recovery, suppressed-episode heartbeat
totals, heartbeat provider registration, and app instance IDs on hitch rows.
Loop episodes live in ``test_stall_watchdog_loop.py``, pump episodes live in
``test_stall_watchdog_pump.py``, and pause/resume plus suspend-signal wiring
live in ``test_stall_watchdog_suspend.py``. The original
``test_stall_watchdog.py`` module remains as a facade that lazily re-exports
every test here under its historic import path.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.util import gc_telemetry
from sase.ace.tui.util.stall_watchdog import _EventLoopStallWatchdog
from sase.logs import tui_telemetry

from ._stall_watchdog_support import FakeClock, read_records


@pytest.mark.asyncio
async def test_late_poll_with_serviced_beacon_records_one_late_hitch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A whole-process stop is reported even when the beacon already ran."""
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    clock = FakeClock()
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=1.0,
        hitch_threshold_seconds=0.05,
        poll_interval_seconds=0.01,
        monotonic=clock.monotonic,
    )

    assert watchdog._poll_once() is True
    clock.advance(0.06)
    # The loop beacon ran at the new time, so the loop gap looks small, but
    # the watchdog thread itself was 0.06 s late for its 0.01 s poll.
    watchdog._mark_loop_progress()
    assert watchdog._poll_once() is True
    clock.advance(0.01)
    assert watchdog._poll_once() is True

    records = read_records(path)
    assert [record["event"] for record in records] == [
        "tui_hitch",
        "tui_hitch_recovered",
    ]
    hitch, recovery = records
    assert hitch["late"] is True
    assert hitch["detected_by"] == "watchdog_lateness"
    assert hitch["poll_lag_s"] == pytest.approx(0.05)
    # Net duration is the gap minus one poll interval, floored at threshold.
    assert hitch["net_stall_seconds"] == pytest.approx(0.05)
    assert hitch["stall_seconds"] == pytest.approx(0.06)
    assert recovery["late"] is True
    assert recovery["detected_by"] == "watchdog_lateness"
    assert recovery["gc_overlap_s"] == 0.0
    assert recovery["gc_generations"] == []
    assert recovery["gc_triggers"] == []


@pytest.mark.asyncio
async def test_loop_gap_and_lateness_never_double_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    clock = FakeClock()
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=1.0,
        hitch_threshold_seconds=0.05,
        poll_interval_seconds=0.01,
        monotonic=clock.monotonic,
    )

    assert watchdog._poll_once() is True
    clock.advance(0.06)
    assert watchdog._poll_once() is True
    # The poll gap is also past the hitch threshold here, but the loop-gap
    # path already owns the episode: still exactly one hitch row.
    assert watchdog._poll_once() is True

    records = read_records(path)
    assert [record["event"] for record in records] == ["tui_hitch"]
    assert records[0]["late"] is False
    assert records[0]["detected_by"] == "loop_gap"


@pytest.mark.asyncio
async def test_recovery_attributes_gc_overlap_from_telemetry_ring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    monkeypatch.setattr(
        gc_telemetry,
        "_active",
        SimpleNamespace(
            recent_collections=lambda since_mono: (
                [
                    {
                        "generation": 2,
                        "start_mono": 99.0,
                        "end_mono": 100.5,
                        "thread": "MainThread",
                        "trigger": "idle",
                    },
                    {
                        "generation": 0,
                        "start_mono": 50.0,
                        "end_mono": 50.1,
                        "thread": "MainThread",
                        "trigger": "automatic",
                    },
                ]
                if since_mono <= 99.0
                else []
            ),
        ),
    )
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=1.0,
        hitch_threshold_seconds=0.05,
        poll_interval_seconds=0.01,
    )

    watchdog._record_hitch(100.0, 2.0)
    watchdog._record_hitch_recovery(101.0)

    records = read_records(path)
    assert [record["event"] for record in records] == [
        "tui_hitch",
        "tui_hitch_recovered",
    ]
    recovery = records[1]
    assert recovery["gc_overlap_s"] == pytest.approx(1.5)
    assert recovery["gc_generations"] == [2]
    assert recovery["gc_triggers"] == ["idle"]


@pytest.mark.asyncio
async def test_suppressed_episodes_count_in_heartbeat_totals(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        hitch_rate_limit_per_minute=2,
        hitch_rate_limit_window_seconds=60.0,
    )

    for index in range(3):
        watchdog._record_hitch(100.0 + index * 10.0, 2.0)
        watchdog._record_hitch_recovery(102.0 + index * 10.0)

    totals = watchdog._heartbeat_hitch_totals()
    assert totals["loop_hitch_episodes"] == 3
    assert totals["loop_hitch_seconds"] == pytest.approx(12.0)
    assert totals["loop_suppressed_episodes"] == 1
    assert totals["loop_suppressed_seconds"] == pytest.approx(4.0)
    assert totals["pump_hitch_episodes"] == 0
    assert totals["pump_suppressed_episodes"] == 0

    # The snapshot resets: the next heartbeat starts from zero.
    reset = watchdog._heartbeat_hitch_totals()
    assert reset["loop_hitch_episodes"] == 0
    assert reset["loop_hitch_seconds"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_heartbeat_provider_registers_on_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    monkeypatch.setattr(gc_telemetry, "_heartbeat_providers", {})
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=100.0,
        poll_interval_seconds=100.0,
    )
    try:
        watchdog._register_heartbeat_provider()
        assert "stall_watchdog" in gc_telemetry._heartbeat_providers
        provided = gc_telemetry._heartbeat_providers["stall_watchdog"]()
        assert provided["loop_hitch_episodes"] == 0
    finally:
        watchdog._unregister_heartbeat_provider()
    assert "stall_watchdog" not in gc_telemetry._heartbeat_providers


@pytest.mark.asyncio
async def test_hitch_rows_carry_app_instance_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    app = SimpleNamespace(_app_instance_id="abc123")
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        pump_app=app,
        threshold_seconds=1.0,
        hitch_threshold_seconds=0.05,
        poll_interval_seconds=0.01,
    )

    watchdog._record_hitch(100.0, 2.0)
    watchdog._record_hitch_recovery(102.0)

    records = read_records(path)
    assert [record["event"] for record in records] == [
        "tui_hitch",
        "tui_hitch_recovered",
    ]
    assert records[0]["app_instance_id"] == "abc123"
    assert records[1]["app_instance_id"] == "abc123"
