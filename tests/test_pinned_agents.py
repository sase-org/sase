"""Tests for pinned agents persistence."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.pinned_agents import (
    load_pinned_agents,
    save_pinned_agents,
    toggle_pinned_agent,
)
from sase.ace.tui.models.agent import AgentType


def test_load_empty_when_no_file(tmp_path: Path) -> None:
    """Test loading returns empty set when no file exists."""
    with patch(
        "sase.ace.pinned_agents._PINNED_AGENTS_FILE",
        tmp_path / "nonexistent.json",
    ):
        result = load_pinned_agents()
        assert result == set()


def test_round_trip(tmp_path: Path) -> None:
    """Test save/load round-trip."""
    test_file = tmp_path / "pinned_agents.json"
    with patch("sase.ace.pinned_agents._PINNED_AGENTS_FILE", test_file):
        pinned = {
            (AgentType.RUNNING, "my_cl", "20250615103000"),
            (AgentType.WORKFLOW, "other_cl", "20250615110000"),
        }
        assert save_pinned_agents(pinned)
        result = load_pinned_agents()
        assert result == pinned


def test_null_raw_suffix(tmp_path: Path) -> None:
    """Test that None raw_suffix is preserved through round-trip."""
    test_file = tmp_path / "pinned_agents.json"
    with patch("sase.ace.pinned_agents._PINNED_AGENTS_FILE", test_file):
        pinned = {(AgentType.RUNNING, "my_cl", None)}
        assert save_pinned_agents(pinned)
        result = load_pinned_agents()
        assert result == pinned


def test_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON files are handled gracefully."""
    test_file = tmp_path / "pinned_agents.json"
    test_file.write_text("not valid json {")
    with patch("sase.ace.pinned_agents._PINNED_AGENTS_FILE", test_file):
        result = load_pinned_agents()
        assert result == set()


def test_handles_non_list_json(tmp_path: Path) -> None:
    """Test that non-list JSON is handled gracefully."""
    test_file = tmp_path / "pinned_agents.json"
    test_file.write_text('{"key": "value"}')
    with patch("sase.ace.pinned_agents._PINNED_AGENTS_FILE", test_file):
        result = load_pinned_agents()
        assert result == set()


def test_handles_unknown_agent_type(tmp_path: Path) -> None:
    """Test that unknown AgentType values are skipped."""
    test_file = tmp_path / "pinned_agents.json"
    test_file.write_text(
        '[["unknown_type", "cl_1", "ts"], ["workflow", "cl_2", "ts2"]]'
    )
    with patch("sase.ace.pinned_agents._PINNED_AGENTS_FILE", test_file):
        result = load_pinned_agents()
        assert result == {(AgentType.WORKFLOW, "cl_2", "ts2")}


def test_handles_malformed_entries(tmp_path: Path) -> None:
    """Test that malformed entries are skipped."""
    test_file = tmp_path / "pinned_agents.json"
    test_file.write_text(
        '[["workflow", "cl", "ts"], [1, 2], "bad", ["workflow", "cl2"]]'
    )
    with patch("sase.ace.pinned_agents._PINNED_AGENTS_FILE", test_file):
        result = load_pinned_agents()
        assert result == {(AgentType.WORKFLOW, "cl", "ts")}


def test_toggle_pin(tmp_path: Path) -> None:
    """Test toggle_pinned_agent adds and removes."""
    pinned: set[tuple[AgentType, str, str | None]] = set()
    identity = (AgentType.RUNNING, "my_cl", "20250615103000")

    # Pin
    result = toggle_pinned_agent(pinned, identity)
    assert result is True
    assert identity in pinned

    # Unpin
    result = toggle_pinned_agent(pinned, identity)
    assert result is False
    assert identity not in pinned


def test_toggle_preserves_other_pins(tmp_path: Path) -> None:
    """Test that toggling one agent doesn't affect others."""
    identity_a = (AgentType.RUNNING, "cl_a", "ts_a")
    identity_b = (AgentType.WORKFLOW, "cl_b", "ts_b")
    pinned: set[tuple[AgentType, str, str | None]] = {identity_a, identity_b}

    # Unpin A
    toggle_pinned_agent(pinned, identity_a)
    assert identity_a not in pinned
    assert identity_b in pinned
