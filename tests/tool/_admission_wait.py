"""Admission waiting, recovery, and slot lifecycle tests."""

from __future__ import annotations

import subprocess
import threading
from typing import Any

import pytest

from sase.core import tool_run as core
from sase.core.tool_run import tool_run_admission_poll, tool_run_show
from sase.tool import admission as gate
from sase.tool.executor_run import run_recorded_body
from sase.tool.executor_signals import SignalState
from tests.tool._admission_helpers import (
    admit,
    begin,
    clean_env,
    ctx,
    hold_slot,
    project,
    record_for_run,
    settle_run,
)

# -- the wait -----------------------------------------------------------------


def test_waiter_prints_counts_then_the_grant_and_records_the_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    holder = hold_slot()
    run_id, resolved = begin()
    timer = threading.Timer(0.4, settle_run, args=(holder,))
    timer.start()
    try:
        headers: list[bool] = []
        result = gate.admit_before_spawn(
            ctx(run_id, resolved),
            SignalState(),
            show_header=lambda: headers.append(True),
        )
    finally:
        timer.join()

    assert result.proceed and result.waited
    assert headers, "the run header prints before the waiting line"
    err = capsys.readouterr().err
    assert "sase: waiting for a check slot (limit 1: 1 running, 0 ahead)" in err
    assert err.count("sase: waiting for a check slot") == 1
    assert "sase: check slot granted after " in err
    record = record_for_run(run_id)
    assert record["state"] == "admitted"
    assert record["admitted_by"] == "slot"
    assert record["wait_ms"] > 0


def test_immediate_admission_prints_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 2}})
    hold_slot(limit=2)
    run_id, resolved = begin()

    result = admit(ctx(run_id, resolved))

    assert result.proceed and result.waited
    assert capsys.readouterr().err == ""
    assert record_for_run(run_id)["state"] == "admitted"


def test_max_wait_admits_over_the_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
    )
    holder = hold_slot()
    run_id, resolved = begin()

    result = admit(ctx(run_id, resolved))

    assert result.proceed
    err = capsys.readouterr().err
    assert "(max_wait_seconds 1); running over the limit of 1" in err
    record = record_for_run(run_id)
    assert record["state"] == "admitted"
    assert record["admitted_by"] == "max_wait"
    polled = tool_run_admission_poll({"schema_version": 1, "run_id": holder})
    assert {peer["run_id"] for peer in polled["holders"]} == {holder, run_id}


def test_force_settled_stops_before_the_child_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
        script=f"touch {marker}",
    )
    hold_slot()
    run_id, resolved = begin()
    monkeypatch.setattr(
        core,
        "tool_run_admission_force",
        lambda *_args, **_kwargs: {"outcome": "settled"},
    )

    assert run_recorded_body(ctx(run_id, resolved), SignalState()) == 143
    run = tool_run_show(run_id)["run"]
    assert not marker.exists()
    assert run["state"] == "signaled"
    assert "command was not run" in (run.get("diagnostics") or [])
    assert record_for_run(run_id)["state"] == "abandoned"


