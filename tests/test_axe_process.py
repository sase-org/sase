"""Tests for the axe process control module."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sase.axe.config import AxeConfig
from sase.axe.process import (
    _build_axe_start_command,
    _AxeOrchestratorProbe,
    _wait_for_daemon_start,
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
    orch_pid_file = state_dir / "orchestrator.pid"
    lumberjack_dir = state_dir / "lumberjacks"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.JACK_STATE_DIR", lumberjack_dir),
        patch("sase.axe.orchestrator.AXE_STATE_DIR", state_dir),
        patch("sase.axe.orchestrator.ORCHESTRATOR_PID_FILE", orch_pid_file),
        patch("sase.axe.process.ORCHESTRATOR_PID_FILE", orch_pid_file),
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


@patch("sase.axe.process.subprocess.Popen")
@patch("sase.axe.process.is_process_running", return_value=True)
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


@patch("sase.axe.process.shutil.which", return_value="/usr/bin/sase")
@patch("sase.axe.process.is_process_running", return_value=True)
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

    with patch("sase.axe.process.subprocess.Popen") as mock_popen:

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
        patch("sase.axe.process.get_axe_pid", side_effect=[None, 4321]),
        patch("sase.axe.process.time.sleep", return_value=None),
    ):
        assert _wait_for_daemon_start(mock_proc, timeout=1.0) == 4321


def test_wait_for_daemon_start_does_not_return_child_pid_on_timeout() -> None:
    """Timeout without a PID file is failure, even if the child is alive."""
    mock_proc = MagicMock()
    mock_proc.pid = 99999
    mock_proc.poll.return_value = None

    with patch("sase.axe.process.get_axe_pid", return_value=None):
        assert _wait_for_daemon_start(mock_proc, timeout=0.0) is None


def test_wait_for_daemon_start_returns_none_when_child_exits() -> None:
    """A dead spawned child without a published PID is startup failure."""
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 1

    with (
        patch("sase.axe.process.get_axe_pid", return_value=None),
        patch("sase.axe.process.time.sleep", return_value=None),
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
        patch("sase.axe.process.Path.home", return_value=tmp_path),
        patch("sase.axe.process.sys.executable", str(ephemeral_python)),
        patch("sase.axe.process.shutil.which", return_value=None),
        patch("sase.axe.process._resolve_primary_workspace_sase", return_value=None),
    ):
        cmd = _build_axe_start_command(axe_config)

    assert cmd is not None
    assert cmd[0] == str(canonical)


def test_start_axe_daemon_result_reports_held_lock_without_pid(
    axe_config: AxeConfig,
) -> None:
    """Start failure explains the held-lock/no-PID deadlock."""
    with (
        patch("sase.axe.process.get_axe_pid", return_value=None),
        patch("sase.axe.process._acquire_lifecycle_lock_for_start", return_value=None),
        patch(
            "sase.axe.process._probe_orchestrator",
            return_value=_AxeOrchestratorProbe(
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


# --- stop_axe_daemon Tests ---


def test_stop_axe_daemon_returns_false_when_no_pid_file(
    temp_state_dir: Path,
) -> None:
    """Test stop_axe_daemon returns False when no PID file exists."""
    assert stop_axe_daemon() is False


@patch("sase.axe.process.os.kill")
@patch("sase.axe.process.is_process_running")
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


@patch("sase.axe.process.os.kill")
@patch("sase.axe.process.is_process_running")
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


@patch("sase.axe.process.os.kill")
@patch("sase.axe.process.is_lifecycle_lock_held", return_value=False)
@patch("sase.axe.process.is_process_running", side_effect=[True, False])
def test_stop_axe_daemon_uses_lock_holder_when_pid_file_missing(
    mock_is_running: MagicMock,
    _mock_lock_held: MagicMock,
    mock_kill: MagicMock,
    temp_state_dir: Path,
) -> None:
    """A held lock with no PID file can still be stopped via holder PID."""
    import signal

    del temp_state_dir
    probe = _AxeOrchestratorProbe(
        lock_held=True,
        lock_holder_pid=12345,
        orchestrator_pid_file_pid=None,
        legacy_pid=None,
        running_pid=12345,
    )
    stopped_probe = _AxeOrchestratorProbe(
        lock_held=False,
        lock_holder_pid=None,
        orchestrator_pid_file_pid=None,
        legacy_pid=None,
        running_pid=None,
    )

    with patch(
        "sase.axe.process._probe_orchestrator",
        side_effect=[probe, stopped_probe],
    ):
        result = stop_axe_daemon_result(timeout=1.0)

    assert result.orchestrator_pid == 12345
    assert result.orchestrator_stopped is True
    mock_kill.assert_called_once_with(12345, signal.SIGTERM)
    mock_is_running.assert_any_call(12345)


@patch("sase.axe.process.os.kill")
@patch("sase.axe.process.is_lifecycle_lock_held", return_value=False)
@patch("sase.axe.process.is_process_running", side_effect=[True, False, False])
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
    stopped_probe = _AxeOrchestratorProbe(
        lock_held=False,
        lock_holder_pid=None,
        orchestrator_pid_file_pid=None,
        legacy_pid=None,
        running_pid=None,
    )

    with patch("sase.axe.process._probe_orchestrator", return_value=stopped_probe):
        result = stop_axe_daemon_result(timeout=1.0)

    assert result.orchestrator_pid is None
    assert result.lumberjacks_stopped == 1
    assert not pid_file.exists()
    mock_kill.assert_called_once_with(22222, signal.SIGTERM)


def test_restart_axe_daemon_stops_then_starts(axe_config: AxeConfig) -> None:
    with (
        patch("sase.axe.process.stop_axe_daemon") as mock_stop,
        patch("sase.axe.process.start_axe_daemon", return_value=2468) as mock_start,
    ):
        assert restart_axe_daemon(axe_config) == 2468

    mock_stop.assert_called_once_with()
    mock_start.assert_called_once_with(axe_config)


# --- get_axe_status Tests ---


@patch("sase.axe.process.is_process_running")
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


@patch("sase.axe.process.is_process_running")
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
