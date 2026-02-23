"""Tests for the new process control module (orchestrator-based)."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.process import (
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


@patch("sase.axe.process.is_process_running", return_value=False)
def test_is_axe_running_stale_pid(
    mock_running: MagicMock, temp_state_dir: Path
) -> None:
    """Test that is_axe_running returns False with stale PID."""
    pid_file = temp_state_dir / "orchestrator.pid"
    pid_file.write_text("99999")
    assert is_axe_running() is False


# --- get_axe_pid Tests ---


# --- get_axe_status Tests ---


# --- get_lumberjack_names Tests ---
