"""Lifecycle controls: ``sase tool stop``, ``show -F``, and ``sase tool wait``."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

import pytest

from sase.config.core import clear_config_cache
from sase.core.process_identity import process_identity_token
from sase.core.tool_run import tool_run_begin, tool_run_finish, tool_run_show
from sase.tool.argv import resolve_run_argv
from sase.tool.control import (
    ToolStopCliRequest,
    ToolWaitCliRequest,
    handle_stop,
    handle_wait,
)
from sase.tool.handoff import reserve_handoff_run
from sase.tool.liveness import current_boot_id
from sase.tool.query import ToolShowCliRequest, handle_show


def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_PROC_LOG_PATH",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
        "SASE_BEAD_ID",
        "SASE_BEAD",
        "SASE_WORKSPACE_NUM",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    clear_config_cache()
    return home


def _seed_definition() -> dict:
    return {
        "schema_version": 1,
        "name": "seeded",
        "argv": ["true"],
        "description": "",
        "stages": "none",
        "inputs": [],
        "env": [],
        "args": "allow",
        "fingerprint": {"repos": [], "toolchain": {}},
    }


def _begin_foreground(state: str = "running", **overrides) -> str:
    request = {
        "schema_version": 1,
        "definition": _seed_definition(),
        "display_argv": ["true"],
        "project": "fixture",
        "commit_running": True,
    }
    if state == "running":
        pid = os.getpid()
        request.update(
            {
                "wrapper_pid": pid,
                "boot_id": current_boot_id() or None,
                "process_start_identity": process_identity_token(pid) or None,
            }
        )
    request.update(overrides)
    return tool_run_begin(request)["run"]["run_id"]


def _finish(run_id: str, state: str, exit_code: int | None) -> None:
    payload: dict = {
        "schema_version": 1,
        "run_id": run_id,
        "state": state,
        "duration_ms": 5,
    }
    if exit_code is not None:
        payload["exit_code"] = exit_code
    else:
        payload["terminal_cause"] = "owner_lost"
    tool_run_finish(payload)


def _reserve(owner_kind: str, owner_id: str) -> str:
    resolved = resolve_run_argv(["--", "true"])
    reservation = reserve_handoff_run(
        resolved, owner_kind=owner_kind, owner_id=owner_id
    )
    assert reservation.reserved, reservation.error
    return reservation.run_id


def test_stop_unknown_run_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    code = handle_stop(ToolStopCliRequest(run_id="0" * 32, json=False))
    assert code == 2
    assert "not found" in capsys.readouterr().err


def test_stop_settled_run_reports_already(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground()
    _finish(run_id, "succeeded", 0)
    code = handle_stop(ToolStopCliRequest(run_id=run_id, json=False))
    assert code == 0
    captured = capsys.readouterr()
    assert "already succeeded" in captured.out


def test_stop_nested_foreground_run_refuses_with_owner_pointer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    parent = _begin_foreground()
    child = _begin_foreground(parent_run_id=parent)
    code = handle_stop(ToolStopCliRequest(run_id=child, json=False))
    assert code == 2
    captured = capsys.readouterr()
    assert parent in captured.err
    assert f"sase tool stop {parent}" in captured.err


def test_stop_inline_run_with_stale_identity_signals_nothing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground(
        wrapper_pid=2**30,
        boot_id=current_boot_id() or None,
        process_start_identity="boot-0:1",
    )
    code = handle_stop(ToolStopCliRequest(run_id=run_id, json=False))
    assert code == 1
    captured = capsys.readouterr()
    assert "not signaling" in captured.err
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] == "running"


def test_stop_proc_handoff_before_start_settles_stopped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _reserve("proc", "proc-missing-1")
    code = handle_stop(ToolStopCliRequest(run_id=run_id, json=False))
    assert code == 0
    assert "stopped" in capsys.readouterr().out
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] == "signaled"
    assert shown["terminal_cause"] == "stop_requested"
    assert "command was not run" in shown["diagnostics"]


def test_stop_monitor_handoff_before_start_settles_stopped(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _reserve("monitor", "mon-missing-1")
    code = handle_stop(ToolStopCliRequest(run_id=run_id, json=False))
    assert code == 0
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] == "signaled"
    assert shown["terminal_cause"] == "stop_requested"


def test_stop_running_proc_handoff_reports_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.core.tool_run import tool_run_claim

    _clean_env(monkeypatch, tmp_path)
    run_id = _reserve("proc", "proc-missing-2")
    pid = os.getpid()
    claimed = tool_run_claim(
        {
            "schema_version": 1,
            "run_id": run_id,
            "owner_kind": "proc",
            "owner_id": "proc-missing-2",
            "wrapper_pid": pid,
            "boot_id": current_boot_id() or None,
            "process_start_identity": process_identity_token(pid) or None,
        }
    )
    assert claimed["outcome"] == "claimed"
    code = handle_stop(ToolStopCliRequest(run_id=run_id, json=False))
    assert code == 0
    assert "stop requested" in capsys.readouterr().out
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] == "running"
    assert shown["stop_request"] is not None


def test_stop_json_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground()
    _finish(run_id, "succeeded", 0)
    assert handle_stop(ToolStopCliRequest(run_id=run_id, json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["run_id"] == run_id
    assert payload["outcome"] == "already succeeded"
    assert payload["state"] == "succeeded"


def test_wait_unknown_run_exits_2(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    code = handle_wait(ToolWaitCliRequest(run_id="1" * 32))
    assert code == 2
    err = capsys.readouterr().err
    assert "not found" in err or "does not exist" in err


def test_wait_mirrors_exit_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground()
    _finish(run_id, "failed", 7)
    assert handle_wait(ToolWaitCliRequest(run_id=run_id)) == 7


def test_wait_without_exit_code_returns_1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground()
    _finish(run_id, "lost", None)
    assert handle_wait(ToolWaitCliRequest(run_id=run_id)) == 1
    assert "owner_lost" in capsys.readouterr().err


def test_wait_deadline_returns_124(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground()
    code = handle_wait(ToolWaitCliRequest(run_id=run_id, timeout_raw="1"))
    assert code == 124
    assert "still running" in capsys.readouterr().err


def test_wait_rejects_bad_timeout_and_tail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground()
    assert handle_wait(ToolWaitCliRequest(run_id=run_id, timeout_raw="nope")) == 2
    capsys.readouterr()
    assert handle_wait(ToolWaitCliRequest(run_id=run_id, tail_lines=-1)) == 2


def test_wait_json_shape(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground()
    _finish(run_id, "succeeded", 0)
    assert handle_wait(ToolWaitCliRequest(run_id=run_id, json=True)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == run_id
    assert payload["state"] == "succeeded"
    assert payload["exit_code"] == 0
    assert payload["timed_out"] is False


def test_show_follow_and_logs_is_usage_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    code = handle_show(
        ToolShowCliRequest(run_id="2" * 32, json=False, logs=True, follow=True)
    )
    assert code == 2
    assert "cannot be used together" in capsys.readouterr().err


def test_show_follow_on_settled_run_prints_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground()
    _finish(run_id, "succeeded", 0)
    code = handle_show(
        ToolShowCliRequest(run_id=run_id, json=False, logs=False, follow=True)
    )
    assert code == 0
    captured = capsys.readouterr()
    assert run_id in captured.out
    assert "CAUSE" in captured.out


def test_show_follow_json_on_settled_run(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground()
    _finish(run_id, "failed", 3)
    code = handle_show(
        ToolShowCliRequest(run_id=run_id, json=True, logs=False, follow=True)
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run"]["run_id"] == run_id
    assert payload["run"]["state"] == "failed"


def test_show_follow_streams_until_settlement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _begin_foreground()

    def _settle_later() -> None:
        time.sleep(0.5)  # sase-test-wait: let follow attach before settlement
        _finish(run_id, "succeeded", 0)

    worker = threading.Thread(target=_settle_later, daemon=True)
    worker.start()
    try:
        code = handle_show(
            ToolShowCliRequest(run_id=run_id, json=False, logs=False, follow=True)
        )
    finally:
        worker.join(timeout=30)
    assert code == 0
    assert run_id in capsys.readouterr().out


def test_show_human_renders_lifecycle_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _clean_env(monkeypatch, tmp_path)
    run_id = _reserve("proc", "proc-missing-3")
    assert handle_show(ToolShowCliRequest(run_id=run_id, json=False, logs=False)) == 0
    out = capsys.readouterr().out
    assert "LAUNCH" in out
    assert "handoff" in out
    assert "CAUSE" in out
    assert "STOP" in out
    assert "OWNERLOG" in out


def test_stop_live_inline_run_settles_stop_requested(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A real wrapper stopped via ``handle_stop`` settles without an exit code."""

    import subprocess
    import sys as _sys

    from sase.core.tool_run import tool_run_list

    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_RUN_ID",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    proc = subprocess.Popen(
        [_sys.executable, "-m", "sase", "tool", "run", "--", "sleep", "30"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        deadline = time.monotonic() + 20
        run_id = None
        while time.monotonic() < deadline:
            try:
                listed = tool_run_list({"schema_version": 1, "limit": 10})
            except Exception:  # noqa: BLE001 - store may still be creating.
                time.sleep(0.05)  # sase-test-wait: store create race
                continue
            for run in listed.get("runs") or ():
                if run.get("state") == "running":
                    run_id = run["run_id"]
                    break
            if run_id is not None:
                break
            time.sleep(0.05)  # sase-test-wait: poll running ToolRun row
        assert run_id is not None, "tool run did not become running"
        assert handle_stop(ToolStopCliRequest(run_id=run_id, json=False)) == 0
        assert proc.wait(timeout=15) == 143
        shown = tool_run_show(run_id)["run"]
        assert shown["state"] == "signaled"
        assert shown["terminal_cause"] == "stop_requested"
        assert shown.get("exit_code") is None
        assert handle_wait(ToolWaitCliRequest(run_id=run_id)) == 1
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)


def test_begin_records_owner_log_for_enclosed_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool.executor_recording import build_begin_request

    _clean_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SASE_PROC_ID", "proc-enclosing")
    monkeypatch.setenv("SASE_PROC_LOG_PATH", "/tmp/owner-test.log")
    resolved = resolve_run_argv(["--", "true"])
    request = build_begin_request(
        "run-id-for-test",
        resolved=resolved,
        owner_kind="proc",
        owner_id="proc-enclosing",
        parent_run_id=None,
        events_path=None,
        stdout_path=None,
        stderr_path=None,
    )
    assert request["owner_log_path"] == "/tmp/owner-test.log"
