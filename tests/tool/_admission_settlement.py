"""Admission stop and child execution settlement tests."""

from __future__ import annotations

import threading

import pytest

from sase.core.tool_run import tool_run_show
from sase.tool.executor_run import run_recorded_body
from sase.tool.executor_signals import SignalState
from tests.tool._admission_helpers import (
    begin,
    clean_env,
    ctx,
    hold_slot,
    project,
    record_for_run,
    settle_run,
)


def test_stopped_waiter_settles_without_running_and_is_abandoned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}},
        script=f"touch {marker}",
    )
    hold_slot()
    run_id, resolved = begin()
    polls: list[int] = []

    def stop_after_a_wait() -> bool:
        polls.append(1)
        return len(polls) >= 3

    code = run_recorded_body(
        ctx(run_id, resolved, stop_recorded=stop_after_a_wait), SignalState()
    )

    assert code == 143
    assert not marker.exists()
    run = tool_run_show(run_id)["run"]
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "stop_requested"
    assert "command was not run" in (run.get("diagnostics") or [])
    assert record_for_run(run_id)["state"] == "abandoned"
    err = capsys.readouterr().err
    assert err.count(f"sase tool run {run_id}") == 1
    assert "sase: stopped waiting for a check slot (stop requested)" in err


def test_sigterm_while_waiting_settles_signaled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    hold_slot()
    run_id, resolved = begin()
    signals = SignalState()
    timer = threading.Timer(0.2, lambda: setattr(signals, "sigterm", True))
    timer.start()
    try:
        code = run_recorded_body(ctx(run_id, resolved), signals)
    finally:
        timer.join()

    assert code == 143
    run = tool_run_show(run_id)["run"]
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "signal"
    assert record_for_run(run_id)["state"] == "abandoned"


def test_admitted_run_executes_its_child_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}},
        script=f"echo x >> {marker}",
    )
    holder = hold_slot()
    run_id, resolved = begin()
    timer = threading.Timer(0.3, settle_run, args=(holder,))
    timer.start()
    try:
        code = run_recorded_body(ctx(run_id, resolved), SignalState())
    finally:
        timer.join()

    assert code == 0
    assert marker.read_text() == "x\n"
    run = tool_run_show(run_id)["run"]
    assert run["state"] == "succeeded"
    # duration_ms measures from the spawn, so it excludes the wait.
    assert run["duration_ms"] < record_for_run(run_id)["wait_ms"]
    err = capsys.readouterr().err
    assert err.count(f"sase tool run {run_id}") == 1
    assert err.index("sase: waiting for a check slot") < err.index(
        "sase: check slot granted"
    )
