"""Tests for per-lumberjack state management in the axe state module."""

import os
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.state import (
    LumberjackMetrics,
    LumberjackStatus,
    ensure_lumberjack_dirs,
    ensure_shared_dir,
    list_lumberjack_names,
    lumberjack_log_path,
    read_lumberjack_log_tail,
    read_lumberjack_metrics,
    read_lumberjack_pid,
    read_lumberjack_status,
    remove_lumberjack_pid,
    write_lumberjack_metrics,
    write_lumberjack_pid,
    write_lumberjack_status,
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


def test_ensure_lumberjack_dirs_creates_tree(temp_state_dir: Path) -> None:
    """Test that ensure_lumberjack_dirs creates the full directory tree."""
    lj_dir = ensure_lumberjack_dirs("hooks")
    assert lj_dir.exists()
    assert (lj_dir / "logs").exists()
    assert lj_dir.name == "hooks"


def test_ensure_lumberjack_dirs_idempotent(temp_state_dir: Path) -> None:
    """Test that calling ensure_lumberjack_dirs twice is safe."""
    lj_dir1 = ensure_lumberjack_dirs("hooks")
    lj_dir2 = ensure_lumberjack_dirs("hooks")
    assert lj_dir1 == lj_dir2
    assert lj_dir1.exists()


def test_ensure_shared_dir_creates_dir(temp_state_dir: Path) -> None:
    """Test that ensure_shared_dir creates the shared directory."""
    shared = ensure_shared_dir()
    assert shared.exists()


# --- PID File ---


def test_write_and_read_lumberjack_pid(temp_state_dir: Path) -> None:
    """Test writing and reading a lumberjack PID file."""
    write_lumberjack_pid("hooks")
    pid = read_lumberjack_pid("hooks")
    assert pid == os.getpid()


def test_read_lumberjack_pid_returns_none_when_missing(
    temp_state_dir: Path,
) -> None:
    """Test that read_lumberjack_pid returns None when no PID file."""
    assert read_lumberjack_pid("hooks") is None


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


def test_write_and_read_lumberjack_status(temp_state_dir: Path) -> None:
    """Test writing and reading lumberjack status."""
    status = LumberjackStatus(
        name="hooks",
        pid=12345,
        started_at="2026-02-21T10:00:00-05:00",
        status="running",
        interval=1,
        chops=["hook_checks", "mentor_checks"],
        last_cycle="2026-02-21T10:00:05-05:00",
        cycles_run=100,
        errors_encountered=2,
        uptime_seconds=300,
    )
    write_lumberjack_status(status)

    result = read_lumberjack_status("hooks")
    assert result is not None
    assert result.name == "hooks"
    assert result.pid == 12345
    assert result.status == "running"
    assert result.interval == 1
    assert result.chops == ["hook_checks", "mentor_checks"]
    assert result.cycles_run == 100
    assert result.uptime_seconds == 300


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


def test_write_and_read_lumberjack_metrics(temp_state_dir: Path) -> None:
    """Test writing and reading lumberjack metrics."""
    metrics = LumberjackMetrics(
        cycles_run=50,
        chops_executed=200,
        total_updates=30,
        errors_encountered=1,
    )
    write_lumberjack_metrics("hooks", metrics)

    result = read_lumberjack_metrics("hooks")
    assert result is not None
    assert result.cycles_run == 50
    assert result.chops_executed == 200
    assert result.total_updates == 30
    assert result.errors_encountered == 1


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


def test_lumberjack_log_path(temp_state_dir: Path) -> None:
    """Test lumberjack_log_path returns correct path."""
    path = lumberjack_log_path("hooks")
    assert path.name == "output.log"
    assert "hooks" in str(path)
    assert "logs" in str(path)


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
