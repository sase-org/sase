"""Tests for the axe process control module."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sase.axe.config import AxeConfig
from sase.axe.process import (
    get_axe_status,
    restart_axe_daemon,
    start_axe_daemon,
    stop_axe_daemon,
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Create a temporary state directory for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    state_dir.mkdir(parents=True, exist_ok=True)
    orch_pid_file = state_dir / "orchestrator.pid"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
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
    mock_is_running.assert_any_call(22222)


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

    # First call: pid lookup says running; subsequent calls: process exited
    mock_is_running.side_effect = [True, False]

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

    mock_is_running.return_value = True
    mock_kill.side_effect = ProcessLookupError

    assert stop_axe_daemon() is False
    # PID file should be cleaned up
    assert not pid_file.exists()


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
