"""Tests for CLs-tab grouping-mode persistence."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.changespec_grouping_mode_state import (
    load_changespec_grouping_mode,
    save_changespec_grouping_mode,
)
from sase.ace.tui.models.changespec_groups import ChangeSpecGroupingMode


def test_load_returns_by_project_when_file_absent(tmp_path: Path) -> None:
    with patch(
        "sase.ace.changespec_grouping_mode_state._GROUPING_MODE_FILE",
        tmp_path / "changespec_grouping_mode.txt",
    ):
        assert load_changespec_grouping_mode() is ChangeSpecGroupingMode.BY_PROJECT


def test_round_trip_by_status(tmp_path: Path) -> None:
    test_file = tmp_path / "cs.txt"
    with patch(
        "sase.ace.changespec_grouping_mode_state._GROUPING_MODE_FILE", test_file
    ):
        assert save_changespec_grouping_mode(ChangeSpecGroupingMode.BY_STATUS)
        assert load_changespec_grouping_mode() is ChangeSpecGroupingMode.BY_STATUS


def test_round_trip_by_project(tmp_path: Path) -> None:
    test_file = tmp_path / "cs.txt"
    with patch(
        "sase.ace.changespec_grouping_mode_state._GROUPING_MODE_FILE", test_file
    ):
        assert save_changespec_grouping_mode(ChangeSpecGroupingMode.BY_PROJECT)
        assert load_changespec_grouping_mode() is ChangeSpecGroupingMode.BY_PROJECT


def test_round_trip_by_date(tmp_path: Path) -> None:
    test_file = tmp_path / "cs.txt"
    with patch(
        "sase.ace.changespec_grouping_mode_state._GROUPING_MODE_FILE", test_file
    ):
        assert save_changespec_grouping_mode(ChangeSpecGroupingMode.BY_DATE)
        assert load_changespec_grouping_mode() is ChangeSpecGroupingMode.BY_DATE


def test_load_returns_by_project_on_corrupt_value(tmp_path: Path) -> None:
    test_file = tmp_path / "cs.txt"
    test_file.write_text("garbage")
    with patch(
        "sase.ace.changespec_grouping_mode_state._GROUPING_MODE_FILE", test_file
    ):
        assert load_changespec_grouping_mode() is ChangeSpecGroupingMode.BY_PROJECT


def test_load_returns_by_project_on_empty_file(tmp_path: Path) -> None:
    test_file = tmp_path / "cs.txt"
    test_file.write_text("")
    with patch(
        "sase.ace.changespec_grouping_mode_state._GROUPING_MODE_FILE", test_file
    ):
        assert load_changespec_grouping_mode() is ChangeSpecGroupingMode.BY_PROJECT


def test_load_returns_by_project_on_legacy_flat_value(tmp_path: Path) -> None:
    """Files containing the literal ``flat`` (legacy persisted state) fall
    through the ValueError path to the new BY_PROJECT default."""
    test_file = tmp_path / "cs.txt"
    test_file.write_text("flat")
    with patch(
        "sase.ace.changespec_grouping_mode_state._GROUPING_MODE_FILE", test_file
    ):
        assert load_changespec_grouping_mode() is ChangeSpecGroupingMode.BY_PROJECT


def test_save_returns_false_on_oserror(tmp_path: Path) -> None:
    test_file = tmp_path / "cs.txt"
    with patch(
        "sase.ace.changespec_grouping_mode_state._GROUPING_MODE_FILE", test_file
    ):
        with patch("pathlib.Path.write_text", side_effect=OSError("read-only")):
            assert (
                save_changespec_grouping_mode(ChangeSpecGroupingMode.BY_DATE) is False
            )


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    test_file = tmp_path / "nested" / "dir" / "cs.txt"
    with patch(
        "sase.ace.changespec_grouping_mode_state._GROUPING_MODE_FILE", test_file
    ):
        assert save_changespec_grouping_mode(ChangeSpecGroupingMode.BY_DATE)
        assert test_file.exists()
        assert test_file.read_text() == "by_date"


def test_cs_state_is_independent_of_agents_state(tmp_path: Path) -> None:
    """Saving one tab's mode must not write to the other tab's file."""
    cs_file = tmp_path / "cs.txt"
    agents_file = tmp_path / "agents.txt"
    with patch("sase.ace.changespec_grouping_mode_state._GROUPING_MODE_FILE", cs_file):
        save_changespec_grouping_mode(ChangeSpecGroupingMode.BY_DATE)
    assert cs_file.exists()
    assert not agents_file.exists()
