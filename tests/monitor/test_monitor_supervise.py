"""Tests for :mod:`sase.monitor.supervise`."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from sase.ace.hooks.processes import is_process_running
from sase.monitor.supervise import run_supervisor
from sase.running_field import WorkspaceClaim, get_claimed_workspaces

from ._fixtures import make_starter_agent, write_project_file

_STOP_POLL_TIMEOUT = 60.0
_STOP_POLL_INTERVAL = 0.1


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


@pytest.fixture(autouse=True)
def _restore_signal_handlers() -> Iterator[None]:
    """``run_supervisor`` installs process-wide SIGTERM/SIGINT handlers.

    Called directly (not via a subprocess) it would otherwise leak that
    installation into the rest of the test session.
    """
    original_term = signal.getsignal(signal.SIGTERM)
    original_int = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGTERM, original_term)
    signal.signal(signal.SIGINT, original_int)


def _make_member(
    tmp_path: Path,
    *,
    command: str,
    timeout_seconds: float = 60.0,
    idle_timeout_seconds: float = 0.0,
    next_action: str | None = None,
    workspace_num: int = 1,
    claim_workflow: str = "ace-monitor",
) -> tuple[str, str]:
    extra_meta = {}
    if idle_timeout_seconds > 0:
        extra_meta["monitor_idle_timeout_seconds"] = idle_timeout_seconds
    project_file = write_project_file(
        "proj",
        running_claims=[
            WorkspaceClaim(workspace_num, claim_workflow, "acme", pid=os.getpid())
        ],
    )
    artifacts_dir = make_starter_agent(
        "proj",
        "20260812120000",
        "acme--mon",
        agent_family="acme",
        agent_family_role="monitor",
        monitor_id="abc123def456",
        monitor_command=command,
        monitor_cwd=str(tmp_path),
        monitor_reason="test",
        monitor_start_status="MONITORING",
        monitor_stop_status="MONITORED",
        monitor_timeout_seconds=timeout_seconds,
        monitor_next_action=next_action,
        monitor_state="running",
        cl_name="acme",
        workspace_dir=str(tmp_path),
        workspace_num=workspace_num,
        **extra_meta,
    )
    return artifacts_dir, project_file


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

    done = json.loads((Path(artifacts_dir) / "done.json").read_text())
    assert done["outcome"] == "monitored"
    assert done["monitor_state"] == "completed"
    assert done["monitor_exit_code"] == 0
    assert done["status_label"] == "MONITORED"
    assert done["response_path"]

    live_reply = (Path(artifacts_dir) / "live_reply.md").read_text()
    assert "hello world" in live_reply

    # No next action: the claim taken in _make_member is released.
    assert get_claimed_workspaces(project_file) == []


def test_run_supervisor_records_a_non_zero_exit_as_failed(tmp_path: Path) -> None:
    artifacts_dir, _ = _make_member(tmp_path, command="sh -c 'echo boom >&2; exit 3'")

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 1
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "failed"
    assert meta["monitor_exit_code"] == 3
    assert "boom" in (Path(artifacts_dir) / "live_reply.md").read_text()


def test_run_supervisor_kills_the_whole_process_group_on_timeout(
    tmp_path: Path,
) -> None:
    pidfile = tmp_path / "grandchild.pid"
    command = f"sh -c 'sleep 30 & echo $! > {pidfile}; wait'"
    artifacts_dir, _ = _make_member(tmp_path, command=command, timeout_seconds=0.3)

    started = time.monotonic()
    exit_status = run_supervisor(artifacts_dir)
    elapsed = time.monotonic() - started

    assert exit_status == 1
    assert elapsed < 5.0
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"

    grandchild_pid = int(pidfile.read_text().strip())
    assert not is_process_running(grandchild_pid)


def test_run_supervisor_holds_the_claim_when_the_followup_launch_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir, project_file = _make_member(
        tmp_path, command="true", next_action="Report that it finished."
    )
    import sase.monitor.supervise as supervise_module

    monkeypatch.setattr(supervise_module, "launch_followup_agent", lambda *a, **k: True)

    run_supervisor(artifacts_dir)

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "completed"
    # engine-next transfers this claim to the follow-up agent it launches;
    # the supervisor itself must never release it on success.
    assert len(get_claimed_workspaces(project_file)) == 1


def test_run_supervisor_releases_the_claim_when_the_followup_launch_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts_dir, project_file = _make_member(
        tmp_path, command="true", next_action="Report that it finished."
    )
    import sase.monitor.supervise as supervise_module

    def fake_launch_failure(
        _artifacts_dir: str, meta: dict[str, object], **_kwargs: object
    ) -> bool:
        meta["monitor_followup_error"] = "boom"
        return False

    monkeypatch.setattr(supervise_module, "launch_followup_agent", fake_launch_failure)

    run_supervisor(artifacts_dir)

    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "completed"
    # A failed follow-up launch must not leave the workspace claimed forever.
    assert get_claimed_workspaces(project_file) == []


def test_run_supervisor_release_matches_only_monitor_workflow(tmp_path: Path) -> None:
    artifacts_dir, project_file = _make_member(
        tmp_path, command="true", claim_workflow="ace-run"
    )

    run_supervisor(artifacts_dir)

    claims = get_claimed_workspaces(project_file)
    assert [(claim.workspace_num, claim.workflow) for claim in claims] == [
        (1, "ace-run")
    ]


def test_run_supervisor_times_out_continuous_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_MONITOR_LOG_MAX_BYTES", "4096")
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sh -c 'while :; do echo chatty; done'",
        timeout_seconds=0.2,
    )

    started = time.monotonic()
    exit_status = run_supervisor(artifacts_dir)
    elapsed = time.monotonic() - started

    assert exit_status == 1
    assert elapsed < 2.0
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"
    assert (Path(artifacts_dir) / "live_reply.md").stat().st_size <= 4096


def test_run_supervisor_times_out_after_partial_line(tmp_path: Path) -> None:
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sh -c 'printf partial; sleep 30'",
        timeout_seconds=0.2,
    )

    started = time.monotonic()
    exit_status = run_supervisor(artifacts_dir)
    elapsed = time.monotonic() - started

    assert exit_status == 1
    assert elapsed < 2.0
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"
    assert (Path(artifacts_dir) / "live_reply.md").read_text() == "partial"


def test_run_supervisor_completes_when_grandchild_holds_stdout(
    tmp_path: Path,
) -> None:
    pidfile = tmp_path / "grandchild.pid"
    command = f"sh -c 'sleep 30 & echo $! > {pidfile}; echo parent done'"
    artifacts_dir, _ = _make_member(tmp_path, command=command, timeout_seconds=30.0)

    started = time.monotonic()
    try:
        exit_status = run_supervisor(artifacts_dir)
        elapsed = time.monotonic() - started

        assert exit_status == 0
        assert elapsed < 1.0
        meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
        assert meta["monitor_state"] == "completed"
        assert "parent done" in (Path(artifacts_dir) / "live_reply.md").read_text()
    finally:
        if pidfile.exists():
            grandchild_pid = int(pidfile.read_text().strip())
            _terminate_pid(grandchild_pid)


def test_run_supervisor_times_out_after_child_closes_stdio(tmp_path: Path) -> None:
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sh -c 'exec >/dev/null 2>&1; sleep 30'",
        timeout_seconds=0.2,
    )

    started = time.monotonic()
    exit_status = run_supervisor(artifacts_dir)
    elapsed = time.monotonic() - started

    assert exit_status == 1
    assert elapsed < 2.0
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"


def test_run_supervisor_idle_timeout_fires_after_output_stalls(tmp_path: Path) -> None:
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sh -c 'echo started; sleep 30'",
        timeout_seconds=30.0,
        idle_timeout_seconds=0.2,
    )

    started = time.monotonic()
    exit_status = run_supervisor(artifacts_dir)
    elapsed = time.monotonic() - started

    assert exit_status == 1
    assert elapsed < 2.0
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"
    assert meta["monitor_timeout_kind"] == "idle"
    assert meta["monitor_timeout_message"] == "no output for 0.2s"
    done = json.loads((Path(artifacts_dir) / "done.json").read_text())
    assert done["monitor_timeout_kind"] == "idle"
    assert done["monitor_timeout_message"] == "no output for 0.2s"


def test_run_supervisor_chatty_command_does_not_hit_idle_timeout(
    tmp_path: Path,
) -> None:
    command = (
        f'{sys.executable} -u -c "import sys, time; '
        "[(sys.stdout.write('tick\\\\n'), sys.stdout.flush(), time.sleep(0.05)) "
        'for _ in range(4)]"'
    )
    artifacts_dir, _ = _make_member(
        tmp_path,
        command=command,
        timeout_seconds=5.0,
        idle_timeout_seconds=0.2,
    )

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 0
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "completed"
    assert "monitor_timeout_kind" not in meta


def test_run_supervisor_quiet_command_without_idle_timeout_completes(
    tmp_path: Path,
) -> None:
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sleep 0.2",
        timeout_seconds=5.0,
    )

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 0
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "completed"


def test_run_supervisor_survives_invalid_utf8_output(tmp_path: Path) -> None:
    command = (
        f'{sys.executable} -c "import sys, time; '
        "sys.stdout.buffer.write(b'bad\\\\xff\\\\n'); "
        'sys.stdout.flush(); time.sleep(30)"'
    )
    artifacts_dir, _ = _make_member(tmp_path, command=command, timeout_seconds=0.2)

    exit_status = run_supervisor(artifacts_dir)

    assert exit_status == 1
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"
    assert (Path(artifacts_dir) / "live_reply.md").read_bytes().startswith(b"bad\xff")


def test_run_supervisor_escalates_term_ignoring_chatty_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.monitor.supervise as supervise_module

    monkeypatch.setattr(supervise_module, "_KILL_GRACE_SECONDS", 0.2)
    monkeypatch.setenv("SASE_MONITOR_LOG_MAX_BYTES", "4096")
    artifacts_dir, _ = _make_member(
        tmp_path,
        command="sh -c 'trap \"\" TERM; while :; do echo stubborn; done'",
        timeout_seconds=0.2,
    )

    started = time.monotonic()
    exit_status = run_supervisor(artifacts_dir)
    elapsed = time.monotonic() - started

    assert exit_status == 1
    assert elapsed < 2.0
    meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
    assert meta["monitor_state"] == "timeout"
    assert (Path(artifacts_dir) / "live_reply.md").stat().st_size <= 4096


def test_supervisor_subprocess_stops_cleanly_on_sigterm(tmp_path: Path) -> None:
    ready_file = tmp_path / "ready"
    artifacts_dir, project_file = _make_member(
        tmp_path, command=f"touch {ready_file} && sleep 30", timeout_seconds=120.0
    )

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "sase.monitor.supervise",
            "--artifacts-dir",
            artifacts_dir,
        ],
        env=os.environ.copy(),
    )
    try:
        deadline = time.monotonic() + _STOP_POLL_TIMEOUT
        while not ready_file.exists() and time.monotonic() < deadline:
            time.sleep(_STOP_POLL_INTERVAL)
        assert ready_file.exists(), "monitored command never started"

        process.send_signal(signal.SIGTERM)
        process.wait(timeout=_STOP_POLL_TIMEOUT)

        meta = json.loads((Path(artifacts_dir) / "agent_meta.json").read_text())
        assert meta["monitor_state"] == "stopped"
        done = json.loads((Path(artifacts_dir) / "done.json").read_text())
        assert done["monitor_state"] == "stopped"
        # A stopped monitor releases the claim -- no follow-up is launched.
        assert get_claimed_workspaces(project_file) == []
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def _terminate_pid(pid: int) -> None:
    if not is_process_running(pid):
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + 2.0
    while is_process_running(pid) and time.monotonic() < deadline:
        time.sleep(0.05)  # sase-test-wait: poll orphaned grandchild cleanup
    if is_process_running(pid):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
