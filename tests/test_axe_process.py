"""Tests for the axe process control module."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sase.axe.process import (
    get_axe_status,
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


# --- is_axe_running Tests ---


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