def test_force_not_found_falls_open_and_recovers_unavailable_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
        script=f"touch {marker}",
    )
    hold_slot()
    run_id, resolved = begin()
    original_force = core.tool_run_admission_force
    outcomes: list[str] = []

    def missing_max_wait(request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if request.get("reason") == "max_wait":
            return {"outcome": "not_found"}
        return original_force(request, **kwargs)

    monkeypatch.setattr(core, "tool_run_admission_force", missing_max_wait)
    monkeypatch.setattr(
        gate, "_count", lambda outcome, *_args: outcomes.append(outcome)
    )

    assert run_recorded_body(ctx(run_id, resolved), SignalState()) == 0
    run = tool_run_show(run_id)["run"]
    assert marker.exists()
    assert run["state"] == "succeeded"
    assert record_for_run(run_id)["admitted_by"] == "unavailable"
    assert "forced" not in outcomes
    assert "unavailable" in outcomes
    err = capsys.readouterr().err
    assert err.count("admission unavailable") == 1
    assert "no check slot after" not in err


def test_transient_force_error_retries_until_max_wait_is_confirmed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
    )
    hold_slot()
    run_id, resolved = begin()
    original_force = core.tool_run_admission_force
    calls = 0

    def one_transient_error(request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database is locked")
        return original_force(request, **kwargs)

    monkeypatch.setattr(core, "tool_run_admission_force", one_transient_error)

    result = admit(ctx(run_id, resolved))

    assert result.proceed
    assert calls >= 2
    assert record_for_run(run_id)["admitted_by"] == "max_wait"


def test_force_store_error_falls_open_and_recovers_before_child_settlement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
        script=f"sleep 1.5; touch {marker}",
    )
    hold_slot()
    run_id, resolved = begin()
    original_force = core.tool_run_admission_force
    monkeypatch.setattr(gate, "STORE_ERROR_GRACE_SECONDS", 0.15)

    def unavailable_during_force(
        request: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        if request.get("reason") == "max_wait":
            raise RuntimeError("database is locked")
        return original_force(request, **kwargs)

    monkeypatch.setattr(core, "tool_run_admission_force", unavailable_during_force)

    assert run_recorded_body(ctx(run_id, resolved), SignalState()) == 0
    run = tool_run_show(run_id)["run"]
    assert marker.exists()
    assert run["state"] == "succeeded"
    admission = record_for_run(run_id)
    assert admission["admitted_by"] == "unavailable"
    assert admission["wait_ms"] < run["duration_ms"]


def test_poll_failure_after_entry_recovers_the_bypass_at_a_later_write(
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
    monkeypatch.setattr(gate, "STORE_ERROR_GRACE_SECONDS", 0.15)
    monkeypatch.setattr(
        core,
        "tool_run_admission_poll",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database is locked")
        ),
    )
    original_force = core.tool_run_admission_force
    recoveries: list[dict[str, Any]] = []

    def recover_on_retry(request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if request.get("reason") == "unavailable":
            recoveries.append(dict(request))
            if len(recoveries) == 1:
                raise RuntimeError("database is locked")
        return original_force(request, **kwargs)

    monkeypatch.setattr(core, "tool_run_admission_force", recover_on_retry)

    assert run_recorded_body(ctx(run_id, resolved), SignalState()) == 0
    run = tool_run_show(run_id)["run"]
    admission = record_for_run(run_id)
    assert marker.exists()
    assert run["state"] == "succeeded"
    assert admission["state"] == "admitted"
    assert admission["admitted_by"] == "unavailable"
    # The pre-spawn bypass time survives the failed first write.
    assert len(recoveries) == 2
    assert {item["now_ms"] for item in recoveries} == {recoveries[0]["now_ms"]}
    assert admission["admitted_ts_ms"] == recoveries[0]["now_ms"]
    assert not any(
        "evidence incomplete" in item for item in (run.get("diagnostics") or [])
    )
    assert capsys.readouterr().err.count("admission unavailable") == 1


def test_unrecovered_bypass_is_named_in_settlement_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
    )
    hold_slot()
    run_id, resolved = begin()
    monkeypatch.setattr(gate, "STORE_ERROR_GRACE_SECONDS", 0.12)
    monkeypatch.setattr(
        core,
        "tool_run_admission_force",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database is locked")
        ),
    )

    assert run_recorded_body(ctx(run_id, resolved), SignalState()) == 0
    run = tool_run_show(run_id)["run"]
    assert run["state"] == "succeeded"
    assert record_for_run(run_id)["state"] == "abandoned"
    assert any(
        "admission bypass evidence incomplete" in item
        for item in (run.get("diagnostics") or [])
    )


@pytest.mark.parametrize(
    ("probe_name", "expected_cause"),
    [("stop_recorded", "stop_requested"), ("timeout_recorded", "timeout")],
)
def test_stop_or_timeout_during_force_retry_does_not_start_child(
    probe_name: str,
    expected_cause: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
        script=f"touch {marker}",
    )
    hold_slot()
    run_id, resolved = begin()
    monkeypatch.setattr(
        core,
        "tool_run_admission_force",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database is locked")
        ),
    )
    calls = 0

    def stop_after_retry() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 2

    code = run_recorded_body(
        ctx(run_id, resolved, **{probe_name: stop_after_retry}), SignalState()
    )
    run = tool_run_show(run_id)["run"]
    assert code == 143
    assert not marker.exists()
    assert run["terminal_cause"] == expected_cause
    assert "command was not run" in (run.get("diagnostics") or [])
    assert record_for_run(run_id)["state"] == "abandoned"


def test_dead_holder_is_reconciled_and_frees_its_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.core.process_identity import process_identity_token

    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    # A holder whose wrapper already exited: its pid is gone.
    gone = subprocess.Popen(["true"])
    identity = process_identity_token(gone.pid)
    gone.wait()
    holder = hold_slot(
        wrapper_pid=gone.pid,
        process_start_identity=identity or None,
    )
    run_id, resolved = begin()

    result = admit(ctx(run_id, resolved))

    assert result.proceed
    assert tool_run_show(holder)["run"]["state"] == "lost"
    assert record_for_run(run_id)["state"] == "admitted"
