"""Tests for per-jack state management in the axe state module."""

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.state import (
    JackMetrics,
    JackStatus,
    ensure_jack_dirs,
    list_jack_names,
    jack_log_path,
    read_jack_log_tail,
    read_jack_metrics,
    read_jack_pid,
    read_jack_status,
    remove_jack_pid,
    write_jack_pid,
)


@pytest.fixture
def temp_state_dir(tmp_path: Path) -> Iterator[Path]:
    """Create a temporary state directory for testing."""
    state_dir = tmp_path / ".sase" / "axe"
    jack_dir = state_dir / "jacks"
    shared_dir = state_dir / "shared"
    with (
        patch("sase.axe.state.AXE_STATE_DIR", state_dir),
        patch("sase.axe.state.JACK_STATE_DIR", jack_dir),
        patch("sase.axe.state.SHARED_STATE_DIR", shared_dir),
    ):
        yield state_dir


# --- Directory Creation ---


# --- PID File ---


def test_remove_jack_pid(temp_state_dir: Path) -> None:
    """Test removing a jack PID file."""
    write_jack_pid("hooks")
    assert read_jack_pid("hooks") is not None
    remove_jack_pid("hooks")
    assert read_jack_pid("hooks") is None


def test_remove_jack_pid_no_error_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that removing a non-existent PID file doesn't error."""
    remove_jack_pid("hooks")  # Should not raise


# --- Status ---


def test_read_jack_status_returns_none_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that read_jack_status returns None when no file."""
    assert read_jack_status("hooks") is None


def test_jack_status_defaults() -> None:
    """Test JackStatus default field values."""
    status = JackStatus(
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


def test_read_jack_metrics_returns_none_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that read_jack_metrics returns None when no file."""
    assert read_jack_metrics("hooks") is None


def test_jack_metrics_defaults() -> None:
    """Test JackMetrics default values."""
    metrics = JackMetrics()
    assert metrics.cycles_run == 0
    assert metrics.chops_executed == 0
    assert metrics.total_updates == 0
    assert metrics.errors_encountered == 0


# --- Log Paths ---


def test_read_jack_log_tail_returns_content(
    temp_state_dir: Path,
) -> None:
    """Test reading jack log tail."""
    ensure_jack_dirs("hooks")
    log_path = jack_log_path("hooks")
    log_path.write_text("line1\nline2\nline3\n")

    result = read_jack_log_tail("hooks", lines=2)
    assert "line2" in result
    assert "line3" in result


def test_read_jack_log_tail_returns_empty_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that read_jack_log_tail returns empty for missing log."""
    assert read_jack_log_tail("hooks") == ""


# --- Listing ---


def test_list_jack_names_empty(temp_state_dir: Path) -> None:
    """Test listing jack names when none exist."""
    assert list_jack_names() == []


def test_list_jack_names(temp_state_dir: Path) -> None:
    """Test listing jack names after creating some."""
    ensure_jack_dirs("hooks")
    ensure_jack_dirs("checks")
    ensure_jack_dirs("comments")

    names = list_jack_names()
    assert names == ["checks", "comments", "hooks"]
