"""Tests for command history functionality."""

from pathlib import Path
from unittest.mock import patch

from sase.command_history import (
    CommandEntry,
    _format_command_for_display,
    _load_command_history,
    _save_command_history,
    add_or_update_command,
    get_commands_for_display,
)


def test_same_command_different_project_not_deduplicated(tmp_path: Path) -> None:
    """Test that same command on different project is not deduplicated."""
    test_file = tmp_path / "command_history.json"
    with patch("sase.command_history._COMMAND_HISTORY_FILE", test_file):
        # Add initial command
        initial_entry = CommandEntry(
            command="make test",
            project="project1",
            cl_name=None,
            timestamp="251231_100000",
            last_used="251231_100000",
        )
        _save_command_history([initial_entry])

        # Add same command for different project
        with patch(
            "sase.command_history.generate_timestamp", return_value="251231_200000"
        ):
            add_or_update_command("make test", "project2", None)

        result = _load_command_history()
        # Should have 2 entries (different projects)
        assert len(result) == 2


def test_format_command_truncates_long_commands() -> None:
    """Test that long commands are truncated with ellipsis."""
    entry = CommandEntry(
        command="a" * 100,
        project="myproject",
        cl_name=None,
        timestamp="251231_143052",
        last_used="251231_143052",
    )
    result = _format_command_for_display(entry, None, "myproject", 10)
    assert "..." in result
    # Should not contain the full command
    assert "a" * 100 not in result


def test_get_commands_for_display_empty(tmp_path: Path) -> None:
    """Test get_commands_for_display returns empty list when no history."""
    test_file = tmp_path / "command_history.json"
    with patch("sase.command_history._COMMAND_HISTORY_FILE", test_file):
        result = get_commands_for_display("feature", "myproject")
        assert result == []


def test_get_commands_for_display_sorts_project_second(tmp_path: Path) -> None:
    """Test that commands from same project but different CL are sorted second."""
    test_file = tmp_path / "command_history.json"
    with patch("sase.command_history._COMMAND_HISTORY_FILE", test_file):
        entries = [
            CommandEntry(
                command="other project command",
                project="otherproject",
                cl_name=None,
                timestamp="251231_143052",
                last_used="251231_300000",  # Most recent
            ),
            CommandEntry(
                command="same project command",
                project="myproject",
                cl_name="other-feature",
                timestamp="251231_143052",
                last_used="251231_200000",  # Middle
            ),
            CommandEntry(
                command="current cl command",
                project="myproject",
                cl_name="feature",
                timestamp="251231_143052",
                last_used="251231_100000",  # Least recent
            ),
        ]
        _save_command_history(entries)

        result = get_commands_for_display("feature", "myproject")
        assert len(result) == 3
        # Current CL first, then same project, then other
        assert result[0][1].command == "current cl command"
        assert result[1][1].command == "same project command"
        assert result[2][1].command == "other project command"


def test_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON files are handled gracefully."""
    test_file = tmp_path / "command_history.json"
    test_file.write_text("not valid json {")
    with patch("sase.command_history._COMMAND_HISTORY_FILE", test_file):
        result = _load_command_history()
        assert result == []


def test_handles_missing_fields_in_json(tmp_path: Path) -> None:
    """Test that JSON entries with missing fields are filtered out."""
    test_file = tmp_path / "command_history.json"
    test_file.write_text(
        '{"commands": [{"command": "valid", "project": "proj", '
        '"timestamp": "251231_143052", "last_used": "251231_143052"}, '
        '{"command": "missing_fields"}]}'
    )
    with patch("sase.command_history._COMMAND_HISTORY_FILE", test_file):
        result = _load_command_history()
        assert len(result) == 1
        assert result[0].command == "valid"
