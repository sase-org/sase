"""Process-level tests for detached task submission and supervision."""

from __future__ import annotations

import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import sase.tasks.runner as task_runner
from sase.ace.hooks.processes import is_process_running
from sase.sessions import SessionIdentity
from sase.tasks import (
    BackgroundTask,
    TaskSubmitError,
    append_task,
    get_task,
    kill_task,
    read_tasks,
    reconcile_running_tasks,
    submit_task,
    wait_for_task,
)


def test_submit_supervisor_captures_output_and_task_environment(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    identity = SessionIdentity(
        session_id="session-test",
        kind="ace",
        pid=os.getpid(),
        started_at="2026-07-25T12:00:00Z",
        project="sase",
        workspace_num=14,
    )
    monkeypatch.setattr("sase.sessions.live_sessions", lambda: [identity])
    lines: list[str] = []
    task = submit_task(
        [
            sys.executable,
            "-c",
            (
                "import os,sys; "
                "print('out', flush=True); "
                "print('err', file=sys.stderr, flush=True); "
                "print(os.environ['SASE_TASK_ID'], flush=True); "
                "print(os.environ['SASE_TASK_LOG_PATH'], flush=True); "
                "print(os.environ['SASE_TASK_SESSION_ID'], flush=True); "
                "print(os.environ['TASK_RUNNER_TEST'], flush=True); "
                "print(os.environ['SASE_HOME'], flush=True)"
            ),
        ],
        label="Environment",
        cwd=tmp_path,
        session_id="session-test",
        project="sase",
        workspace_num=14,
        tags=["test", "runner", "test"],
        origin="test",
        env={
            "SASE_HOME": str(tmp_path / "child-home"),
            "TASK_RUNNER_TEST": "propagated",
        },
    )

    finished = wait_for_task(task.task_id, timeout=10, on_line=lines.append)

    assert finished.status == "success"
    assert finished.exit_code == 0
    assert finished.pid is not None
    assert finished.pgid is not None
    assert finished.session_label == "ace·sase#14"
    assert finished.tags == ["runner", "test"]
    assert lines == [
        "out",
        "err",
        task.task_id,
        task.log_path,
        "session-test",
        "propagated",
        str(tmp_path / "child-home"),
    ]


def test_supervisor_records_nonzero_and_unspawnable_commands(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    failed = submit_task(
        [sys.executable, "-c", "raise SystemExit(7)"],
        label="Fails",
        cwd=tmp_path,
        origin="test",
    )
    missing = submit_task(
        [str(tmp_path / "missing-executable")],
        label="Missing",
        cwd=tmp_path,
        origin="test",
    )

    failed_result = wait_for_task(failed.task_id, timeout=10)
    missing_result = wait_for_task(missing.task_id, timeout=10)

    assert failed_result.status == "error"
    assert failed_result.exit_code == 7
    assert failed_result.message == "exited with code 7"
    assert missing_result.status == "error"
    assert missing_result.exit_code is None
    assert missing_result.message is not None
    assert missing_result.message.startswith("could not start command:")


def test_submit_validation_and_supervisor_spawn_failure_stay_visible(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    with pytest.raises(TaskSubmitError, match="non-empty argv"):
        submit_task([], label="Empty", cwd=tmp_path)
    with pytest.raises(TaskSubmitError, match="existing directory"):
        submit_task(["true"], label="Bad cwd", cwd=tmp_path / "missing")
    assert read_tasks() == []

    def fail_spawn(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("detachment failed")

    monkeypatch.setattr(task_runner.subprocess, "Popen", fail_spawn)
    with pytest.raises(TaskSubmitError, match="detachment failed"):
        submit_task(["true"], label="Visible failure", cwd=tmp_path)

    tasks = read_tasks()
    assert len(tasks) == 1
    assert tasks[0].status == "error"
    assert tasks[0].message == ("could not start task supervisor: detachment failed")


def test_kill_task_terminates_the_supervised_process_group(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    task = submit_task(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Long running",
        cwd=tmp_path,
        origin="test",
    )
    running = _wait_for_running(task.task_id)

    killed = kill_task(task.task_id)
    finished = wait_for_task(task.task_id, timeout=10)

    assert killed.status == "killed"
    assert finished.status == "killed"
    assert finished.finished_at is not None
    assert running.pid is not None
    _wait_for_process_exit(running.pid)


def test_reconcile_marks_missing_supervisors_error(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    orphan = _recorded_task(
        "orphan-task1",
        pid=999_999_999,
        status="running",
        tmp_path=tmp_path,
    )
    pending = _recorded_task(
        "pending-task",
        pid=None,
        status="pending",
        tmp_path=tmp_path,
    )
    append_task(orphan)
    append_task(pending)

    reconciled = reconcile_running_tasks()

    assert {task.task_id for task in reconciled} == {
        orphan.task_id,
        pending.task_id,
    }
    assert all(task.status == "error" for task in reconciled)
    assert all(
        task.message == "supervisor exited without reporting" for task in reconciled
    )


def test_reconcile_leaves_a_just_submitted_row_alone(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """A row appended moments ago has no supervisor pid yet, but is not dead.

    Terminalizing it here would race the supervisor's own ``running`` write,
    which the store then refuses because terminal states are final.
    """
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    fresh = _recorded_task(
        "fresh-task01",
        pid=None,
        status="pending",
        tmp_path=tmp_path,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    append_task(fresh)

    assert reconcile_running_tasks() == []

    current = get_task(fresh.task_id)
    assert current is not None
    assert current.status == "pending"


def test_reconcile_leaves_mirrored_tui_rows_alone(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """In-TUI tasks record no supervisor pid; their own process owns them."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    mirrored = _recorded_task(
        "mirrored-tui",
        pid=None,
        status="running",
        tmp_path=tmp_path,
        kind="tui",
    )
    append_task(mirrored)

    assert reconcile_running_tasks() == []

    current = get_task(mirrored.task_id)
    assert current is not None
    assert current.status == "running"


def test_killed_supervisor_is_reconciled_to_terminal_error(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    task = submit_task(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Orphaned",
        cwd=tmp_path,
        origin="test",
    )
    running = _wait_for_running(task.task_id)
    assert running.pid is not None
    assert running.pgid is not None

    try:
        os.kill(running.pid, signal.SIGKILL)
        _wait_for_process_exit(running.pid)
        reconciled = reconcile_running_tasks()
        current = get_task(task.task_id)

        assert [item.task_id for item in reconciled] == [task.task_id]
        assert current is not None
        assert current.status == "error"
        assert current.message == "supervisor exited without reporting"
    finally:
        try:
            os.killpg(running.pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _recorded_task(
    task_id: str,
    *,
    pid: int | None,
    status: str,
    tmp_path: Path,
    kind: str = "command",
    created_at: str = "2020-01-01T00:00:00Z",
) -> BackgroundTask:
    return BackgroundTask(
        task_id=task_id,
        label=task_id,
        kind=kind,
        status=status,
        command=["true"],
        cwd=str(tmp_path),
        origin="test",
        created_at=created_at,
        log_path=str(tmp_path / f"{task_id}.log"),
        pid=pid,
    )


def _wait_for_running(task_id: str) -> BackgroundTask:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        task = get_task(task_id)
        assert task is not None
        if task.status == "running":
            return task
        if task.status not in {"pending", "running"}:
            pytest.fail(f"task became {task.status} before it was observed running")
        time.sleep(0.025)
    pytest.fail("task did not enter running state")


def _wait_for_process_exit(pid: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not is_process_running(pid):
            return
        time.sleep(0.025)
    pytest.fail(f"process {pid} did not exit")
