"""Queue-pump stall and hitch episodes for the TUI stall watchdog.

Covers the synchronous off-the-loop pump record, pump stall stacks with
recovery, compact pump hitches, and bounded worker-thread stacks. Loop
episodes live in ``test_stall_watchdog_loop.py``, pause/resume and
suspend-signal wiring live in ``test_stall_watchdog_suspend.py``, and the
watchdog-truth hitch additions live in
``test_stall_watchdog_hitch_truth.py``. The original
``test_stall_watchdog.py`` module remains as a facade that lazily re-exports
every test here under its historic import path.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

import pytest

from sase.ace.tui.util.stall_watchdog import (
    MAX_WORKER_THREAD_STACK_DEPTH,
    MAX_WORKER_THREAD_STACKS,
    _EventLoopStallWatchdog,
)
from sase.logs import tui_telemetry

from ._stall_watchdog_support import FakeClock, FakePumpApp, read_records


async def _wait_for_event(path: Path, event: str) -> None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if any(record.get("event") == event for record in read_records(path)):
            return
        await asyncio.sleep(min(0.01, max(0.0, deadline - time.monotonic())))
    raise AssertionError(f"{event} was not written to {path}")


@pytest.mark.asyncio
async def test_pump_stall_record_is_written_synchronously_off_the_loop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression test: recording must not hop through call_soon_threadsafe.

    Dispatching stack capture and the JSONL write via call_soon_threadsafe
    made that work run on the event loop as soon as it recovered,
    extending the very freeze the watchdog measures. The record must be
    fully written by the time ``_record_pump_stall`` returns, with no
    intervening event-loop tick.
    """
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    watchdog = _EventLoopStallWatchdog(asyncio.get_running_loop())

    watchdog._record_pump_stall(100.0, 1.0)

    assert path.exists()
    records = read_records(path)
    assert len(records) == 1
    assert records[0]["event"] == "tui_pump_stall"


@pytest.mark.asyncio
async def test_watchdog_records_pump_stall_stack_and_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    pump = FakePumpApp()
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

    records = read_records(path)
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
    pump = FakePumpApp()
    clock = FakeClock()
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

    records = read_records(path)
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
