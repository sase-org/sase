"""Tests for the TUI event-loop stall watchdog."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from sase.ace.tui.util.stall_watchdog import (
    ENV_HITCH_DISABLE,
    ENV_HITCH_THRESHOLD_SECONDS,
    ENV_PUMP_HITCH_DISABLE,
    ENV_PUMP_HITCH_THRESHOLD_SECONDS,
    MAX_WORKER_THREAD_STACK_DEPTH,
    MAX_WORKER_THREAD_STACKS,
    _EventLoopStallWatchdog,
    subscribe_watchdog_to_suspend_signals,
)
from sase.logs import tui_telemetry


class _FakePumpApp:
    """Queue pump callbacks until the test explicitly delivers them."""

    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []

    def call_later(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)

    def deliver(self) -> None:
        callback = self.callbacks.pop(0)
        callback()


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


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
    clock = _FakeClock()
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
    clock = _FakeClock()
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

    records = _read_records(path)
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
    clock = _FakeClock()
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

    records = _read_records(path)
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
    clock = _FakeClock()
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

    events = [record["event"] for record in _read_records(path)]
    assert events == [
        "tui_hitch",
        "tui_stall",
        "tui_hitch_recovered",
        "tui_stall_recovered",
    ]


@pytest.mark.asyncio
async def test_watchdog_records_pump_stall_stack_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    pump = _FakePumpApp()
    release_handler = asyncio.Event()

    async def deliberately_stuck_handler() -> None:
        await release_handler.wait()

    stuck_handler = asyncio.create_task(
        deliberately_stuck_handler(),
        name="deliberately-stuck-pump-handler",
    )
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        pump_app=pump,
        threshold_seconds=1.0,
        poll_interval_seconds=0.01,
        pump_threshold_seconds=0.05,
        pump_poll_interval_seconds=0.01,
    )
    try:
        watchdog.start()
        await _wait_for_event(path, "tui_pump_stall")
        assert len(pump.callbacks) == 1  # no callback flood while stuck
        pump.deliver()
        release_handler.set()
        await stuck_handler
        await _wait_for_event(path, "tui_pump_stall_recovered")
    finally:
        release_handler.set()
        await stuck_handler
        watchdog.stop()

    records = _read_records(path)
    stall = next(r for r in records if r["event"] == "tui_pump_stall")
    recovery = next(r for r in records if r["event"] == "tui_pump_stall_recovered")
    assert stall["stall_seconds"] >= 0.05
    assert stall["pause_depth"] == 0
    assert any(
        task["name"] == "deliberately-stuck-pump-handler" and task["stack"]
        for task in stall["asyncio_task_stacks"]
    )
    stuck_task = next(
        task
        for task in stall["asyncio_task_stacks"]
        if task["name"] == "deliberately-stuck-pump-handler"
    )
    assert any(
        "deliberately_stuck_handler" in line
        for awaited in stuck_task["await_chain"]
        for line in awaited["stack"]
    )
    assert recovery["duration_seconds"] >= 0.05


@pytest.mark.asyncio
async def test_watchdog_records_compact_pump_hitch_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    pump = _FakePumpApp()
    clock = _FakeClock()
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        pump_app=pump,
        threshold_seconds=1.0,
        hitch_threshold_seconds=1.0,
        poll_interval_seconds=0.01,
        pump_threshold_seconds=1.0,
        pump_hitch_threshold_seconds=0.05,
        pump_poll_interval_seconds=0.01,
        monotonic=clock.monotonic,
    )

    clock.advance(0.01)
    assert watchdog._poll_once() is True
    clock.advance(0.06)
    assert watchdog._poll_once() is True
    await asyncio.sleep(0)
    assert len(pump.callbacks) == 1
    pump.deliver()
    assert watchdog._poll_once() is True

    records = _read_records(path)
    assert [record["event"] for record in records] == [
        "tui_pump_hitch",
        "tui_pump_hitch_recovered",
    ]
    hitch, recovery = records
    assert hitch["stall_seconds"] >= 0.05
    assert hitch["main_thread_stack"]
    assert "asyncio_task_stacks" not in hitch
    assert "worker_thread_stacks" not in hitch
    assert recovery["duration_seconds"] >= 0.05


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

    records = _read_records(path)
    hitches = [record for record in records if record["event"] == "tui_hitch"]
    recoveries = [
        record for record in records if record["event"] == "tui_hitch_recovered"
    ]
    assert len(hitches) == 3
    assert len(recoveries) == 3
    assert [record["suppressed_count"] for record in hitches] == [0, 0, 1]


@pytest.mark.asyncio
async def test_pump_stall_record_includes_bounded_worker_thread_stacks() -> None:
    worker_ready = threading.Event()
    release_worker = threading.Event()

    def blocked_worker() -> None:
        worker_ready.set()
        release_worker.wait(timeout=2.0)

    worker = threading.Thread(
        target=blocked_worker,
        name="aaa-test-blocked-worker",
        daemon=True,
    )
    worker.start()
    try:
        assert await asyncio.to_thread(worker_ready.wait, 1.0) is True
        watchdog = _EventLoopStallWatchdog(asyncio.get_running_loop())

        record = watchdog._pump_stall_record(1.0, capture_tasks=False)

        worker_stacks = record["worker_thread_stacks"]
        assert len(worker_stacks) <= MAX_WORKER_THREAD_STACKS
        blocked = next(
            stack
            for stack in worker_stacks
            if stack["name"] == "aaa-test-blocked-worker"
        )
        assert len(blocked["stack"]) <= MAX_WORKER_THREAD_STACK_DEPTH
        assert any("blocked_worker" in line for line in blocked["stack"])
        assert all(
            stack["ident"]
            not in {
                record["loop_thread_ident"],
                record["watchdog_thread_ident"],
            }
            for stack in worker_stacks
        )
    finally:
        release_worker.set()
        worker.join(timeout=1.0)


@pytest.mark.asyncio
async def test_paused_watchdog_quiets_loop_and_pump_beacons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    pump = _FakePumpApp()
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        pump_app=pump,
        threshold_seconds=0.05,
        poll_interval_seconds=0.01,
        pump_threshold_seconds=0.05,
        pump_poll_interval_seconds=0.01,
    )
    try:
        watchdog.pause()
        watchdog.start()
        await asyncio.sleep(0.12)  # sase-test-wait: paused watchdog window
    finally:
        watchdog.resume()
        watchdog.stop()

    assert pump.callbacks == []
    assert not path.exists()


@pytest.mark.asyncio
async def test_paused_watchdog_emits_no_stall_while_loop_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=0.05,
        poll_interval_seconds=0.01,
    )
    try:
        watchdog.start()
        watchdog.pause()
        # Block the loop well past the threshold while paused.
        time.sleep(0.2)  # sase-test-wait: intentional loop block
        # Let the watchdog thread poll several times during the paused block.
        await asyncio.sleep(0.05)  # sase-test-wait: watchdog thread poll window
    finally:
        watchdog.resume()
        watchdog.stop()

    assert not path.exists()


@pytest.mark.asyncio
async def test_resumed_watchdog_records_one_later_real_stall(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=0.05,
        poll_interval_seconds=0.01,
    )
    try:
        watchdog.start()
        watchdog.pause()
        time.sleep(0.15)  # sase-test-wait: paused loop block
        watchdog.resume()
        await asyncio.sleep(0.03)  # sase-test-wait: fresh watchdog ping
        time.sleep(0.15)  # sase-test-wait: recorded loop block
        await _wait_for_path(path)
    finally:
        watchdog.stop()

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 1
    assert records[0]["event"] == "tui_stall"


@pytest.mark.asyncio
async def test_nested_pause_requires_final_resume_before_detection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    clock = _FakeClock()
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=0.05,
        poll_interval_seconds=0.01,
        monotonic=clock.monotonic,
    )

    watchdog.pause()
    watchdog.pause()
    watchdog.resume()
    clock.advance(0.15)
    assert watchdog._poll_once() is True
    assert not path.exists()

    watchdog.resume()
    assert watchdog._poll_once() is True
    clock.advance(0.06)
    assert watchdog._poll_once() is True

    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(records) == 1


class _FakeSignal:
    """Minimal stand-in for a Textual instance signal."""

    def __init__(self) -> None:
        self.subscriptions: list[tuple[object, object, bool]] = []

    def subscribe(
        self,
        node: object,
        callback: object,
        immediate: bool = False,
    ) -> None:
        self.subscriptions.append((node, callback, immediate))


class _FakeWatchdog:
    def __init__(self) -> None:
        self.paused = 0
        self.resumed = 0

    def pause(self) -> None:
        self.paused += 1

    def resume(self) -> None:
        self.resumed += 1


class _FakeApp:
    def __init__(self, *, with_signals: bool) -> None:
        if with_signals:
            self.app_suspend_signal = _FakeSignal()
            self.app_resume_signal = _FakeSignal()


def test_subscribe_wires_both_signals_immediately() -> None:
    app = _FakeApp(with_signals=True)
    watchdog = _FakeWatchdog()

    wired = subscribe_watchdog_to_suspend_signals(app, watchdog)  # type: ignore[arg-type]

    assert wired is True
    assert len(app.app_suspend_signal.subscriptions) == 1
    assert len(app.app_resume_signal.subscriptions) == 1
    # Both subscribe with immediate=True so the callback runs during publish,
    # before suspend() parks the loop.
    suspend_node, suspend_cb, suspend_immediate = app.app_suspend_signal.subscriptions[
        0
    ]
    resume_node, resume_cb, resume_immediate = app.app_resume_signal.subscriptions[0]
    assert suspend_immediate is True
    assert resume_immediate is True
    assert suspend_node is app
    assert resume_node is app

    # The wired callbacks pause/resume the watchdog when published.
    suspend_cb(app)  # type: ignore[operator]
    resume_cb(app)  # type: ignore[operator]
    assert watchdog.paused == 1
    assert watchdog.resumed == 1


def test_subscribe_tolerates_missing_signal_attributes() -> None:
    app = _FakeApp(with_signals=False)
    watchdog = _FakeWatchdog()

    wired = subscribe_watchdog_to_suspend_signals(app, watchdog)  # type: ignore[arg-type]

    assert wired is False


def test_subscribe_returns_false_without_watchdog() -> None:
    app = _FakeApp(with_signals=True)

    assert subscribe_watchdog_to_suspend_signals(app, None) is False


async def _wait_for_path(path: Path) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if path.exists():
            return
        await asyncio.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    raise AssertionError(f"{path} was not written")


def _read_records(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


async def _wait_for_event(path: Path, event: str) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if any(record.get("event") == event for record in _read_records(path)):
            return
        await asyncio.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    raise AssertionError(f"{event} was not written to {path}")
