"""Tests for the axe process control module."""

from collections.abc import Iterator
import os
from pathlib import Path
import signal
import subprocess
import sys
from unittest.mock import MagicMock, patch

import pytest
from sase.axe.config import AxeConfig
from sase.axe.desired_state import read_desired_state
from sase.axe.lock import AxeLifecycleLock
from sase.axe._process_probe import cleanup_pid_files, probe_orchestrator
from sase.axe._process_start import (
    _build_axe_start_command,
    _compose_axe_daemon_env,
    _wait_for_daemon_start,
)
from sase.axe._process_stop import _send_signal
from sase.axe._process_types import AxeOrchestratorProbe, TerminateResult
from sase.axe.process import (
    AxeStartResult,
    get_axe_status,
    restart_axe_daemon,
    start_axe_daemon,
    start_axe_daemon_result,
    stop_axe_daemon,
    stop_axe_daemon_result,
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Create a temporary state directory for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    state_dir.mkdir(parents=True, exist_ok=True)
    lumberjack_dir = state_dir / "lumberjacks"
    with (
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch("sase.axe.state.jack_state_dir", return_value=lumberjack_dir),
    ):
        yield state_dir


@pytest.fixture
def axe_config() -> AxeConfig:
    return AxeConfig(
        max_hook_runners=3,
        max_agent_runners=3,
        zombie_timeout_seconds=7200,
        query="",
        lumberjacks={},
    )


# --- is_axe_running Tests ---


# --- start_axe_daemon Tests ---


def test_compose_axe_daemon_env_strips_agent_and_chop_context() -> None:
    environ = {
        "PATH": "/bin",
        "SASE_AGENT": "1",
        "SASE_AGENT_NAME": "parent",
        "SASE_AGENT_AUTO_APPROVE": "1",
        "SASE_CHOP_NAME": "workflow_checks",
        "SASE_CHOP_LUMBERJACK": "hooks",
        "SASE_AXE_OTHER": "keep",
    }

    result = _compose_axe_daemon_env(environ)

    assert result == {
        "PATH": "/bin",
        "SASE_AXE_OTHER": "keep",
        "SASE_AXE_START_SOURCE": "start",
    }
    assert environ["SASE_AGENT_NAME"] == "parent"


@patch("sase.axe._process_start.subprocess.Popen")
@patch("sase.axe._process_probe.is_process_running", return_value=True)
def test_start_axe_daemon_returns_existing_pid(
    mock_is_running: MagicMock,
    mock_popen: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Already-running axe is neutral success."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("12345")

    assert start_axe_daemon(axe_config) == 12345
    mock_is_running.assert_called_once_with(12345)
    mock_popen.assert_not_called()


@patch("sase.axe._process_start.shutil.which", return_value="/usr/bin/sase")
@patch("sase.axe._process_probe.is_process_running", return_value=True)
def test_repeated_start_axe_daemon_spawns_once_after_pid_appears(
    mock_is_running: MagicMock,
    _mock_which: MagicMock,
    temp_state_dir: Path,
    axe_config: AxeConfig,
) -> None:
    """Repeated starts converge on the first live orchestrator PID."""
    import os

    pid_file = temp_state_dir / "orchestrator.pid"
    mock_proc = MagicMock()
    mock_proc.pid = 22222
    mock_proc.poll.return_value = None

    with patch("sase.axe._process_start.subprocess.Popen") as mock_popen:

        def fake_popen(*_args: object, **_kwargs: object) -> MagicMock:
            pid_file.write_text("22222")
            return mock_proc

        mock_popen.side_effect = fake_popen

        assert start_axe_daemon(axe_config) == 22222
        assert start_axe_daemon(axe_config) == 22222

    assert mock_popen.call_count == 1
    kwargs = mock_popen.call_args.kwargs
    assert kwargs["pass_fds"]
    assert "SASE_AXE_LIFECYCLE_LOCK_FD" in kwargs["env"]
    assert kwargs["cwd"] == os.path.expanduser("~")
    mock_is_running.assert_any_call(22222)


def test_wait_for_daemon_start_waits_for_published_pid() -> None:
    """A live child is not success until the daemon PID file is readable."""
    mock_proc = MagicMock()
    mock_proc.pid = 99999
    mock_proc.poll.return_value = None

    with (
        patch("sase.axe._process_start.get_axe_pid", side_effect=[None, 4321]),
        patch("sase.axe._process_start.time.sleep", return_value=None),
    ):
        assert _wait_for_daemon_start(mock_proc, timeout=1.0) == 4321


def test_wait_for_daemon_start_does_not_return_child_pid_on_timeout() -> None:
    """Timeout without a PID file is failure, even if the child is alive."""
    mock_proc = MagicMock()
    mock_proc.pid = 99999
    mock_proc.poll.return_value = None

    with patch("sase.axe._process_start.get_axe_pid", return_value=None):
        assert _wait_for_daemon_start(mock_proc, timeout=0.0) is None


def test_wait_for_daemon_start_returns_none_when_child_exits() -> None:
    """A dead spawned child without a published PID is startup failure."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1

    with (
        patch("sase.axe._process_start.get_axe_pid", return_value=None),
        patch("sase.axe._process_start.time.sleep", return_value=None),
    ):
        assert _wait_for_daemon_start(mock_proc, timeout=1.0) is None


def test_build_start_command_prefers_canonical_sase_from_ephemeral_workspace(
    tmp_path: Path,
    axe_config: AxeConfig,
) -> None:
    canonical = tmp_path / ".local" / "bin" / "sase"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("#!/bin/sh\n")
    ephemeral_python = (
        tmp_path
        / ".local"
        / "state"
        / "sase"
        / "workspaces"
        / "sase-org"
        / "sase"
        / "sase_42"
        / ".venv"
        / "bin"
        / "python"
    )
    ephemeral_python.parent.mkdir(parents=True)
    ephemeral_python.write_text("")

    with (
        patch("sase.axe._process_start.Path.home", return_value=tmp_path),
        patch("sase.axe._process_start.sys.executable", str(ephemeral_python)),
        patch("sase.axe._process_start.shutil.which", return_value=None),
        patch(
            "sase.axe._process_start._resolve_primary_workspace_sase",
            return_value=None,
        ),
    ):
        cmd = _build_axe_start_command(axe_config)

    assert cmd is not None
    assert cmd[0] == str(canonical)


def test_start_axe_daemon_result_reports_held_lock_without_pid(
    axe_config: AxeConfig,
    temp_state_dir: Path,
) -> None:
    """Start failure explains the held-lock/no-PID deadlock."""
    with (
        patch("sase.axe._process_start.get_axe_pid", return_value=None),
        patch(
            "sase.axe._process_start._acquire_lifecycle_lock_for_start",
            return_value=None,
        ),
        patch(
            "sase.axe._process_start.probe_orchestrator",
            return_value=AxeOrchestratorProbe(
                lock_held=True,
                lock_holder_pid=None,
                orchestrator_pid_file_pid=None,
                legacy_pid=None,
                running_pid=None,
            ),
        ),
    ):
        result = start_axe_daemon_result(axe_config)

    assert result.status == "blocked"
    assert result.pid is None
    assert "sase axe stop --force" in result.message
    marker = read_desired_state()
    assert marker is not None
    assert marker.state == "running"
    assert marker.source == "start"


# --- stop_axe_daemon Tests ---


def test_stop_axe_daemon_returns_false_when_no_pid_file(
    temp_state_dir: Path,
) -> None:
    """Test stop_axe_daemon returns False when no PID file exists."""
    assert stop_axe_daemon() is False
    marker = read_desired_state()
    assert marker is not None
    assert marker.state == "stopped"
    assert marker.source == "stop"


@patch("sase.axe._process_stop.os.kill")
@patch("sase.axe._process_probe.is_process_running")
def test_stop_axe_daemon_sends_sigterm(
    mock_is_running: MagicMock,
    mock_kill: MagicMock,
    temp_state_dir: Path,
) -> None:
    """Test stop_axe_daemon sends SIGTERM and waits for exit."""
    import signal

    pid_file = temp_state_dir / "pid"
    pid_file.write_text("12345")

    # Probe and terminate both see it running; the wait then sees exit.
    mock_is_running.side_effect = [True, True, False, False]

    assert stop_axe_daemon() is True
    mock_kill.assert_called_once_with(12345, signal.SIGTERM)


@patch("sase.axe._process_stop.os.kill")
@patch("sase.axe._process_probe.is_process_running")
def test_stop_axe_daemon_handles_process_not_found(
    mock_is_running: MagicMock,
    mock_kill: MagicMock,
    temp_state_dir: Path,
) -> None:
    """Test stop_axe_daemon handles ProcessLookupError."""
    pid_file = temp_state_dir / "pid"
    pid_file.write_text("12345")

    mock_is_running.side_effect = [True, True, False, False]
    mock_kill.side_effect = ProcessLookupError

    assert stop_axe_daemon() is False
    # PID file should be cleaned up
    assert not pid_file.exists()


@patch("sase.axe._process_stop.os.kill")
@patch("sase.axe._process_stop.is_lifecycle_lock_held", return_value=False)
@patch("sase.axe._process_probe.is_process_running", side_effect=[True, False])
def test_stop_axe_daemon_uses_lock_holder_when_pid_file_missing(
    mock_is_running: MagicMock,
    _mock_lock_held: MagicMock,
    mock_kill: MagicMock,
    temp_state_dir: Path,
) -> None:
    """A held lock with no PID file can still be stopped via holder PID."""
    import signal

    del temp_state_dir
    probe = AxeOrchestratorProbe(
        lock_held=True,
        lock_holder_pid=12345,
        orchestrator_pid_file_pid=None,
        legacy_pid=None,
        running_pid=12345,
    )
    stopped_probe = AxeOrchestratorProbe(
        lock_held=False,
        lock_holder_pid=None,
        orchestrator_pid_file_pid=None,
        legacy_pid=None,
        running_pid=None,
    )

    with patch(
        "sase.axe._process_stop.probe_orchestrator",
        side_effect=[probe, stopped_probe],
    ):
        result = stop_axe_daemon_result(timeout=1.0)

    assert result.orchestrator_pid == 12345
    assert result.orchestrator_stopped is True
    mock_kill.assert_called_once_with(12345, signal.SIGTERM)
    mock_is_running.assert_any_call(12345)


@patch("sase.axe._process_stop.os.kill")
def test_send_signal_refuses_current_pid_direct(
    mock_kill: MagicMock,
) -> None:
    assert _send_signal(os.getpid(), signal.SIGTERM) is False
    mock_kill.assert_not_called()


@patch("sase.axe._process_stop.os.kill")
@patch("sase.axe._process_stop.is_lifecycle_lock_held", return_value=False)
def test_stop_axe_daemon_filters_current_pid_before_terminating(
    _mock_lock_held: MagicMock,
    mock_kill: MagicMock,
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    current_pid = os.getpid()
    self_probe = AxeOrchestratorProbe(
        lock_held=False,
        lock_holder_pid=current_pid,
        orchestrator_pid_file_pid=None,
        legacy_pid=None,
        running_pid=current_pid,
    )
    stopped_probe = AxeOrchestratorProbe(
        lock_held=False,
        lock_holder_pid=None,
        orchestrator_pid_file_pid=None,
        legacy_pid=None,
        running_pid=None,
    )

    with patch(
        "sase.axe._process_stop.probe_orchestrator",
        side_effect=[self_probe, stopped_probe],
    ):
        result = stop_axe_daemon_result(timeout=1.0)

    assert result.orchestrator_pid is None
    assert result.orchestrator_signaled is False
    assert result.failed_pids == ()
    mock_kill.assert_not_called()


def test_cleanup_pid_files_preserves_different_live_orchestrator(
    temp_state_dir: Path,
) -> None:
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("22222\n")

    with patch(
        "sase.axe._process_probe.is_process_running",
        return_value=True,
    ):
        cleanup_pid_files(stopped_pid=11111)

    assert pid_file.read_text() == "22222\n"


def test_cleanup_pid_files_removes_dead_orchestrator(
    temp_state_dir: Path,
) -> None:
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("22222\n")

    with patch(
        "sase.axe._process_probe.is_process_running",
        return_value=False,
    ):
        cleanup_pid_files(stopped_pid=11111)

    assert not pid_file.exists()


def test_cleanup_pid_files_removes_stopped_orchestrator(
    temp_state_dir: Path,
) -> None:
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("11111\n")

    with patch("sase.axe._process_probe.is_process_running") as is_running:
        cleanup_pid_files(stopped_pid=11111)

    assert not pid_file.exists()
    is_running.assert_not_called()


@patch("sase.axe._process_stop.clear_lock_holder_pid")
@patch("sase.axe._process_stop.is_lifecycle_lock_held", return_value=False)
def test_stop_cleanup_preserves_pid_published_by_concurrent_restart(
    _mock_lock_held: MagicMock,
    _mock_clear_lock_holder: MagicMock,
    temp_state_dir: Path,
) -> None:
    """A late stop cleanup cannot remove a newly-started orchestrator PID."""
    old_pid = 11111
    new_pid = 22222
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text(f"{old_pid}\n")
    running_probe = AxeOrchestratorProbe(
        lock_held=True,
        lock_holder_pid=old_pid,
        orchestrator_pid_file_pid=old_pid,
        legacy_pid=None,
        running_pid=old_pid,
    )
    restarted_probe = AxeOrchestratorProbe(
        lock_held=True,
        lock_holder_pid=new_pid,
        orchestrator_pid_file_pid=new_pid,
        legacy_pid=None,
        running_pid=new_pid,
    )

    def stop_old_process(*_args: object, **_kwargs: object) -> TerminateResult:
        pid_file.write_text(f"{new_pid}\n")
        return TerminateResult(pid=old_pid, signaled=True, stopped=True)

    with (
        patch(
            "sase.axe._process_stop.probe_orchestrator",
            side_effect=[running_probe, restarted_probe],
        ),
        patch(
            "sase.axe._process_stop._terminate_process",
            side_effect=stop_old_process,
        ),
        patch("sase.axe._process_probe.is_process_running", return_value=True),
    ):
        result = stop_axe_daemon_result(record_desired_state=False)

    assert result.orchestrator_stopped is True
    assert pid_file.read_text() == f"{new_pid}\n"


def test_probe_orchestrator_resolves_recorded_daemon_over_acquirer(
    temp_state_dir: Path,
) -> None:
    path = temp_state_dir / "orchestrator.lock"
    path.write_text("24680")

    def is_running(pid: int) -> bool:
        return pid in {13579, 24680}

    with (
        patch("sase.axe._process_probe.is_lifecycle_lock_held", return_value=True),
        patch("sase.axe.lock._find_proc_lock_holder_pid", return_value=13579),
        patch("sase.ace.hooks.processes.is_process_running", side_effect=is_running),
        patch("sase.axe._process_probe.is_process_running", side_effect=is_running),
    ):
        probe = probe_orchestrator()

    assert probe.lock_holder_pid == 24680
    assert probe.running_pid == 24680


def test_stop_axe_daemon_targets_recorded_daemon_not_acquirer(
    temp_state_dir: Path,
) -> None:
    acquirer = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    daemon: subprocess.Popen[str] | None = None
    daemon_code = "\n".join(
        [
            "import os",
            "import signal",
            "import sys",
            "import time",
            "signal.signal(signal.SIGTERM, lambda _signum, _frame: os._exit(0))",
            "print(os.getpid(), flush=True)",
            "time.sleep(30)",
        ]
    )
    try:
        daemon = subprocess.Popen(
            [sys.executable, "-c", daemon_code],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert daemon.stdout is not None
        line = daemon.stdout.readline().strip()
        assert line, daemon.stderr.read() if daemon.stderr is not None else ""
        daemon_pid = int(line)

        path = temp_state_dir / "orchestrator.lock"
        path.write_text(f"{daemon_pid}\n")

        with (
            patch("sase.axe._process_probe.is_lifecycle_lock_held", return_value=True),
            patch(
                "sase.axe.lock._find_proc_lock_holder_pid",
                return_value=acquirer.pid,
            ),
        ):
            result = stop_axe_daemon_result(timeout=10.0, kill_timeout=1.0)

        assert result.orchestrator_pid == daemon_pid
        assert result.orchestrator_signaled is True
        assert result.orchestrator_stopped is True
        assert result.failed_pids == ()
        assert daemon.wait(timeout=1.0) == 0
        assert acquirer.poll() is None
    finally:
        if daemon is not None and daemon.poll() is None:
            daemon.terminate()
            try:
                daemon.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                daemon.kill()
                daemon.wait(timeout=2.0)
        if acquirer.poll() is None:
            acquirer.terminate()
            try:
                acquirer.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                acquirer.kill()
                acquirer.wait(timeout=2.0)


def test_stop_axe_daemon_targets_inherited_lock_daemon(
    temp_state_dir: Path,
) -> None:
    del temp_state_dir
    lock = AxeLifecycleLock.acquire(blocking=False)
    assert lock is not None
    handed_off = False
    proc: subprocess.Popen[str] | None = None
    child_code = "\n".join(
        [
            "import os",
            "import signal",
            "import sys",
            "import time",
            "fd = int(sys.argv[1])",
            "pid = os.getpid()",
            "os.lseek(fd, 0, os.SEEK_SET)",
            "os.ftruncate(fd, 0)",
            "os.write(fd, (str(pid) + '\\n').encode())",
            "os.fsync(fd)",
            "signal.signal(signal.SIGTERM, lambda _signum, _frame: os._exit(0))",
            "print(pid, flush=True)",
            "time.sleep(30)",
        ]
    )
    try:
        proc = subprocess.Popen(
            [sys.executable, "-c", child_code, str(lock.fd)],
            pass_fds=(lock.fd,),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert proc.stdout is not None
        line = proc.stdout.readline().strip()
        assert line, proc.stderr.read() if proc.stderr is not None else ""
        child_pid = int(line)

        lock.close_after_handoff()
        handed_off = True

        result = stop_axe_daemon_result(timeout=10.0, kill_timeout=1.0)

        assert result.orchestrator_pid == child_pid
        assert result.orchestrator_signaled is True
        assert result.orchestrator_stopped is True
        assert result.failed_pids == ()
        assert proc.wait(timeout=1.0) == 0
    finally:
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
        if not handed_off:
            lock.release()


@patch("sase.axe._process_stop.os.kill")
@patch("sase.axe._process_stop.is_lifecycle_lock_held", return_value=False)
@patch("sase.axe._process_probe.is_process_running", side_effect=[True, False, False])
def test_stop_axe_daemon_sweeps_orphaned_lumberjacks(
    _mock_is_running: MagicMock,
    _mock_lock_held: MagicMock,
    mock_kill: MagicMock,
    temp_state_dir: Path,
) -> None:
    """Stop sweeps lumberjacks even when no orchestrator exists."""
    import signal

    lumberjack_dir = temp_state_dir / "lumberjacks" / "hooks"
    lumberjack_dir.mkdir(parents=True)
    pid_file = lumberjack_dir / "pid"
    pid_file.write_text("22222")
    stopped_probe = AxeOrchestratorProbe(
        lock_held=False,
        lock_holder_pid=None,
        orchestrator_pid_file_pid=None,
        legacy_pid=None,
        running_pid=None,
    )

    with patch(
        "sase.axe._process_stop.probe_orchestrator",
        return_value=stopped_probe,
    ):
        result = stop_axe_daemon_result(timeout=1.0)

    assert result.orchestrator_pid is None
    assert result.lumberjacks_stopped == 1
    assert not pid_file.exists()
    mock_kill.assert_called_once_with(22222, signal.SIGTERM)


def test_restart_axe_daemon_returns_verified_result_pid(axe_config: AxeConfig) -> None:
    result = AxeStartResult(status="started", pid=2468, verified=True)
    with patch(
        "sase.axe._process_restart.restart_axe_daemon_result",
        return_value=result,
    ) as mock_restart:
        assert restart_axe_daemon(axe_config) == 2468

    mock_restart.assert_called_once_with(axe_config)


# --- get_axe_status Tests ---


@patch("sase.axe._process_probe.is_process_running")
def test_get_axe_status_returns_none_when_process_dead(
    mock_is_running: MagicMock,
    temp_state_dir: Path,
) -> None:
    """Test get_axe_status returns None when process is dead."""
    pid_file = temp_state_dir / "pid"
    pid_file.write_text("12345")

    mock_is_running.return_value = False

    assert get_axe_status() is None
    # PID file should be cleaned up
    assert not pid_file.exists()


@patch("sase.axe._process_probe.is_process_running")
def test_get_axe_status_returns_full_status_when_no_status_file(
    mock_is_running: MagicMock,
    temp_state_dir: Path,
) -> None:
    """Test get_axe_status returns full status dict when no status.json exists."""
    pid_file = temp_state_dir / "pid"
    pid_file.write_text("12345")

    mock_is_running.return_value = True

    status = get_axe_status()
    assert status is not None
    assert status["pid"] == 12345
    assert status["status"] == "running"
    # Should have all AxeStatus fields populated from config defaults
    assert "max_hook_runners" in status
    assert "max_agent_runners" in status
    assert "started_at" in status


# --- get_axe_pid Tests ---
