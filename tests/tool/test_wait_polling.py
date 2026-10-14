"""Backoff, reconcile throttle, and event-ingest skip for tool wait."""

from __future__ import annotations

from collections import OrderedDict
import threading
from pathlib import Path
from typing import Any

import pytest

from sase.tool.control import UnknownRunError, WaitPollState, wait_for_settlement
from sase.tool.control_wait import (
    _POLL_MAX_SECONDS,
    _POLL_START_SECONDS,
)
from sase.tool.follow_run import follow_run
from sase.tool.liveness import reconcile_unsettled_tool_runs


class _Clock:
    """Monotonic clock that advances on sleep."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _running(run_id: str = "r" * 32) -> dict[str, Any]:
    return {"run": {"run_id": run_id, "state": "running"}}


def _settled(run_id: str = "r" * 32) -> dict[str, Any]:
    return {
        "run": {
            "run_id": run_id,
            "state": "succeeded",
            "exit_code": 0,
        }
    }


def _patch_clock(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> None:
    monkeypatch.setattr("sase.tool.control_wait.time.monotonic", clock.monotonic)
    monkeypatch.setattr("sase.tool.control_wait.time.sleep", clock.sleep)
    monkeypatch.setattr("sase.tool.follow_run.time.monotonic", clock.monotonic)
    monkeypatch.setattr("sase.tool.follow_run.time.sleep", clock.sleep)


def _patch_show(monkeypatch: pytest.MonkeyPatch, show: Any) -> None:
    monkeypatch.setattr("sase.tool.control_wait.tool_run_show", show)
    monkeypatch.setattr("sase.core.tool_run.tool_run_show", show)


def test_follow_throttles_reconcile_and_backs_off_show(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    show_times: list[float] = []
    reconcile_times: list[float] = []
    envelope = _running()

    def show(_run_id: str) -> dict[str, Any]:
        show_times.append(clock.now)
        return envelope

    def reconcile() -> dict[str, Any]:
        reconcile_times.append(clock.now)
        return {}

    _patch_clock(monkeypatch, clock)
    _patch_show(monkeypatch, show)
    monkeypatch.setattr(
        "sase.tool.control_wait.reconcile_unsettled_tool_runs", reconcile
    )

    outcome = follow_run("r" * 32, deadline_s=3.0, stream_output=False)

    assert outcome.kind == "deadline"
    assert 2 <= len(reconcile_times) <= 3
    assert clock.now == pytest.approx(3.0)
    assert len(show_times) <= 25
    assert any(sleep >= _POLL_MAX_SECONDS - 1e-9 for sleep in clock.sleeps)
    late = [t for t in show_times if t >= 1.0]
    late_gaps = [b - a for a, b in zip(late, late[1:], strict=False) if b - a > 1e-12]
    assert late_gaps
    assert min(late_gaps) >= 0.4


def test_follow_poll_state_carries_backoff_across_slices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    _patch_clock(monkeypatch, clock)
    _patch_show(monkeypatch, lambda _run_id: _running())
    monkeypatch.setattr(
        "sase.tool.control_wait.reconcile_unsettled_tool_runs", lambda: {}
    )
    state = WaitPollState()
    wait_for_settlement("r" * 32, timeout_s=0.5, poll_state=state)
    assert state.delay > _POLL_START_SECONDS
    delay_after_first_slice = state.delay
    wait_for_settlement("r" * 32, timeout_s=0.5, poll_state=state)
    assert state.delay == _POLL_MAX_SECONDS
    assert state.delay >= delay_after_first_slice


def test_follow_settlement_deadline_and_stop_outcomes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = _Clock()
    _patch_clock(monkeypatch, clock)

    def show_then_settle(_run_id: str) -> dict[str, Any]:
        if clock.now >= 0.2:
            return _settled()
        return _running()

    _patch_show(monkeypatch, show_then_settle)
    monkeypatch.setattr(
        "sase.tool.control_wait.reconcile_unsettled_tool_runs", lambda: {}
    )
    settled = follow_run("r" * 32, deadline_s=3.0, stream_output=False)
    assert settled.kind == "settled"
    assert settled.envelope is not None
    assert settled.envelope["run"]["state"] == "succeeded"

    clock.now = 0.0
    clock.sleeps.clear()
    _patch_show(monkeypatch, lambda _run_id: _running())
    deadline = follow_run("r" * 32, deadline_s=1.0, stream_output=False)
    assert deadline.kind == "deadline"
    assert clock.now == pytest.approx(1.0)

    clock.now = 0.0
    clock.sleeps.clear()
    stop = threading.Event()

    def show_and_stop(_run_id: str) -> dict[str, Any]:
        stop.set()
        return _running()

    _patch_show(monkeypatch, show_and_stop)
    stopped = follow_run("r" * 32, deadline_s=3.0, stream_output=False, stop_event=stop)
    assert stopped.kind == "stopped"
    assert clock.now == pytest.approx(0.5)


def test_follow_unknown_run_still_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _Clock()
    _patch_clock(monkeypatch, clock)
    _patch_show(monkeypatch, lambda _run_id: {"diagnostics": ["missing"]})
    monkeypatch.setattr(
        "sase.tool.control_wait.reconcile_unsettled_tool_runs", lambda: {}
    )
    with pytest.raises(UnknownRunError):
        follow_run("r" * 32, deadline_s=1.0, stream_output=False)


def _patch_reconcile_list(
    monkeypatch: pytest.MonkeyPatch,
    run: dict[str, Any],
    *,
    ingest_diagnostics: list[str] | None = None,
) -> list[tuple[str, str]]:
    ingest_calls: list[tuple[str, str]] = []

    def fake_list(payload: dict[str, Any]) -> dict[str, Any]:
        if payload.get("state") == "running":
            return {"runs": [run], "diagnostics": []}
        return {"runs": [], "diagnostics": []}

    def fake_ingest(path: Any, run_id: str) -> list[str]:
        ingest_calls.append((str(path), run_id))
        return list(ingest_diagnostics or [])

    monkeypatch.setattr("sase.tool.liveness.tool_run_list", fake_list)
    monkeypatch.setattr("sase.tool.liveness.ingest_event_file", fake_ingest)
    monkeypatch.setattr(
        "sase.tool.liveness.tool_run_reconcile",
        lambda _payload: {
            "schema_version": 1,
            "marked_lost": [],
            "persisted": False,
            "diagnostics": [],
        },
    )
    monkeypatch.setattr("sase.tool.liveness.observe_owner_fact", lambda _run: None)
    return ingest_calls


def test_unchanged_events_file_is_not_re_ingested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text("{}\n", encoding="utf-8")
    run_id = "e" * 32
    run = {
        "run_id": run_id,
        "state": "running",
        "wrapper_pid": 1,
        "logs": {"events_path": str(events)},
    }
    ingest_calls = _patch_reconcile_list(monkeypatch, run)
    monkeypatch.setattr("sase.tool.liveness._EVENT_INGEST_STATS", OrderedDict())
    reconcile_unsettled_tool_runs()
    reconcile_unsettled_tool_runs()
    reconcile_unsettled_tool_runs(reap_orphans=True)
    assert ingest_calls == [(str(events), run_id)]

    events.write_text("{}\n{}\n", encoding="utf-8")
    reconcile_unsettled_tool_runs()
    assert ingest_calls == [(str(events), run_id), (str(events), run_id)]


def test_failed_event_ingest_is_retried_on_unchanged_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    events = tmp_path / "events.jsonl"
    events.write_text("{}\n", encoding="utf-8")
    run_id = "e" * 32
    run = {
        "run_id": run_id,
        "state": "running",
        "wrapper_pid": 1,
        "logs": {"events_path": str(events)},
    }
    ingest_calls = _patch_reconcile_list(
        monkeypatch, run, ingest_diagnostics=["store busy"]
    )
    monkeypatch.setattr("sase.tool.liveness._EVENT_INGEST_STATS", OrderedDict())
    reconcile_unsettled_tool_runs()
    reconcile_unsettled_tool_runs()
    assert ingest_calls == [(str(events), run_id), (str(events), run_id)]
