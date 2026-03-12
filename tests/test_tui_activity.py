"""Tests for sase.ace.tui_activity module."""

from __future__ import annotations

import os
import time
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui_activity import (
    _IDLE_GUARD_SECONDS,
    _is_tui_running,
    get_tui_last_activity,
    is_idle,
    remove_idle_state,
    remove_last_keypress,
    remove_tui_pid,
    write_activity_timestamp,
    write_idle_state,
    write_last_keypress,
    write_tui_pid,
)


def _patch_activity_file(tmp_path: Path):
    """Return a mock.patch targeting ACTIVITY_FILE to use *tmp_path*."""
    return patch("sase.ace.tui_activity.ACTIVITY_FILE", tmp_path / "tui_last_activity")


def _patch_pid_file(tmp_path: Path):
    """Return a mock.patch targeting PID_FILE to use *tmp_path*."""
    return patch("sase.ace.tui_activity.PID_FILE", tmp_path / "tui_pid")


def _patch_idle_state_file(tmp_path: Path):
    """Return a mock.patch targeting IDLE_STATE_FILE to use *tmp_path*."""
    return patch("sase.ace.tui_activity.IDLE_STATE_FILE", tmp_path / "tui_idle_state")


def _patch_last_keypress_file(tmp_path: Path):
    """Return a mock.patch targeting LAST_KEYPRESS_FILE to use *tmp_path*."""
    return patch(
        "sase.ace.tui_activity.LAST_KEYPRESS_FILE", tmp_path / "tui_last_keypress"
    )


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


# ── write_idle_state / remove_idle_state ─────────────────────────────


def test_write_idle_state_true(tmp_path: Path) -> None:
    with _patch_idle_state_file(tmp_path) as mock_file:
        write_idle_state(True)
        assert mock_file.read_text() == "1"


def test_write_idle_state_false(tmp_path: Path) -> None:
    with _patch_idle_state_file(tmp_path) as mock_file:
        write_idle_state(False)
        assert mock_file.read_text() == "0"


def test_write_idle_state_overwrites(tmp_path: Path) -> None:
    with _patch_idle_state_file(tmp_path) as mock_file:
        write_idle_state(True)
        write_idle_state(False)
        assert mock_file.read_text() == "0"


def test_write_idle_state_creates_parent_dirs(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "dir" / "tui_idle_state"
    with patch("sase.ace.tui_activity.IDLE_STATE_FILE", target):
        write_idle_state(True)
        assert target.exists()
        assert target.read_text() == "1"


def test_remove_idle_state_deletes_file(tmp_path: Path) -> None:
    with _patch_idle_state_file(tmp_path):
        write_idle_state(True)
        remove_idle_state()
        assert not (tmp_path / "tui_idle_state").exists()


def test_remove_idle_state_no_error_when_missing(tmp_path: Path) -> None:
    with _patch_idle_state_file(tmp_path):
        remove_idle_state()  # should not raise


# ── is_tui_running ──────────────────────────────────────────────────


def test_is_tui_running_true_for_current_process(tmp_path: Path) -> None:
    with _patch_pid_file(tmp_path):
        write_tui_pid()
        assert _is_tui_running() is True


def test_is_tui_running_false_when_no_file(tmp_path: Path) -> None:
    with _patch_pid_file(tmp_path):
        assert _is_tui_running() is False


def test_is_tui_running_false_for_dead_pid(tmp_path: Path) -> None:
    pid_file = tmp_path / "tui_pid"
    pid_file.write_text("999999")
    with _patch_pid_file(tmp_path), patch("os.kill", side_effect=ProcessLookupError):
        assert _is_tui_running() is False
        # Stale PID file should be cleaned up
        assert not pid_file.exists()


def test_is_tui_running_false_for_invalid_content(tmp_path: Path) -> None:
    pid_file = tmp_path / "tui_pid"
    pid_file.write_text("not-a-number")
    with _patch_pid_file(tmp_path):
        assert _is_tui_running() is False


def test_is_tui_running_true_on_permission_error(tmp_path: Path) -> None:
    pid_file = tmp_path / "tui_pid"
    pid_file.write_text("12345")
    with _patch_pid_file(tmp_path), patch("os.kill", side_effect=PermissionError):
        assert _is_tui_running() is True


# ── is_idle ────────────────────────────────────────────────────────


def test_is_idle_true_when_tui_not_running_no_state_file(tmp_path: Path) -> None:
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=False),
    ):
        # No idle_state file → idle
        assert is_idle() is True


