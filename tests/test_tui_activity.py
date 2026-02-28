"""Tests for sase.ace.tui_activity module."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui_activity import (
    get_tui_inactive_seconds,
    get_tui_last_activity,
    is_tui_running,
    remove_tui_pid,
    write_activity_timestamp,
    write_tui_pid,
)


def _patch_activity_file(tmp_path: Path):
    """Return a mock.patch targeting ACTIVITY_FILE to use *tmp_path*."""
    return patch("sase.ace.tui_activity.ACTIVITY_FILE", tmp_path / "tui_last_activity")


def _patch_pid_file(tmp_path: Path):
    """Return a mock.patch targeting PID_FILE to use *tmp_path*."""
    return patch("sase.ace.tui_activity.PID_FILE", tmp_path / "tui_pid")


# ── write_activity_timestamp ──────────────────────────────────────────


def test_write_creates_file(tmp_path: Path) -> None:
    with _patch_activity_file(tmp_path) as mock_file:
        write_activity_timestamp(1700000000.123)
        assert mock_file.read_text() == "1700000000.123"


def test_write_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "tui_last_activity"
    with patch("sase.ace.tui_activity.ACTIVITY_FILE", target):
        write_activity_timestamp(42.0)
        assert target.exists()
        assert target.read_text() == "42.0"


def test_write_is_atomic_no_leftover_tmp(tmp_path: Path) -> None:
    with _patch_activity_file(tmp_path):
        write_activity_timestamp(99.9)
        tmp_file = tmp_path / "tui_last_activity.tmp"
        assert not tmp_file.exists()


def test_write_epoch_zero(tmp_path: Path) -> None:
    with _patch_activity_file(tmp_path) as mock_file:
        write_activity_timestamp(0)
        assert mock_file.read_text() == "0"


def test_write_overwrites_existing(tmp_path: Path) -> None:
    with _patch_activity_file(tmp_path) as mock_file:
        write_activity_timestamp(1.0)
        write_activity_timestamp(2.0)
        assert mock_file.read_text() == "2.0"


# ── get_tui_last_activity ───────────────────────────────────────────


def test_get_last_activity_reads_epoch(tmp_path: Path) -> None:
    with _patch_activity_file(tmp_path):
        write_activity_timestamp(1700000000.5)
        assert get_tui_last_activity() == 1700000000.5


def test_get_last_activity_returns_none_when_missing(tmp_path: Path) -> None:
    with _patch_activity_file(tmp_path):
        assert get_tui_last_activity() is None


def test_get_last_activity_returns_none_on_invalid(tmp_path: Path) -> None:
    target = tmp_path / "tui_last_activity"
    target.write_text("not-a-number")
    with patch("sase.ace.tui_activity.ACTIVITY_FILE", target):
        assert get_tui_last_activity() is None


# ── get_tui_inactive_seconds ─────────────────────────────────────────


def test_inactive_seconds_calculates_correctly(tmp_path: Path) -> None:
    with _patch_activity_file(tmp_path):
        write_activity_timestamp(1700000000.0)
        with patch("time.time", return_value=1700000030.0):
            result = get_tui_inactive_seconds()
            assert result is not None
            assert abs(result - 30.0) < 0.01


def test_inactive_seconds_returns_none_when_missing(tmp_path: Path) -> None:
    with _patch_activity_file(tmp_path):
        assert get_tui_inactive_seconds() is None


def test_inactive_seconds_returns_inf_for_epoch_zero(tmp_path: Path) -> None:
    with _patch_activity_file(tmp_path):
        write_activity_timestamp(0)
        assert get_tui_inactive_seconds() == float("inf")


# ── write_tui_pid / remove_tui_pid ──────────────────────────────────


def test_write_pid_creates_file(tmp_path: Path) -> None:
    with _patch_pid_file(tmp_path):
        write_tui_pid()
        pid_file = tmp_path / "tui_pid"
        assert pid_file.exists()
        assert int(pid_file.read_text().strip()) == os.getpid()


def test_remove_pid_deletes_file(tmp_path: Path) -> None:
    with _patch_pid_file(tmp_path):
        write_tui_pid()
        remove_tui_pid()
        assert not (tmp_path / "tui_pid").exists()


def test_remove_pid_no_error_when_missing(tmp_path: Path) -> None:
    with _patch_pid_file(tmp_path):
        remove_tui_pid()  # should not raise


# ── is_tui_running ──────────────────────────────────────────────────


def test_is_tui_running_true_for_current_process(tmp_path: Path) -> None:
    with _patch_pid_file(tmp_path):
        write_tui_pid()
        assert is_tui_running() is True


def test_is_tui_running_false_when_no_file(tmp_path: Path) -> None:
    with _patch_pid_file(tmp_path):
        assert is_tui_running() is False


def test_is_tui_running_false_for_dead_pid(tmp_path: Path) -> None:
    pid_file = tmp_path / "tui_pid"
    pid_file.write_text("999999")
    with _patch_pid_file(tmp_path), patch("os.kill", side_effect=ProcessLookupError):
        assert is_tui_running() is False
        # Stale PID file should be cleaned up
        assert not pid_file.exists()


def test_is_tui_running_false_for_invalid_content(tmp_path: Path) -> None:
    pid_file = tmp_path / "tui_pid"
    pid_file.write_text("not-a-number")
    with _patch_pid_file(tmp_path):
        assert is_tui_running() is False


def test_is_tui_running_true_on_permission_error(tmp_path: Path) -> None:
    pid_file = tmp_path / "tui_pid"
    pid_file.write_text("12345")
    with _patch_pid_file(tmp_path), patch("os.kill", side_effect=PermissionError):
        assert is_tui_running() is True
