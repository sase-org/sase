"""Tests for dismissed agents persistence."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    MAX_DISMISSED,
    load_dismissed_agents,
    load_dismissed_bundles,
    remove_bundle_by_identity,
    save_dismissed_agents,
    save_dismissed_bundles,
)
from sase.ace.tui.models.agent import Agent, AgentType


def test_load_empty_when_no_file(tmp_path: Path) -> None:
    """Test loading returns empty set when no file exists."""
    with patch(
        "sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE",
        tmp_path / "nonexistent.json",
    ):
        result = load_dismissed_agents()
        assert result == set()


def test_null_raw_suffix(tmp_path: Path) -> None:
    """Test that None raw_suffix is preserved through round-trip."""
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        dismissed = {(AgentType.RUNNING, "my_cl", None)}
        assert save_dismissed_agents(dismissed)
        result = load_dismissed_agents()
        assert result == dismissed


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
    """Test that saving >MAX_DISMISSED trims oldest entries first."""
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        # Use sequential 14-digit timestamps (zero-padded counters)
        total = MAX_DISMISSED + 50
        dismissed: set[tuple[AgentType, str, str | None]] = {
            (AgentType.WORKFLOW, "cl", f"{i:014d}") for i in range(total)
        }
        save_dismissed_agents(dismissed)
        result = load_dismissed_agents()
        assert len(result) == MAX_DISMISSED

        # The oldest 50 entries (0..49) should be dropped,
        # newest 500 (50..549) should be kept
        suffixes = {s for _, _, s in result}
        assert f"{0:014d}" not in suffixes  # oldest dropped
        assert f"{49:014d}" not in suffixes  # still old, dropped
        assert f"{50:014d}" in suffixes  # first kept
        assert f"{total - 1:014d}" in suffixes  # newest kept


# --- Bundle Persistence Tests ---


def _make_agent(
    *,
    agent_type: AgentType = AgentType.RUNNING,
    cl_name: str = "test_cl",
    raw_suffix: str | None = "20250615103000",
    status: str = "DONE",
    workflow: str | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
    step_index: int | None = None,
) -> Agent:
    """Helper to create a test Agent."""
    return Agent(
        agent_type=agent_type,
        cl_name=cl_name,
        project_file="/tmp/test.gp",
        status=status,
        start_time=datetime(2025, 6, 15, 10, 30, 0),
        raw_suffix=raw_suffix,
        workflow=workflow,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        step_index=step_index,
    )


def test_bundle_save_load_round_trip(tmp_path: Path) -> None:
    """Test save/load round-trip for dismissed bundles."""
    bundles_file = tmp_path / "bundles.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_FILE", bundles_file):
        agent = _make_agent()
        assert save_dismissed_bundles([agent])

        loaded = load_dismissed_bundles()
        assert len(loaded) == 1
        assert loaded[0].identity == agent.identity
        assert loaded[0].cl_name == "test_cl"
        assert loaded[0].start_time == datetime(2025, 6, 15, 10, 30, 0)


def test_bundle_load_empty_when_no_file(tmp_path: Path) -> None:
    """Test loading returns empty list when no file exists."""
    with patch(
        "sase.ace.dismissed_agents._DISMISSED_BUNDLES_FILE",
        tmp_path / "nonexistent.json",
    ):
        result = load_dismissed_bundles()
        assert result == []


def test_bundle_load_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON files are handled gracefully."""
    bundles_file = tmp_path / "bundles.json"
    bundles_file.write_text("not valid json {")
    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_FILE", bundles_file):
        result = load_dismissed_bundles()
        assert result == []


def test_bundle_load_handles_non_list_json(tmp_path: Path) -> None:
    """Test that non-list JSON is handled gracefully."""
    bundles_file = tmp_path / "bundles.json"
    bundles_file.write_text('{"key": "value"}')
    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_FILE", bundles_file):
        result = load_dismissed_bundles()
        assert result == []


def test_bundle_load_skips_malformed_entries(tmp_path: Path) -> None:
    """Test that malformed bundle entries are skipped."""
    bundles_file = tmp_path / "bundles.json"
    # Mix of valid and invalid entries
    agent = _make_agent()
    import json

    valid_entry = agent.to_bundle_dict()
    bundles_file.write_text(json.dumps([valid_entry, "bad", 42, {}]))
    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_FILE", bundles_file):
        result = load_dismissed_bundles()
        assert len(result) == 1
        assert result[0].identity == agent.identity


def test_bundle_trimming(tmp_path: Path) -> None:
    """Test that saving >MAX_DISMISSED bundles trims oldest first."""
    bundles_file = tmp_path / "bundles.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_FILE", bundles_file):
        total = MAX_DISMISSED + 50
        agents = [_make_agent(raw_suffix=f"{i:014d}") for i in range(total)]
        save_dismissed_bundles(agents)
        loaded = load_dismissed_bundles()
        assert len(loaded) == MAX_DISMISSED

        suffixes = {a.raw_suffix for a in loaded}
        assert f"{0:014d}" not in suffixes  # oldest dropped
        assert f"{total - 1:014d}" in suffixes  # newest kept


def test_remove_bundle_by_identity(tmp_path: Path) -> None:
    """Test removing a bundle by identity."""
    bundles_file = tmp_path / "bundles.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_FILE", bundles_file):
        agent1 = _make_agent(cl_name="cl_1", raw_suffix="20250615100000")
        agent2 = _make_agent(cl_name="cl_2", raw_suffix="20250615110000")
        save_dismissed_bundles([agent1, agent2])

        result = remove_bundle_by_identity(agent1.identity)
        assert result is True

        loaded = load_dismissed_bundles()
        assert len(loaded) == 1
        assert loaded[0].identity == agent2.identity


def test_remove_bundle_removes_child_steps(tmp_path: Path) -> None:
    """Test that removing a parent bundle also removes its child step bundles."""
    bundles_file = tmp_path / "bundles.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_FILE", bundles_file):
        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="my_cl",
            raw_suffix="20250615103000",
            workflow="gh",
        )
        child1 = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="my_cl",
            raw_suffix="child1_suffix",
            parent_workflow="gh",
            parent_timestamp="20250615103000",
            step_index=0,
        )
        child2 = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="my_cl",
            raw_suffix="child2_suffix",
            parent_workflow="gh",
            parent_timestamp="20250615103000",
            step_index=1,
        )
        unrelated = _make_agent(cl_name="other", raw_suffix="20250615120000")

        save_dismissed_bundles([parent, child1, child2, unrelated])

        result = remove_bundle_by_identity(parent.identity)
        assert result is True

        loaded = load_dismissed_bundles()
        assert len(loaded) == 1
        assert loaded[0].identity == unrelated.identity


def test_remove_bundle_returns_false_when_not_found(tmp_path: Path) -> None:
    """Test that removing a nonexistent bundle returns False."""
    bundles_file = tmp_path / "bundles.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_FILE", bundles_file):
        agent = _make_agent()
        save_dismissed_bundles([agent])

        fake_identity = (AgentType.RUNNING, "nonexistent", "00000000000000")
        result = remove_bundle_by_identity(fake_identity)
        assert result is False
