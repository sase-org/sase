"""Tests for Agents-tab grouping-mode persistence."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.grouping_mode_state import load_grouping_mode, save_grouping_mode
from sase.ace.tui.models.agent_groups import GroupingMode


def test_load_returns_standard_when_file_absent(tmp_path: Path) -> None:
    with patch(
        "sase.ace.grouping_mode_state._GROUPING_MODE_FILE",
        tmp_path / "grouping_mode.txt",
    ):
        assert load_grouping_mode() is GroupingMode.STANDARD


def test_round_trip_by_status(tmp_path: Path) -> None:
    test_file = tmp_path / "grouping_mode.txt"
    with patch("sase.ace.grouping_mode_state._GROUPING_MODE_FILE", test_file):
        assert save_grouping_mode(GroupingMode.BY_STATUS)
        assert load_grouping_mode() is GroupingMode.BY_STATUS


def test_round_trip_by_date(tmp_path: Path) -> None:
    test_file = tmp_path / "grouping_mode.txt"
    with patch("sase.ace.grouping_mode_state._GROUPING_MODE_FILE", test_file):
        assert save_grouping_mode(GroupingMode.BY_DATE)
        assert load_grouping_mode() is GroupingMode.BY_DATE


def test_load_returns_standard_on_corrupt_value(tmp_path: Path) -> None:
    test_file = tmp_path / "grouping_mode.txt"
    test_file.write_text("garbage")
    with patch("sase.ace.grouping_mode_state._GROUPING_MODE_FILE", test_file):
        assert load_grouping_mode() is GroupingMode.STANDARD


def test_load_returns_standard_on_empty_file(tmp_path: Path) -> None:
    test_file = tmp_path / "grouping_mode.txt"
    test_file.write_text("")
    with patch("sase.ace.grouping_mode_state._GROUPING_MODE_FILE", test_file):
        assert load_grouping_mode() is GroupingMode.STANDARD


def test_save_returns_false_on_oserror(tmp_path: Path) -> None:
    test_file = tmp_path / "grouping_mode.txt"
    with patch("sase.ace.grouping_mode_state._GROUPING_MODE_FILE", test_file):
        with patch("pathlib.Path.write_text", side_effect=OSError("read-only")):
            assert save_grouping_mode(GroupingMode.BY_STATUS) is False


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    test_file = tmp_path / "nested" / "dir" / "grouping_mode.txt"
    with patch("sase.ace.grouping_mode_state._GROUPING_MODE_FILE", test_file):
        assert save_grouping_mode(GroupingMode.BY_DATE)
        assert test_file.exists()
        assert test_file.read_text() == "by_date"
