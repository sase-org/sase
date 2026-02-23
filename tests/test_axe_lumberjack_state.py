"""Tests for per-lumberjack state management in the axe state module."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.state import (
    LumberjackMetrics,
    LumberjackStatus,
    ensure_lumberjack_dirs,
    list_lumberjack_names,
    lumberjack_log_path,
    read_lumberjack_log_tail,
    read_lumberjack_metrics,
    read_lumberjack_pid,
    read_lumberjack_status,
    remove_lumberjack_pid,
    write_lumberjack_pid,
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Create a temporary state directory for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    lj_dir = state_dir / "lumberjacks"
    shared_dir = state_dir / "shared"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.LUMBERJACK_STATE_DIR", lj_dir),
        patch("sase.axe.state.SHARED_STATE_DIR", shared_dir),
    ):
        yield state_dir


# --- Directory Creation ---


# --- PID File ---


def test_remove_lumberjack_pid(temp_state_dir: Path) -> None:
    """Test removing a lumberjack PID file."""
    write_lumberjack_pid("hooks")
    assert read_lumberjack_pid("hooks") is not None
    remove_lumberjack_pid("hooks")
    assert read_lumberjack_pid("hooks") is None


def test_remove_lumberjack_pid_no_error_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that removing a non-existent PID file doesn't error."""
    remove_lumberjack_pid("hooks")  # Should not raise


# --- Status ---


def test_read_lumberjack_status_returns_none_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that read_lumberjack_status returns None when no file."""
    assert read_lumberjack_status("hooks") is None


def test_lumberjack_status_defaults() -> None:
    """Test LumberjackStatus default field values."""
    status = LumberjackStatus(
        name="test",
        pid=1,
        started_at="now",
        status="running",
        interval=1,
    )
    assert status.chops == []
    assert status.last_cycle is None
    assert status.cycles_run == 0
    assert status.errors_encountered == 0
    assert status.uptime_seconds == 0


# --- Metrics ---


def test_read_lumberjack_metrics_returns_none_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that read_lumberjack_metrics returns None when no file."""
    assert read_lumberjack_metrics("hooks") is None


def test_lumberjack_metrics_defaults() -> None:
    """Test LumberjackMetrics default values."""
    metrics = LumberjackMetrics()
    assert metrics.cycles_run == 0
    assert metrics.chops_executed == 0
    assert metrics.total_updates == 0
    assert metrics.errors_encountered == 0


# --- Log Paths ---


def test_read_lumberjack_log_tail_returns_content(
    temp_state_dir: Path,
) -> None:
    """Test reading lumberjack log tail."""
    ensure_lumberjack_dirs("hooks")
    log_path = lumberjack_log_path("hooks")
    log_path.write_text("line1\nline2\nline3\n")

    result = read_lumberjack_log_tail("hooks", lines=2)
    assert "line2" in result
    assert "line3" in result


def test_read_lumberjack_log_tail_returns_empty_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that read_lumberjack_log_tail returns empty for missing log."""
    assert read_lumberjack_log_tail("hooks") == ""


# --- Listing ---


def test_list_lumberjack_names_empty(temp_state_dir: Path) -> None:
    """Test listing lumberjack names when none exist."""
    assert list_lumberjack_names() == []


def test_list_lumberjack_names(temp_state_dir: Path) -> None:
    """Test listing lumberjack names after creating some."""
    ensure_lumberjack_dirs("hooks")
    ensure_lumberjack_dirs("checks")
    ensure_lumberjack_dirs("comments")

    names = list_lumberjack_names()
    assert names == ["checks", "comments", "hooks"]
