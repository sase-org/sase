"""Tests for the TUI event-loop stall watchdog."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from sase.ace.tui.util.stall_watchdog import _EventLoopStallWatchdog
from sase.logs import tui_telemetry


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
        await asyncio.sleep(0.08)
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
    watchdog = _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=0.05,
        poll_interval_seconds=0.01,
        context_provider=lambda: {
            "current_tab": "agents",
            "last_action": "launch",
            "last_keypress_age_s": 1.25,
        },
    )
    try:
        watchdog.start()
        await asyncio.sleep(0.03)
        time.sleep(0.14)
        await _wait_for_path(path)
    finally:
        watchdog.stop()

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


async def _wait_for_path(path: Path) -> None:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        if path.exists():
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"{path} was not written")
