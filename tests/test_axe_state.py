"""Tests for the axe state management module."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest
from sase.axe.state import (
    AxeMetrics,
    CycleResult,
    append_error,
    read_cycle_result,
    read_errors,
    read_metrics,
    read_pid_file,
    read_status,
    write_cycle_result,
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Create a temporary state directory for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    with patch("sase.axe.state.AXE_STATE_DIR", state_dir):
        yield state_dir


# --- PID File Tests ---


def test_read_pid_file_returns_none_on_invalid_content(temp_state_dir: Path) -> None:
    """Test that read_pid_file returns None on invalid content."""
    with patch("sase.axe.state.AXE_STATE_DIR", temp_state_dir):
        temp_state_dir.mkdir(parents=True, exist_ok=True)
        pid_file = temp_state_dir / "pid"
        pid_file.write_text("not_a_number")
        assert read_pid_file() is None


# --- Status Tests ---


def test_read_status_returns_none_on_invalid_json(temp_state_dir: Path) -> None:
    """Test that read_status returns None on invalid JSON."""
    with patch("sase.axe.state.AXE_STATE_DIR", temp_state_dir):
        temp_state_dir.mkdir(parents=True, exist_ok=True)
        status_file = temp_state_dir / "status.json"
        status_file.write_text("not valid json")
        assert read_status() is None


# --- Cycle Result Tests ---


def test_write_and_read_hook_cycle_result(temp_state_dir: Path) -> None:
    """Test writing and reading hook cycle result."""
    with patch("sase.axe.state.AXE_STATE_DIR", temp_state_dir):
        result = CycleResult(
            timestamp="2025-01-15T10:00:05-05:00",
            cycle_type="hook",
            duration_ms=45,
            changespecs_processed=10,
            updates=[],
            errors=[],
        )
        write_cycle_result(result)

        read_result = read_cycle_result("hook")
        assert read_result is not None
        assert read_result.cycle_type == "hook"
        assert read_result.duration_ms == 45


def test_read_cycle_result_returns_none_when_missing(temp_state_dir: Path) -> None:
    """Test that read_cycle_result returns None when file doesn't exist."""
    with patch("sase.axe.state.AXE_STATE_DIR", temp_state_dir):
        assert read_cycle_result("full") is None
        assert read_cycle_result("hook") is None


# --- Metrics Tests ---


def test_read_metrics_returns_none_when_missing(temp_state_dir: Path) -> None:
    """Test that read_metrics returns None when file doesn't exist."""
    with patch("sase.axe.state.AXE_STATE_DIR", temp_state_dir):
        assert read_metrics() is None


def test_axe_metrics_default_values() -> None:
    """Test that AxeMetrics has sensible default values."""
    metrics = AxeMetrics()
    assert metrics.full_cycles_run == 0
    assert metrics.hook_cycles_run == 0
    assert metrics.total_updates == 0
    assert metrics.errors_encountered == 0


# --- Error Tests ---


def test_append_and_read_errors(temp_state_dir: Path) -> None:
    """Test appending and reading errors."""
    with patch("sase.axe.state.AXE_STATE_DIR", temp_state_dir):
        append_error({"timestamp": "t1", "job": "hooks", "error": "error 1"})
        append_error({"timestamp": "t2", "job": "mentors", "error": "error 2"})

        errors = read_errors()
        assert len(errors) == 2
        assert errors[0]["job"] == "hooks"
        assert errors[1]["job"] == "mentors"


def test_read_errors_returns_empty_list_when_missing(temp_state_dir: Path) -> None:
    """Test that read_errors returns empty list when file doesn't exist."""
    with patch("sase.axe.state.AXE_STATE_DIR", temp_state_dir):
        assert read_errors() == []


# --- Utility Tests ---


# --- Atomic Write Tests ---


# --- read_json Tests ---
