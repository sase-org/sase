"""E2 settlement: retention reporting and real-supervisor timeouts."""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from typing import Any

import pytest

from sase.core.process_identity import process_identity_token
from sase.core.tool_run import tool_run_finish
from sase.procs import get_proc, new_proc_id, submit_proc_request, wait_for_proc
from sase.procs.models import Proc
from sase.procs.request import ProcSubmitRequest
from sase.tool.executor import ToolRunCliRequest, execute_tool_run
from sase.tool.handoff import (
    owner_request_fingerprint,
    owner_tags,
    worker_argv,
    worker_env_overlay,
)
from sase.tool.liveness import current_boot_id, reconcile_unsettled_tool_runs
from sase.tool.owner import owner_retention
from sase.tool.query import ToolShowCliRequest, handle_show
from tool._settlement_helpers import (
    claim,
    clean_env,
    expected_notification_id,
    fabricate_proc,
    get_run,
    reserve,
    tool_run_notifications,
)


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env(monkeypatch, tmp_path)


# --- Retention reporting ----------------------------------------------------


def test_pruned_owner_is_reported_by_show_json_and_logs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Row 9: the summary stays intact and the missing log is named."""

    gone_log = str(tmp_path / "pruned-owner.log")
    run_id = reserve("proc", "proc-pruned")
    claim(run_id, "proc", "proc-pruned", owner_log_path=gone_log)

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=True, logs=False)) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["owner_retention"] == {
        "owner": "pruned",
        "log": "missing",
        "log_path": gone_log,
    }
    assert envelope["run"]["run_id"] == run_id
    assert envelope["run"]["state"] == "lost"
    assert envelope["run"]["display_argv"] == ["true"]

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=False, logs=True)) == 0
    err = capsys.readouterr().err
    assert "proc owner proc-pruned is no longer retained (pruned)" in err
    assert f"its log {gone_log} is missing" in err

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=False, logs=False)) == 0
    out = capsys.readouterr().out
    assert "OWNERRET  proc proc-pruned: pruned; log not retained" in out


def test_pruned_owner_recorded_log_still_replays(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    log = tmp_path / "kept.log"
    log.write_text("kept output\n", encoding="utf-8")
    run_id = reserve("proc", "proc-pruned-kept")
    claim(run_id, "proc", "proc-pruned-kept", owner_log_path=str(log))

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=False, logs=True)) == 0
    captured = capsys.readouterr()
    assert "kept output" in captured.out


def test_follow_states_that_a_pruned_owner_has_no_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    gone_log = str(tmp_path / "gone.log")
    run_id = reserve("proc", "proc-follow")
    claim(run_id, "proc", "proc-follow", owner_log_path=gone_log)

    code = handle_show(
        ToolShowCliRequest(run_id=run_id, json=True, logs=False, follow=True)
    )

    assert code == 0
    captured = capsys.readouterr()
    assert captured.err.count("no longer retained") == 1
    assert json.loads(captured.out)["owner_retention"]["owner"] == "pruned"


def test_owner_retention_states(tmp_path: Path) -> None:
    assert owner_retention({"launch_mode": "foreground"}) == {
        "owner": "none",
        "log": "none",
        "log_path": None,
    }
    fabricate_proc(tmp_path, "proc-kept", None)
    run = {"owner_kind": "proc", "owner_id": "proc-kept", "logs": {}}
    live = owner_retention(run)
    assert live["owner"] == "retained"
    assert live["log"] == "missing"
    assert live["log_path"] == str(tmp_path / "proc-kept.log")
    (tmp_path / "proc-kept.log").write_text("x", encoding="utf-8")
    assert owner_retention(run)["log"] == "retained"
    unrecorded = owner_retention(
        {"owner_kind": "proc", "owner_id": "proc-never-existed", "logs": {}}
    )
    assert unrecorded == {"owner": "pruned", "log": "not-recorded", "log_path": None}


def test_persisted_diagnostics_render_in_show_json_and_human(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """sase-145: finish diagnostics are visible in ``show -j`` and the DIAG block."""

    run_id = reserve("proc", "proc-diag")
    claim(
        run_id,
        "proc",
        "proc-diag",
        identity=(os.getpid(), current_boot_id(), process_identity_token(os.getpid())),
    )
    tool_run_finish(
        {
            "schema_version": 1,
            "run_id": run_id,
            "state": "failed",
            "exit_code": 127,
            "duration_ms": 5,
            "terminal_cause": "exited",
            "diagnostics": ["spawn failed: executable not found: nope"],
        }
    )

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=True, logs=False)) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert "spawn failed: executable not found: nope" in envelope["run"]["diagnostics"]

    assert handle_show(ToolShowCliRequest(run_id=run_id, json=False, logs=False)) == 0
    out = capsys.readouterr().out
    assert "DIAG\n  spawn failed: executable not found: nope" in out


# --- Real supervisor: termination intent and timeouts -----------------------


def _result_reason(proc: Proc) -> object:
    assert isinstance(proc.result, dict)
    return proc.result["termination_reason"]


def _submit_worker(
    tmp_path: Path,
    words: tuple[str, ...],
    *,
    timeout_seconds: int | None = None,
    idle_timeout_seconds: int | None = None,
) -> tuple[str, str]:
    proc_id = new_proc_id()
    run_id = reserve("proc", proc_id, words)
    submit_proc_request(
        ProcSubmitRequest(
            argv=worker_argv(run_id),
            command=["sase", "tool", "run", *words],
            label="tool:ad-hoc",
            cwd=tmp_path,
            origin="tool-run",
            proc_id=proc_id,
            tags=owner_tags(run_id),
            env=worker_env_overlay(),
            request_fingerprint=owner_request_fingerprint(run_id),
            followup={"kind": "tool-run", "run_id": run_id},
            timeout_seconds=timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
        )
    )
    return run_id, proc_id


def _settled_run(run_id: str, *, timeout: float = 60.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        run = get_run(run_id)
        if run["state"] not in ("created", "running"):
            return run
        time.sleep(0.2)  # sase-test-wait: poll worker or hook settlement
    pytest.fail(f"run {run_id} did not settle")


def test_total_timeout_settles_signaled_timeout(tmp_path: Path) -> None:
    """Row 5: a real supervisor's total timeout is a timeout, not a bare signal."""

    run_id, proc_id = _submit_worker(tmp_path, ("--", "sleep", "30"), timeout_seconds=1)
    proc = wait_for_proc(proc_id, timeout=60)
    assert _result_reason(proc) == "total-timeout"
    run = _settled_run(run_id)
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "timeout"
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not tool_run_notifications():
        time.sleep(0.2)  # sase-test-wait: poll notification durability
    assert [item.id for item in tool_run_notifications()] == [
        expected_notification_id(run_id)
    ]


