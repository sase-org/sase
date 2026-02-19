"""Tests for dismissed agents persistence."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    MAX_DISMISSED,
    load_dismissed_agents,
    save_dismissed_agents,
)
from sase.ace.tui.models.agent import AgentType


def test_load_empty_when_no_file(tmp_path: Path) -> None:
    """Test loading returns empty set when no file exists."""
    with patch(
        "sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE",
        tmp_path / "nonexistent.json",
    ):
        result = load_dismissed_agents()
        assert result == set()


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """Test saving and loading dismissed agents."""
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        dismissed = {
            (AgentType.WORKFLOW, "cl_1", "20250101_120000"),
            (AgentType.FIX_HOOK, "cl_2", "suffix_abc"),
        }
        assert save_dismissed_agents(dismissed)
        result = load_dismissed_agents()
        assert result == dismissed


def test_null_raw_suffix(tmp_path: Path) -> None:
    """Test that None raw_suffix is preserved through round-trip."""
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        dismissed = {(AgentType.RUNNING, "my_cl", None)}
        assert save_dismissed_agents(dismissed)
        result = load_dismissed_agents()
        assert result == dismissed


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    """Test that save creates parent directory if needed."""
    test_file = tmp_path / "subdir" / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        dismissed = {(AgentType.WORKFLOW, "cl", "ts")}
        assert save_dismissed_agents(dismissed)
        assert test_file.exists()


def test_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON files are handled gracefully."""
    test_file = tmp_path / "dismissed_agents.json"
    test_file.write_text("not valid json {")
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        result = load_dismissed_agents()
        assert result == set()


def test_handles_non_list_json(tmp_path: Path) -> None:
    """Test that non-list JSON is handled gracefully."""
    test_file = tmp_path / "dismissed_agents.json"
    test_file.write_text('{"key": "value"}')
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        result = load_dismissed_agents()
        assert result == set()


def test_handles_unknown_agent_type(tmp_path: Path) -> None:
    """Test that unknown AgentType values are skipped."""
    test_file = tmp_path / "dismissed_agents.json"
    test_file.write_text(
        '[["unknown_type", "cl_1", "ts"], ["workflow", "cl_2", "ts2"]]'
    )
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        result = load_dismissed_agents()
        assert result == {(AgentType.WORKFLOW, "cl_2", "ts2")}


def test_handles_malformed_entries(tmp_path: Path) -> None:
    """Test that malformed entries are skipped."""
    test_file = tmp_path / "dismissed_agents.json"
    # Mix of valid and invalid entries
    test_file.write_text(
        '[["workflow", "cl", "ts"], [1, 2], "bad", ["workflow", "cl2"]]'
    )
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        result = load_dismissed_agents()
        assert result == {(AgentType.WORKFLOW, "cl", "ts")}


def test_max_dismissed_trimming(tmp_path: Path) -> None:
    """Test that saving >MAX_DISMISSED trims to MAX_DISMISSED."""
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        dismissed = {
            (AgentType.WORKFLOW, f"cl_{i}", f"ts_{i}")
            for i in range(MAX_DISMISSED + 50)
        }
        save_dismissed_agents(dismissed)
        result = load_dismissed_agents()
        assert len(result) == MAX_DISMISSED
