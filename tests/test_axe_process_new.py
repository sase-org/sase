"""Tests for the new process control module (orchestrator-based)."""

import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.process import (
    get_axe_pid,
    get_axe_status,
    get_lumberjack_names,
    is_axe_running,
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Patch state directories for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    state_dir.mkdir(parents=True, exist_ok=True)
    pid_file = state_dir / "orchestrator.pid"
    lj_dir = state_dir / "lumberjacks"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.orchestrator.AXE_STATE_DIR", state_dir),
        patch("sase.axe.orchestrator.ORCHESTRATOR_PID_FILE", pid_file),
        patch("sase.axe.process.ORCHESTRATOR_PID_FILE", pid_file),
        patch("sase.axe.state.LUMBERJACK_STATE_DIR", lj_dir),
    ):
        yield state_dir


# --- is_axe_running Tests ---


def test_is_axe_running_no_pid_file(temp_state_dir: Path) -> None:
    """Test that is_axe_running returns False when no PID file exists."""
    assert is_axe_running() is False


@patch("sase.axe.process.is_process_running", return_value=True)
def test_is_axe_running_with_running_process(
    mock_running: MagicMock, temp_state_dir: Path
) -> None:
    """Test that is_axe_running returns True when orchestrator is running."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text(str(os.getpid()))
    assert is_axe_running() is True


@patch("sase.axe.process.is_process_running", return_value=False)
def test_is_axe_running_stale_pid(
    mock_running: MagicMock, temp_state_dir: Path
) -> None:
    """Test that is_axe_running returns False with stale PID."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("99999")
    assert is_axe_running() is False


# --- get_axe_pid Tests ---


def test_get_axe_pid_no_file(temp_state_dir: Path) -> None:
    """Test that get_axe_pid returns None when no PID file."""
    assert get_axe_pid() is None


@patch("sase.axe.process.is_process_running", return_value=True)
def test_get_axe_pid_with_orchestrator(
    mock_running: MagicMock, temp_state_dir: Path
) -> None:
    """Test that get_axe_pid returns orchestrator PID."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("42")
    assert get_axe_pid() == 42


@patch("sase.axe.process.is_process_running", return_value=True)
def test_get_axe_pid_falls_back_to_legacy(
    mock_running: MagicMock, temp_state_dir: Path
) -> None:
    """Test that get_axe_pid falls back to legacy PID file."""
    legacy_pid_file = temp_state_dir / "pid"
    legacy_pid_file.write_text("99")
    assert get_axe_pid() == 99


# --- get_axe_status Tests ---


def test_get_axe_status_not_running(temp_state_dir: Path) -> None:
    """Test that get_axe_status returns None when not running."""
    assert get_axe_status() is None


@patch("sase.axe.process.read_status", return_value=None)
@patch("sase.axe.process.is_process_running", return_value=True)
def test_get_axe_status_initializing(
    mock_running: MagicMock, mock_read: MagicMock, temp_state_dir: Path
) -> None:
    """Test status returns initializing when status file not written yet."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text(str(os.getpid()))

    status = get_axe_status()
    assert status is not None
    assert "initializing" in status["status"]


# --- get_lumberjack_names Tests ---


@patch("sase.axe.process.load_axe_config")
def test_get_lumberjack_names_returns_defaults(mock_load: MagicMock) -> None:
    """Test that get_lumberjack_names returns configured names."""
    from sase.axe.config import _default_lumberjacks

    mock_load.return_value = MagicMock(lumberjacks=_default_lumberjacks())
    names = get_lumberjack_names()
    assert sorted(names) == ["checks", "comments", "hooks", "housekeeping"]


@patch("sase.axe.process.load_axe_config")
def test_get_lumberjack_names_empty(mock_load: MagicMock) -> None:
    """Test that get_lumberjack_names returns empty list when no lumberjacks."""
    mock_load.return_value = MagicMock(lumberjacks={})
    names = get_lumberjack_names()
    assert names == []
