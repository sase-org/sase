"""Tests for :mod:`sase.monitor.supervise`.

These cover command spawn, completion, settlement, and the launch barrier.
Follow-up claim handling and timeout/process-tree behavior live in the sibling
``test_monitor_supervise_*`` modules.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sase.monitor.supervise import (
    _execution_argv,
    _popen_monitored_command,
    run_supervisor,
)
from sase.notifications.store import load_notifications
from sase.running_field import get_claimed_workspaces

from ._supervise import _make_member, _restore_signal_handlers, _sandbox_home


def test_execution_argv_reconstructs_bootstrap_from_persisted_meta() -> None:
    argv = [sys.executable, "code_swap_guarded_exec.py", "lock", "--", "sase"]
    assert _execution_argv({"monitor_execution_argv": argv}) == argv
    assert _execution_argv({}) is None
    assert _execution_argv({"monitor_execution_argv": []}) is None


def test_popen_monitored_command_uses_persisted_execution_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded: dict[str, object] = {}

    def fake_popen(*args: object, **kwargs: object) -> object:
        recorded["args"] = args
        recorded["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    argv = [sys.executable, "-c", "pass"]
    _popen_monitored_command(
        {"monitor_execution_argv": argv},
        command="sase bead work plan.md --yes-to-all",
        cwd=str(tmp_path),
        output_pipe=object(),  # type: ignore[arg-type]
        command_env={"PATH": "/bin"},
    )
    assert recorded["args"] == (argv,)
    kwargs = recorded["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is False
    assert kwargs["cwd"] == str(tmp_path)


def test_popen_monitored_command_keeps_shell_form_without_execution_argv(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded: dict[str, object] = {}

    def fake_popen(*args: object, **kwargs: object) -> object:
        recorded["args"] = args
        recorded["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    _popen_monitored_command(
        {},
        command="true",
        cwd=str(tmp_path),
        output_pipe=object(),  # type: ignore[arg-type]
        command_env={},
    )
    assert recorded["args"] == ("true",)
    kwargs = recorded["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs["shell"] is True


def test_run_supervisor_records_a_clean_completion_and_releases_the_claim(
    tmp_path: Path,
) -> None:
    artifacts_dir, project_file = _make_member(tmp_path, command="echo hello world")

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 0
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "completed"
    assert meta["monitor_exit_code"] == 0
    assert meta["monitor_output_truncated"] is False
    assert meta["monitor_output_path"] == str(Path(artifacts_dir) / "live_reply.md")
    assert meta["run_started_at"]

    done = json.loads((Path(artifacts_dir) / "done.json").read_text())
    assert done["outcome"] == "monitored"
    assert done["monitor_state"] == "completed"
    assert done["monitor_exit_code"] == 0
    assert done["status_label"] == "MONITORED"
    assert done["response_path"]
    assert isinstance(done["finished_at"], int | float)

    live_reply = (Path(artifacts_dir) / "live_reply.md").read_text()
    assert "hello world" in live_reply

    # No next action: the claim taken in _make_member is released.
    assert get_claimed_workspaces(project_file) == []
    # Monitor settlement is notification-neutral: terminal state lives in
    # agent_meta.json/done.json only, not as a routine notification row.
    assert load_notifications() == []


def test_run_supervisor_records_project_file_and_finalizes_workflow_state(
    tmp_path: Path,
) -> None:
    """Settling writes done.json::project_file and finalizes workflow_state.json.

    The member's workflow_state.json is launch scaffolding seeded by
    create_followup_artifacts() with status="running"; nothing else ever
    rewrites it, so settlement must finalize it to a terminal status while
    preserving fields other workflow_state.json consumers rely on.
    """
    artifacts_dir, project_file = _make_member(tmp_path, command="true")
    workflow_state_path = Path(artifacts_dir) / "workflow_state.json"
    workflow_state_path.write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "status": "running",
                "current_step_index": 0,
                "steps": [],
                "context": {"cl_name": "acme"},
                "artifacts_dir": artifacts_dir,
                "pid": os.getpid(),
                "appears_as_agent": True,
            }
        ),
        encoding="utf-8",
    )

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 0
    done = json.loads((Path(artifacts_dir) / "done.json").read_text())
    assert done["project_file"] == project_file

    workflow_state = json.loads(workflow_state_path.read_text())
    assert workflow_state["status"] == "completed"
    assert workflow_state["appears_as_agent"] is True
    assert workflow_state["context"] == {"cl_name": "acme"}


def test_run_supervisor_records_a_non_zero_exit_as_failed(tmp_path: Path) -> None:
    artifacts_dir, _ = _make_member(tmp_path, command="sh -c 'echo boom >&2; exit 3'")

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 1
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "failed"
    assert meta["monitor_exit_code"] == 3
    assert "boom" in (Path(artifacts_dir) / "live_reply.md").read_text()


def test_run_supervisor_fails_without_the_launch_barrier(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.supervise as supervise_module

    sentinel = tmp_path / "command-ran"
    monkeypatch.setattr(supervise_module, "MONITOR_LAUNCH_BARRIER_TIMEOUT_SECONDS", 0.1)
    artifacts_dir, project_file = _make_member(
        tmp_path,
        command=f"touch {sentinel}",
        timeout_seconds=30.0,
        go_barrier=False,
    )

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 1
    assert not sentinel.exists()
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "failed"
    assert meta["monitor_settled"] is True
    # Written as soon as the log is opened, before the barrier wait -- unlike
    # run_started_at, which only appears once the command actually spawns.
    assert meta["monitor_output_path"] == str(Path(artifacts_dir) / "live_reply.md")
    assert "run_started_at" not in meta
    done = json.loads((Path(artifacts_dir) / "done.json").read_text())
    assert done["monitor_state"] == "failed"
    assert "command was not run" in done["error"]
    assert get_claimed_workspaces(project_file) == []


def test_run_supervisor_scrubs_agent_identity_from_the_command_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme--0")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", "/some/dead/starter")
    env_dump = tmp_path / "env.out"
    command = f"env | grep -E '^SASE_(AGENT|ARTIFACTS_DIR)' > {env_dump}; true"
    artifacts_dir, _ = _make_member(tmp_path, command=command)

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 0
    assert env_dump.read_text() == ""
