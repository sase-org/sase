"""Loop stall and hitch episodes for the TUI event-loop stall watchdog.

Covers the quiet-loop case, stall records with stack and context, loop
recovery, hitch thresholds/disables from the environment, compact hitch
episodes, hitch/stall state-machine independence, and hitch rate limiting.
Pump episodes live in ``test_stall_watchdog_pump.py``, pause/resume and
suspend-signal wiring live in ``test_stall_watchdog_suspend.py``, and the
watchdog-truth hitch additions live in
``test_stall_watchdog_hitch_truth.py``. The original
``test_stall_watchdog.py`` module remains as a facade that lazily re-exports
every test here under its historic import path.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from sase.ace.tui.util.stall_watchdog import (
    ENV_HITCH_DISABLE,
    ENV_HITCH_THRESHOLD_SECONDS,
    ENV_PUMP_HITCH_DISABLE,
    ENV_PUMP_HITCH_THRESHOLD_SECONDS,
    _EventLoopStallWatchdog,
)
from sase.logs import tui_telemetry

from ._stall_watchdog_support import FakeClock, read_records


@pytest.mark.asyncio
async def test_watchdog_emits_nothing_while_loop_progresses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=0.2,
        poll_interval_seconds=0.02,
    )
    try:
        watchdog.start()
        await asyncio.sleep(0.08)  # sase-test-wait: below watchdog threshold
    finally:
        watchdog.stop()

    assert not path.exists()


@pytest.mark.asyncio
async def test_watchdog_records_one_stall_with_stack_and_context(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    clock = FakeClock()
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=0.05,
        poll_interval_seconds=0.01,
        monotonic=clock.monotonic,
        context_provider=lambda: {
            "current_tab": "agents",
            "last_action": "launch",
            "last_keypress_age_s": 1.25,
        },
    )

    assert watchdog._poll_once() is True
    clock.advance(0.06)
    assert watchdog._poll_once() is True

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 1
    record = records[0]
    assert record["event"] == "tui_stall"
    assert record["pid"] > 0
    assert record["stall_seconds"] >= 0.05
    assert record["current_tab"] == "agents"
    assert record["last_action"] == "launch"
    assert record["last_keypress_age_s"] == 1.25
    assert record["main_thread_stack"]


@pytest.mark.asyncio
async def test_watchdog_writes_loop_recovery_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    clock = FakeClock()
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=0.05,
        poll_interval_seconds=0.01,
        monotonic=clock.monotonic,
    )

    assert watchdog._poll_once() is True
    clock.advance(0.06)
    assert watchdog._poll_once() is True
    await asyncio.sleep(0)
    assert watchdog._poll_once() is True

    records = read_records(path)
    assert [record["event"] for record in records] == [
        "tui_stall",
        "tui_stall_recovered",
    ]
    assert records[1]["duration_seconds"] >= 0.05
    assert records[1]["pause_depth"] == 0


@pytest.mark.asyncio
async def test_watchdog_reads_hitch_thresholds_and_disables_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_HITCH_THRESHOLD_SECONDS, "1.25")
    monkeypatch.setenv(ENV_PUMP_HITCH_THRESHOLD_SECONDS, "1.75")
    watchdog = _EventLoopStallWatchdog(asyncio.get_running_loop())

    assert watchdog._hitch_threshold_seconds == 1.25
    assert watchdog._pump_hitch_threshold_seconds == 1.75
    assert watchdog._hitch_enabled is True
    assert watchdog._pump_hitch_enabled is True

    monkeypatch.setenv(ENV_HITCH_DISABLE, "yes")
    monkeypatch.setenv(ENV_PUMP_HITCH_DISABLE, "1")
    disabled_watchdog = _EventLoopStallWatchdog(asyncio.get_running_loop())

    assert disabled_watchdog._hitch_enabled is False
    assert disabled_watchdog._pump_hitch_enabled is False


@pytest.mark.asyncio
async def test_watchdog_records_compact_loop_hitch_and_recovery(
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
        context_provider=lambda: {
            "current_tab": "agents",
            "current_idx": 7,
            "last_action": "down",
            "last_keypress_age_s": 0.8,
        },
    )

    assert watchdog._poll_once() is True
    clock.advance(0.06)
    assert watchdog._poll_once() is True
    await asyncio.sleep(0)
    assert watchdog._poll_once() is True

    records = read_records(path)
    events = [record["event"] for record in records]
    assert events == ["tui_hitch", "tui_hitch_recovered"]
    hitch, recovery = records
    assert hitch["stall_seconds"] >= 0.05
    assert hitch["suppressed_count"] == 0
    assert hitch["current_tab"] == "agents"
    assert hitch["current_idx"] == 7
    assert hitch["last_action"] == "down"
    assert hitch["last_keypress_age_s"] == 0.8
    assert hitch["main_thread_stack"]
    assert "asyncio_task_stacks" not in hitch
    assert "worker_thread_stacks" not in hitch
    assert recovery["duration_seconds"] >= 0.05
    assert recovery["main_thread_stack"]


@pytest.mark.asyncio
async def test_watchdog_keeps_hitch_and_stall_state_machines_independent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    clock = FakeClock()
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=0.08,
        hitch_threshold_seconds=0.03,
        poll_interval_seconds=0.01,
        monotonic=clock.monotonic,
    )

    assert watchdog._poll_once() is True
    clock.advance(0.04)
    assert watchdog._poll_once() is True
    clock.advance(0.05)
    assert watchdog._poll_once() is True
    await asyncio.sleep(0)
    assert watchdog._poll_once() is True

    events = [record["event"] for record in read_records(path)]
    assert events == [
        "tui_hitch",
        "tui_stall",
        "tui_hitch_recovered",
        "tui_stall_recovered",
    ]


@pytest.mark.asyncio
async def test_watchdog_rate_limits_hitch_episodes_and_reports_suppression(
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

    watchdog._record_hitch(100.0, 2.0)
    watchdog._record_hitch_recovery(101.0)
    watchdog._record_hitch(110.0, 2.0)
    watchdog._record_hitch_recovery(111.0)
    watchdog._record_hitch(120.0, 2.0)
    watchdog._record_hitch_recovery(121.0)
    watchdog._record_hitch(161.0, 2.0)
    watchdog._record_hitch_recovery(162.0)

    records = read_records(path)
    hitches = [record for record in records if record["event"] == "tui_hitch"]
    recoveries = [
        record for record in records if record["event"] == "tui_hitch_recovered"
    ]
    assert len(hitches) == 3
    assert len(recoveries) == 3
    assert [record["suppressed_count"] for record in hitches] == [0, 0, 1]
