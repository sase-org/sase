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
    lumberjack_dir = state_dir / "lumberjacks"
    with (
        patch("sase.axe.state.axe_state_dir", return_value=state_dir),
        patch("sase.axe.state.jack_state_dir", return_value=lumberjack_dir),
    ):
        yield state_dir


# --- is_axe_running Tests ---


@patch("sase.axe._process_probe.is_process_running", return_value=False)
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
