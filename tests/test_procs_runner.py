"""Process-level tests for durable proc submission and supervision."""

from __future__ import annotations

import os
import signal
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import sase.procs.runner as proc_runner
from sase.ace.hooks.processes import is_process_running
from sase.sessions import SessionIdentity
from sase.procs import (
    COMMAND_PROC_KIND,
    DETACHED_PROC_KIND,
    Proc,
    ProcControlError,
    ProcSubmitError,
    append_proc,
    get_proc,
    kill_proc,
    read_procs,
    reconcile_running_procs,
    submit_detached_proc,
    submit_proc,
    wait_for_proc,
)


def test_submit_supervisor_captures_output_and_proc_environment(
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
    proc = submit_proc(
        [
            sys.executable,
            "-c",
            (
                "import os,sys; "
                "print('out', flush=True); "
                "print('err', file=sys.stderr, flush=True); "
                "print(os.environ['SASE_PROC_ID'], flush=True); "
                "print(os.environ['SASE_PROC_LOG_PATH'], flush=True); "
                "print(os.environ['SASE_PROC_SESSION_ID'], flush=True); "
                "print(os.environ['PROC_RUNNER_TEST'], flush=True); "
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
            "PROC_RUNNER_TEST": "propagated",
        },
    )

    finished = wait_for_proc(proc.proc_id, timeout=10, on_line=lines.append)

    assert finished.status == "success"
    assert finished.exit_code == 0
    assert finished.pid is not None
    assert finished.pgid is not None
    assert finished.session_label == "ace·sase#14"
    assert finished.tags == ["runner", "test"]
    assert lines == [
        "out",
        "err",
        proc.proc_id,
        proc.log_path,
        "session-test",
        "propagated",
        str(tmp_path / "child-home"),
    ]


def test_supervisor_records_nonzero_and_unspawnable_commands(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    failed = submit_proc(
        [sys.executable, "-c", "raise SystemExit(7)"],
        label="Fails",
        cwd=tmp_path,
        origin="test",
    )
    missing = submit_proc(
        [str(tmp_path / "missing-executable")],
        label="Missing",
        cwd=tmp_path,
        origin="test",
    )

    failed_result = wait_for_proc(failed.proc_id, timeout=10)
    missing_result = wait_for_proc(missing.proc_id, timeout=10)

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
    with pytest.raises(ProcSubmitError, match="non-empty argv"):
        submit_proc([], label="Empty", cwd=tmp_path)
    with pytest.raises(ProcSubmitError, match="existing directory"):
        submit_proc(["true"], label="Bad cwd", cwd=tmp_path / "missing")
    assert read_procs() == []

    def fail_spawn(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("detachment failed")

    monkeypatch.setattr("sase.procs.spawn.subprocess.Popen", fail_spawn)
    with pytest.raises(ProcSubmitError, match="detachment failed"):
        submit_proc(["true"], label="Visible failure", cwd=tmp_path)

    procs = read_procs()
    assert len(procs) == 1
    assert procs[0].status == "error"
    assert procs[0].message == ("could not start proc supervisor: detachment failed")


def test_legacy_detached_submit_creates_unattributed_command_row(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """The legacy detached API now stays unattributed without writing that kind."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    identity = SessionIdentity(
        session_id="session-live",
        kind="ace",
        pid=os.getpid(),
        started_at="2026-07-25T12:00:00Z",
        project="sase",
        workspace_num=14,
    )
    monkeypatch.setattr("sase.sessions.live_sessions", lambda: [identity])

    proc = submit_detached_proc(
        [sys.executable, "-c", "print('detached', flush=True)"],
        label="Epic launch",
        cwd=tmp_path,
        origin="telegram",
        project="sase",
        tags=["epic", "launch"],
    )
    lines: list[str] = []
    finished = wait_for_proc(proc.proc_id, timeout=10, on_line=lines.append)

    assert proc.kind == COMMAND_PROC_KIND
    assert proc.session_id is None
    assert proc.session_label is None
    assert proc.origin == "telegram"
    assert proc.tags == ["epic", "launch"]
    assert finished.status == "success"
    assert finished.session_id is None
    assert lines == ["detached"]
    assert read_procs(session_id=None) == [finished]


def test_ace_origin_proc_is_owned_by_its_supervisor_pid(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """ACE submits work; the recorded active owner is the proc supervisor."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    proc = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="ACE durable work",
        cwd=tmp_path,
        origin="ace",
    )
    running = _wait_for_running(proc.proc_id)

    try:
        assert running.pid is not None
        assert running.pid != os.getpid()
        assert running.supervisor_id
        assert is_process_running(running.pid)
    finally:
        kill_proc(proc.proc_id)
        wait_for_proc(proc.proc_id, timeout=10)


def test_detached_submit_validates_argv_and_cwd(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    with pytest.raises(ProcSubmitError, match="non-empty argv"):
        submit_detached_proc([], label="Empty", cwd=tmp_path, origin="cli")
    with pytest.raises(ProcSubmitError, match="existing directory"):
        submit_detached_proc(
            ["true"], label="Bad cwd", cwd=tmp_path / "missing", origin="cli"
        )
    assert read_procs() == []


def test_kill_proc_terminates_a_detached_proc(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    proc = submit_detached_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Long detached launch",
        cwd=tmp_path,
        origin="cli",
    )
    running = _wait_for_running(proc.proc_id)

    killed = kill_proc(proc.proc_id)
    finished = wait_for_proc(proc.proc_id, timeout=10)

    assert killed.status == "killed"
    assert finished.status == "killed"
    assert running.pid is not None
    _wait_for_process_exit(running.pid)


def test_kill_proc_terminates_the_supervised_process_group(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    proc = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Long running",
        cwd=tmp_path,
        origin="test",
    )
    running = _wait_for_running(proc.proc_id)

    killed = kill_proc(proc.proc_id)
    finished = wait_for_proc(proc.proc_id, timeout=10)

    assert killed.status == "killed"
    assert finished.status == "killed"
    assert finished.finished_at is not None
    assert running.pid is not None
    _wait_for_process_exit(running.pid)


def test_reconcile_marks_missing_supervisors_error(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    orphan = _recorded_proc(
        "orphan-proc1",
        pid=999_999_999,
        status="running",
        tmp_path=tmp_path,
    )
    pending = _recorded_proc(
        "pending-proc",
        pid=None,
        status="pending",
        tmp_path=tmp_path,
    )
    append_proc(orphan)
    append_proc(pending)

    reconciled = reconcile_running_procs()

    assert {proc.proc_id for proc in reconciled} == {
        orphan.proc_id,
        pending.proc_id,
    }
    assert all(proc.status == "error" for proc in reconciled)
    assert all(
        proc.message == "supervisor exited without reporting" for proc in reconciled
    )


def test_reconcile_leaves_a_just_submitted_row_alone(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """A row appended moments ago has no supervisor pid yet, but is not dead.

    Terminalizing it here would race the supervisor's own ``running`` write,
    which the store then refuses because terminal states are final.
    """
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    fresh = _recorded_proc(
        "fresh-proc01",
        pid=None,
        status="pending",
        tmp_path=tmp_path,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    append_proc(fresh)

    assert reconcile_running_procs() == []

    current = get_proc(fresh.proc_id)
    assert current is not None
    assert current.status == "pending"


def test_reconcile_leaves_live_mirrored_tui_rows_alone(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """In-TUI procs remain active while their owning process is alive."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    mirrored = _recorded_proc(
        "mirrored-tui",
        pid=os.getpid(),
        status="running",
        tmp_path=tmp_path,
        kind="tui",
    )
    append_proc(mirrored)

    assert reconcile_running_procs() == []

    current = get_proc(mirrored.proc_id)
    assert current is not None
    assert current.status == "running"


def test_reconcile_terminalizes_mirrored_tui_rows_after_owner_exit(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    mirrored = _recorded_proc(
        "orphaned-tui",
        pid=999_999_999,
        status="running",
        tmp_path=tmp_path,
        kind="tui",
    )
    append_proc(mirrored)

    reconciled = reconcile_running_procs()

    assert [proc.proc_id for proc in reconciled] == [mirrored.proc_id]
    assert reconciled[0].status == "error"


def test_store_kill_rejects_tui_owned_procs(monkeypatch: Any, tmp_path: Path) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    mirrored = _recorded_proc(
        "mirrored-tui",
        pid=os.getpid(),
        status="running",
        tmp_path=tmp_path,
        kind="tui",
    )
    append_proc(mirrored)

    with pytest.raises(ProcControlError, match="owning ACE session"):
        kill_proc(mirrored.proc_id)

    assert get_proc(mirrored.proc_id) == mirrored


def test_store_kill_rejects_a_reused_supervisor_pid(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    reused = _recorded_proc(
        "reused-pid01",
        pid=os.getpid(),
        status="running",
        tmp_path=tmp_path,
    )
    append_proc(reused)

    with pytest.raises(ProcControlError, match="recorded supervisor"):
        kill_proc(reused.proc_id)

    current = get_proc(reused.proc_id)
    assert current is not None
    assert current.status == "error"


def test_reconcile_owns_stale_pidless_detached_rows(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """A detached submit that died before it spawned must not sit pending."""
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    stale = _recorded_proc(
        "stale-detach",
        pid=None,
        status="pending",
        tmp_path=tmp_path,
        kind=DETACHED_PROC_KIND,
    )
    fresh = _recorded_proc(
        "fresh-detach",
        pid=None,
        status="pending",
        tmp_path=tmp_path,
        kind=DETACHED_PROC_KIND,
        created_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    )
    append_proc(stale)
    append_proc(fresh)

    reconciled = reconcile_running_procs()

    assert [proc.proc_id for proc in reconciled] == [stale.proc_id]
    assert reconciled[0].status == "error"
    current = get_proc(fresh.proc_id)
    assert current is not None
    assert current.status == "pending"


def test_killed_supervisor_is_reconciled_to_terminal_error(
    monkeypatch: Any, tmp_path: Path
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "home"))
    proc = submit_proc(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        label="Orphaned",
        cwd=tmp_path,
        origin="test",
    )
    running = _wait_for_running(proc.proc_id)
    assert running.pid is not None
    assert running.pgid is not None

    try:
        os.kill(running.pid, signal.SIGKILL)
        _wait_for_process_exit(running.pid)
        reconciled = reconcile_running_procs()
        current = get_proc(proc.proc_id)

        assert [item.proc_id for item in reconciled] == [proc.proc_id]
        assert current is not None
        assert current.status == "error"
        assert current.message == "supervisor exited without reporting"
    finally:
        try:
            os.killpg(running.pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _recorded_proc(
    proc_id: str,
    *,
    pid: int | None,
    status: str,
    tmp_path: Path,
    kind: str = "command",
    created_at: str = "2020-01-01T00:00:00Z",
) -> Proc:
    return Proc(
        proc_id=proc_id,
        label=proc_id,
        kind=kind,
        status=status,
        command=["true"],
        cwd=str(tmp_path),
        origin="test",
        created_at=created_at,
        log_path=str(tmp_path / f"{proc_id}.log"),
        pid=pid,
    )


def _wait_for_running(proc_id: str) -> Proc:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        proc = get_proc(proc_id)
        assert proc is not None
        if proc.status == "running":
            return proc
        if proc.status not in {"pending", "running"}:
            pytest.fail(f"proc became {proc.status} before it was observed running")
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
    pytest.fail("proc did not enter running state")


def _wait_for_process_exit(pid: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not is_process_running(pid):
            return
        time.sleep(min(0.025, max(0.0, deadline - time.monotonic())))
    pytest.fail(f"process {pid} did not exit")