def test_is_idle_true_when_state_file_missing(tmp_path: Path) -> None:
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=True),
    ):
        assert is_idle() is True


def test_is_idle_true_when_state_says_idle(tmp_path: Path) -> None:
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=True),
    ):
        write_idle_state(True)
        assert is_idle() is True


def test_is_idle_false_when_state_says_active(tmp_path: Path) -> None:
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=True),
    ):
        write_idle_state(False)
        assert is_idle() is False


def test_is_idle_true_after_state_transitions_to_idle(tmp_path: Path) -> None:
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=True),
    ):
        write_idle_state(False)
        assert is_idle() is False
        write_idle_state(True)
        assert is_idle() is True


def test_is_idle_true_after_state_file_removed(tmp_path: Path) -> None:
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=True),
    ):
        write_idle_state(False)
        assert is_idle() is False
        remove_idle_state()
        assert is_idle() is True


# ── missing PID file with active state ───────────────────────────


def test_is_idle_false_when_pid_missing_but_state_active_and_recent_keypress(
    tmp_path: Path,
) -> None:
    """PID file missing but idle_state=0 + recent keypress → not idle."""
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=False),
    ):
        write_idle_state(False)
        write_last_keypress(time.time())
        assert is_idle() is False


def test_is_idle_true_when_pid_missing_state_active_but_old_keypress(
    tmp_path: Path,
) -> None:
    """PID file missing + idle_state=0 but old keypress → idle (stale crash state)."""
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=False),
    ):
        write_idle_state(False)
        write_last_keypress(time.time() - _IDLE_GUARD_SECONDS - 10)
        assert is_idle() is True


def test_is_idle_true_when_pid_missing_state_active_no_keypress(
    tmp_path: Path,
) -> None:
    """PID file missing + idle_state=0 but no keypress file → idle."""
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=False),
    ):
        write_idle_state(False)
        assert is_idle() is True


# ── keypress guard ────────────────────────────────────────────────


def test_is_idle_false_when_keypress_recent(tmp_path: Path) -> None:
    """Even if idle_state says '1', a recent keypress overrides to not-idle."""
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=True),
    ):
        write_idle_state(True)
        # Keypress just happened
        write_last_keypress(time.time())
        assert is_idle() is False


def test_is_idle_true_when_keypress_old_enough(tmp_path: Path) -> None:
    """Idle state is respected when the keypress is old enough."""
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=True),
    ):
        write_idle_state(True)
        # Keypress was a long time ago (> _IDLE_GUARD_SECONDS)
        write_last_keypress(time.time() - _IDLE_GUARD_SECONDS - 10)
        assert is_idle() is True


def test_is_idle_true_when_no_keypress_file(tmp_path: Path) -> None:
    """Missing keypress file does not block idle detection."""
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=True),
    ):
        write_idle_state(True)
        # No keypress file — guard does not apply
        assert is_idle() is True


def test_is_idle_true_when_keypress_is_zero(tmp_path: Path) -> None:
    """Manual idle (epoch=0) is not blocked by the guard."""
    with (
        _patch_idle_state_file(tmp_path),
        _patch_last_keypress_file(tmp_path),
        patch("sase.ace.tui_activity._is_tui_running", return_value=True),
    ):
        write_idle_state(True)
        write_last_keypress(0)
        assert is_idle() is True


def test_write_last_keypress_creates_file(tmp_path: Path) -> None:
    with _patch_last_keypress_file(tmp_path):
        write_last_keypress(1700000000.5)
        f = tmp_path / "tui_last_keypress"
        assert f.exists()
        assert float(f.read_text().strip()) == 1700000000.5


def test_remove_last_keypress_deletes_file(tmp_path: Path) -> None:
    with _patch_last_keypress_file(tmp_path):
        write_last_keypress(1.0)
        remove_last_keypress()
        assert not (tmp_path / "tui_last_keypress").exists()


def test_remove_last_keypress_no_error_when_missing(tmp_path: Path) -> None:
    with _patch_last_keypress_file(tmp_path):
        remove_last_keypress()  # should not raise
