"""Tests for the bgcmd module."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.bgcmd import (
    BGCMD_STATE_DIR,
    MAX_SLOTS,
    BackgroundCommandInfo,
    _is_process_running,
    _is_slot_pending,
    _read_pid,
    _remove_pid,
    _write_info,
    _write_pid,
    clear_slot_output,
    clear_slot_pending,
    find_first_available_slot,
    get_slot_info,
    is_slot_running,
    mark_slot_pending,
    read_slot_output_tail,
)


def test_max_slots() -> None:
    """Test that MAX_SLOTS is 9."""
    assert MAX_SLOTS == 9


def test_is_process_running_current_process() -> None:
    """Test _is_process_running returns True for current process."""
    import os

    assert _is_process_running(os.getpid()) is True


def test_find_first_available_slot_all_available() -> None:
    """Test find_first_available_slot returns 1 when all slots available."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            slot = find_first_available_slot()
            assert slot == 1


def test_background_command_info_dataclass() -> None:
    """Test BackgroundCommandInfo dataclass."""
    info = BackgroundCommandInfo(
        command="make test",
        project="myproject",
        workspace_num=1,
        workspace_dir="/path/to/workspace",
        started_at="2025-01-01T12:00:00",
    )
    assert info.command == "make test"
    assert info.project == "myproject"
    assert info.workspace_num == 1
    assert info.workspace_dir == "/path/to/workspace"
    assert info.started_at == "2025-01-01T12:00:00"


def test_read_pid_invalid_content() -> None:
    """Test reading PID when file contains invalid content."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            slot_dir = Path(tmp_dir) / "1"
            slot_dir.mkdir(parents=True)
            (slot_dir / "pid").write_text("not_a_number")
            pid = _read_pid(1)
            assert pid is None


def test_get_slot_info_invalid_json() -> None:
    """Test get_slot_info when info.json contains invalid JSON."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            slot_dir = Path(tmp_dir) / "1"
            slot_dir.mkdir(parents=True)
            (slot_dir / "info.json").write_text("not valid json")
            info = get_slot_info(1)
            assert info is None


def test_get_slot_info_missing_fields() -> None:
    """Test get_slot_info when info.json has missing fields."""
    import json

    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            slot_dir = Path(tmp_dir) / "1"
            slot_dir.mkdir(parents=True)
            info_data = {"command": "make test"}  # Missing other fields
            (slot_dir / "info.json").write_text(json.dumps(info_data))
            info = get_slot_info(1)
            assert info is None  # Should fail due to TypeError


def test_remove_pid() -> None:
    """Test _remove_pid removes the pid file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            _write_pid(1, 12345)
            pid_file = Path(tmp_dir) / "1" / "pid"
            assert pid_file.exists()
            _remove_pid(1)
            assert not pid_file.exists()


def test_remove_pid_not_exists() -> None:
    """Test _remove_pid doesn't fail if pid file doesn't exist."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            # This should not raise
            _remove_pid(1)


def test_read_slot_output_tail_empty() -> None:
    """Test read_slot_output_tail returns empty string when no output."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            output = read_slot_output_tail(1)
            assert output == ""


def test_read_slot_output_tail_with_content() -> None:
    """Test read_slot_output_tail returns content."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            slot_dir = Path(tmp_dir) / "1"
            slot_dir.mkdir(parents=True)
            (slot_dir / "output.log").write_text("line 1\nline 2\nline 3\n")
            output = read_slot_output_tail(1, lines=2)
            assert "line 2" in output
            assert "line 3" in output


def test_clear_slot_output() -> None:
    """Test clear_slot_output clears the output file."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            slot_dir = Path(tmp_dir) / "1"
            slot_dir.mkdir(parents=True)
            output_file = slot_dir / "output.log"
            output_file.write_text("some output")
            assert output_file.read_text() == "some output"
            clear_slot_output(1)
            assert output_file.read_text() == ""


def test_clear_slot_output_not_exists() -> None:
    """Test clear_slot_output doesn't fail if file doesn't exist."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            # This should not raise
            clear_slot_output(1)


def test_bgcmd_state_dir_is_path() -> None:
    """Test that BGCMD_STATE_DIR is a Path."""
    assert isinstance(BGCMD_STATE_DIR, Path)
    assert "bgcmd" in str(BGCMD_STATE_DIR)


def test_is_slot_running_dead_process() -> None:
    """Test is_slot_running returns False for dead process."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            # Write a PID for a non-existent process
            _write_pid(1, 99999999)
            assert is_slot_running(1) is False


def test_find_first_available_slot_all_used() -> None:
    """Test find_first_available_slot returns None when all slots used."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            # Mark all 9 slots as active by writing info.json
            for i in range(1, 10):
                info = BackgroundCommandInfo(
                    command=f"make test {i}",
                    project="myproject",
                    workspace_num=1,
                    workspace_dir="/path",
                    started_at="2025-01-01T12:00:00",
                )
                _write_info(i, info)

            slot = find_first_available_slot()
            assert slot is None


def test_bgcmd_state_dir_path() -> None:
    """Test BGCMD_STATE_DIR is a proper Path under .sase/axe."""
    assert BGCMD_STATE_DIR.name == "bgcmd"
    assert "axe" in str(BGCMD_STATE_DIR)
    assert ".sase" in str(BGCMD_STATE_DIR)


def test_mark_and_clear_slot_pending_roundtrip() -> None:
    """mark/is/clear pending behave as a simple disk flag."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            assert _is_slot_pending(3) is False
            mark_slot_pending(3)
            assert _is_slot_pending(3) is True
            assert (Path(tmp_dir) / "3" / "pending").exists()
            clear_slot_pending(3)
            assert _is_slot_pending(3) is False


def test_clear_slot_pending_missing_is_noop() -> None:
    """clear_slot_pending is safe to call when no marker exists."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            clear_slot_pending(7)  # does not raise


def test_find_first_available_slot_skips_pending() -> None:
    """A pending marker makes a slot unavailable even with no info.json."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch("sase.ace.tui.bgcmd.BGCMD_STATE_DIR", Path(tmp_dir)):
            mark_slot_pending(1)
            assert find_first_available_slot() == 2
            mark_slot_pending(2)
            assert find_first_available_slot() == 3
            clear_slot_pending(1)
            assert find_first_available_slot() == 1