def test_idle_timeout_settles_signaled_timeout(tmp_path: Path) -> None:
    run_id, proc_id = _submit_worker(
        tmp_path,
        ("--", "sh", "-c", "echo started; sleep 30"),
        idle_timeout_seconds=1,
    )
    proc = wait_for_proc(proc_id, timeout=60)
    assert _result_reason(proc) == "idle-timeout"
    run = _settled_run(run_id)
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "timeout"


def test_handoff_end_to_end_publishes_one_notification(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Row 2: the launcher exits after submit and the worker settles the run."""

    request = ToolRunCliRequest(
        quiet=True,
        verbose=False,
        tail_lines=200,
        words=("--", "sh", "-c", "exit 0"),
        hand_off=True,
        tail_lines_explicit=False,
    )
    assert execute_tool_run(request) == 0
    run_id = capsys.readouterr().out.strip()
    run = _settled_run(run_id)
    assert run["state"] == "succeeded"
    assert run["settled_by"] != "owner"
    proc_id = run["owner_id"]
    wait_for_proc(proc_id, timeout=60)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not tool_run_notifications():
        time.sleep(0.2)  # sase-test-wait: poll notification durability
    reconcile_unsettled_tool_runs()
    assert [item.id for item in tool_run_notifications()] == [
        expected_notification_id(run_id)
    ]


def test_supervisor_sigterm_records_stop_intent_worker_settles_stop(
    tmp_path: Path,
) -> None:
    run_id, proc_id = _submit_worker(tmp_path, ("--", "sleep", "30"))
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and get_run(run_id)["state"] != "running":
        time.sleep(0.1)  # sase-test-wait: poll worker claim
    assert get_run(run_id)["state"] == "running"
    proc = get_proc(proc_id)
    assert proc is not None and proc.pid is not None
    os.kill(proc.pid, signal.SIGTERM)
    wait_for_proc(proc_id, timeout=60)
    run = _settled_run(run_id)
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "stop_requested"
