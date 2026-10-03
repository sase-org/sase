"""Pause/resume gating and suspend-signal wiring for the stall watchdog.

Covers the paused watchdog staying quiet while the loop is blocked,
recording one real stall after resume, nested pause depth, and wiring the
watchdog to app suspend/resume signals. Loop episodes live in
``test_stall_watchdog_loop.py``, pump episodes live in
``test_stall_watchdog_pump.py``, and the watchdog-truth hitch additions live
in ``test_stall_watchdog_hitch_truth.py``. The original
``test_stall_watchdog.py`` module remains as a facade that lazily re-exports
every test here under its historic import path.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from sase.ace.tui.util.stall_watchdog import (
    _EventLoopStallWatchdog,
    subscribe_watchdog_to_suspend_signals,
)
from sase.logs import tui_telemetry

from ._stall_watchdog_support import FakeClock, FakePumpApp


@pytest.mark.asyncio
async def test_paused_watchdog_quiets_loop_and_pump_beacons(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    pump = FakePumpApp()
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
    clock = FakeClock()
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
