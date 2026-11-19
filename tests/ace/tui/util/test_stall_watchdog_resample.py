"""Bounded main-thread stack re-samples and compact hitch stacks.

A long loop stall re-samples the loop thread's stack on a bounded cadence
and carries those samples on its ``tui_stall_recovered`` row. Hitch-tier rows
keep only the innermost frames of the main-thread stack.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from sase.ace.tui.util import _stall_watchdog_records as records_module
from sase.ace.tui.util._stall_watchdog_config import (
    HITCH_RECOVERY_STACK_DEPTH,
    HITCH_STACK_DEPTH,
    STALL_RESAMPLE_INTERVAL_SECONDS,
    STALL_RESAMPLE_MAX,
    STALL_RESAMPLE_STACK_DEPTH,
)
from sase.ace.tui.util.stall_watchdog import _EventLoopStallWatchdog
from sase.logs import tui_telemetry

from ._stall_watchdog_support import FakeClock, read_records


class _ScriptedStacks:
    """Stand-in for ``format_thread_stack`` that records each ``limit``."""

    def __init__(self, *stacks: list[str]) -> None:
        self._stacks = list(stacks)
        self.limits: list[int | None] = []

    def __call__(self, _ident: int, *, limit: int | None = None) -> list[str]:
        self.limits.append(limit)
        stack = self._stacks.pop(0) if len(self._stacks) > 1 else self._stacks[0]
        return stack[-limit:] if limit else list(stack)


@pytest.fixture
def stall_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "tui_stalls.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_STALLS_JSONL", str(path))
    return path


def _stall_watchdog(
    clock: FakeClock,
    *,
    stall_resample_interval_seconds: float = STALL_RESAMPLE_INTERVAL_SECONDS,
    stall_resample_max: int = STALL_RESAMPLE_MAX,
) -> _EventLoopStallWatchdog:
    return _EventLoopStallWatchdog(
        asyncio.get_running_loop(),
        threshold_seconds=0.05,
        hitch_threshold_seconds=100.0,
        poll_interval_seconds=0.01,
        monotonic=clock.monotonic,
        stall_resample_interval_seconds=stall_resample_interval_seconds,
        stall_resample_max=stall_resample_max,
    )


def test_resample_defaults_are_bounded() -> None:
    assert STALL_RESAMPLE_INTERVAL_SECONDS == 10.0
    assert STALL_RESAMPLE_MAX == 6
    assert 0 < STALL_RESAMPLE_STACK_DEPTH <= 64
    assert 0 < HITCH_RECOVERY_STACK_DEPTH < HITCH_STACK_DEPTH


@pytest.mark.asyncio
async def test_long_stall_recovery_carries_bounded_stack_samples(
    stall_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deep_stack = [f"frame-{index}\n" for index in range(80)]
    stacks = _ScriptedStacks(
        ["outer\n", "blocked_at_threshold\n"],
        ["outer\n", "second_call\n"],
        ["outer\n", "second_call\n"],
        deep_stack,
    )
    monkeypatch.setattr(records_module, "format_thread_stack", stacks)
    clock = FakeClock()
    watchdog = _stall_watchdog(
        clock, stall_resample_interval_seconds=0.1, stall_resample_max=3
    )

    assert watchdog._poll_once() is True
    clock.advance(0.06)
    assert watchdog._poll_once() is True  # tui_stall row
    clock.advance(0.05)
    assert watchdog._poll_once() is True  # not yet due
    for _ in range(4):
        clock.advance(0.1)
        assert watchdog._poll_once() is True  # 3 samples, then capped
    await asyncio.sleep(0)
    assert watchdog._poll_once() is True  # recovery

    records = read_records(stall_path)
    assert [record["event"] for record in records] == [
        "tui_stall",
        "tui_stall_recovered",
    ]
    samples = records[1]["stack_samples"]
    assert isinstance(samples, list)
    assert [sample["at_s"] for sample in samples] == pytest.approx([0.21, 0.31, 0.41])
    assert samples[0]["stack"] == ["outer\n", "second_call\n"]
    assert samples[1] == {"at_s": pytest.approx(0.31), "same_as_previous": True}
    assert samples[2]["stack"] == deep_stack[-STALL_RESAMPLE_STACK_DEPTH:]
    assert stacks.limits[1:] == [STALL_RESAMPLE_STACK_DEPTH] * 3


@pytest.mark.asyncio
async def test_first_resample_matching_the_stall_row_is_deduplicated(
    stall_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        records_module, "format_thread_stack", _ScriptedStacks(["stuck_here\n"])
    )
    clock = FakeClock()
    watchdog = _stall_watchdog(clock, stall_resample_interval_seconds=0.1)

    assert watchdog._poll_once() is True
    clock.advance(0.06)
    assert watchdog._poll_once() is True
    clock.advance(0.1)
    assert watchdog._poll_once() is True
    await asyncio.sleep(0)
    assert watchdog._poll_once() is True

    recovery = read_records(stall_path)[-1]
    assert recovery["stack_samples"] == [
        {"at_s": pytest.approx(0.16), "same_as_previous": True}
    ]


@pytest.mark.asyncio
async def test_short_stall_recovery_has_no_stack_samples(stall_path: Path) -> None:
    clock = FakeClock()
    watchdog = _stall_watchdog(clock)

    assert watchdog._poll_once() is True
    clock.advance(0.06)
    assert watchdog._poll_once() is True
    await asyncio.sleep(0)
    assert watchdog._poll_once() is True

    recovery = read_records(stall_path)[-1]
    assert recovery["event"] == "tui_stall_recovered"
    assert "stack_samples" not in recovery


@pytest.mark.asyncio
async def test_pause_discards_pending_stack_samples(
    stall_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        records_module, "format_thread_stack", _ScriptedStacks(["a\n"], ["b\n"])
    )
    clock = FakeClock()
    watchdog = _stall_watchdog(clock, stall_resample_interval_seconds=0.1)

    assert watchdog._poll_once() is True
    clock.advance(0.06)
    assert watchdog._poll_once() is True
    clock.advance(0.1)
    assert watchdog._poll_once() is True
    assert watchdog._stall_stack_samples

    watchdog.pause()

    assert watchdog._stall_stack_samples == []
    assert watchdog._stall_last_sample_stack is None
    watchdog._maybe_resample_stall_stack(clock.now + 1.0)
    assert watchdog._stall_stack_samples == []


@pytest.mark.asyncio
async def test_hitch_rows_keep_only_the_innermost_frames(
    stall_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    deep_stack = [f"frame-{index}\n" for index in range(100)]
    stacks = _ScriptedStacks(deep_stack)
    monkeypatch.setattr(records_module, "format_thread_stack", stacks)
    watchdog = _EventLoopStallWatchdog(asyncio.get_running_loop())

    watchdog._record_hitch(100.0, 2.0)
    watchdog._record_hitch_recovery(101.0)

    hitch, recovery = read_records(stall_path)
    assert hitch["main_thread_stack"] == deep_stack[-HITCH_STACK_DEPTH:]
    assert recovery["main_thread_stack"] == deep_stack[-HITCH_RECOVERY_STACK_DEPTH:]
    assert stacks.limits == [HITCH_STACK_DEPTH, HITCH_RECOVERY_STACK_DEPTH]
