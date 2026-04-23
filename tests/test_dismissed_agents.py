"""Tests for dismissed agents persistence."""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    load_dismissed_agents,
    load_dismissed_bundles,
    remove_bundle_by_identity,
    save_dismissed_agents,
    save_dismissed_bundle,
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


def test_no_trimming_limit(tmp_path: Path) -> None:
    """Test that all entries are preserved (no MAX_DISMISSED limit)."""
    test_file = tmp_path / "dismissed_agents.json"
    with patch("sase.ace.dismissed_agents._DISMISSED_AGENTS_FILE", test_file):
        total = 1000
        dismissed: set[tuple[AgentType, str, str | None]] = {
            (AgentType.WORKFLOW, "cl", f"{i:014d}") for i in range(total)
        }
        save_dismissed_agents(dismissed)
        result = load_dismissed_agents()
        assert len(result) == total


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
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = _make_agent()
        assert save_dismissed_bundle(agent)

        loaded = load_dismissed_bundles()
        assert len(loaded) == 1
        assert loaded[0].identity == agent.identity
        assert loaded[0].cl_name == "test_cl"
        assert loaded[0].start_time == datetime(2025, 6, 15, 10, 30, 0)


def test_bundle_load_empty_when_no_dir(tmp_path: Path) -> None:
    """Test loading returns empty list when directory doesn't exist."""
    with (
        patch(
            "sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR",
            tmp_path / "nonexistent",
        ),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        result = load_dismissed_bundles()
        assert result == []


def test_bundle_load_handles_corrupt_json(tmp_path: Path) -> None:
    """Test that corrupt JSON bundle files are skipped."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    (bundles_dir / "20250615103000.json").write_text("not valid json {")
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        result = load_dismissed_bundles()
        assert result == []


def test_bundle_load_handles_non_dict_json(tmp_path: Path) -> None:
    """Test that non-dict JSON bundle files are skipped."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    (bundles_dir / "20250615103000.json").write_text("[1, 2, 3]")
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        result = load_dismissed_bundles()
        assert result == []


def test_bundle_load_by_suffixes(tmp_path: Path) -> None:
    """Test loading specific bundles by suffix."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent1 = _make_agent(cl_name="cl_1", raw_suffix="20250615100000")
        agent2 = _make_agent(cl_name="cl_2", raw_suffix="20250615110000")
        agent3 = _make_agent(cl_name="cl_3", raw_suffix="20250615120000")
        save_dismissed_bundle(agent1)
        save_dismissed_bundle(agent2)
        save_dismissed_bundle(agent3)

        # Load only two specific bundles
        loaded = load_dismissed_bundles({"20250615100000", "20250615120000"})
        assert len(loaded) == 2
        suffixes = {a.raw_suffix for a in loaded}
        assert suffixes == {"20250615100000", "20250615120000"}


def test_bundle_load_by_suffixes_with_children(tmp_path: Path) -> None:
    """Parent and child bundles are both returned when suffix is requested."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        parent = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="cl_1",
            raw_suffix="20250615100000",
            workflow="wf",
        )
        child0 = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="cl_1",
            raw_suffix="20250615100000",
            parent_workflow="wf",
            parent_timestamp="20250615100000",
            step_index=0,
        )
        child1 = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="cl_1",
            raw_suffix="20250615100000",
            parent_workflow="wf",
            parent_timestamp="20250615100000",
            step_index=1,
        )
        unrelated = _make_agent(cl_name="cl_2", raw_suffix="20250615110000")
        save_dismissed_bundle(parent)
        save_dismissed_bundle(child0)
        save_dismissed_bundle(child1)
        save_dismissed_bundle(unrelated)

        loaded = load_dismissed_bundles({"20250615100000"})
        assert len(loaded) == 3
        step_indices = sorted(a.step_index for a in loaded if a.step_index is not None)
        assert step_indices == [0, 1]


def test_bundle_load_by_suffixes_child_only(tmp_path: Path) -> None:
    """Child-only suffix (no parent .json) still returns children."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        child0 = _make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="cl_1",
            raw_suffix="20250615100000",
            parent_workflow="wf",
            parent_timestamp="20250615100000",
            step_index=0,
        )
        save_dismissed_bundle(child0)

        loaded = load_dismissed_bundles({"20250615100000"})
        assert len(loaded) == 1
        assert loaded[0].step_index == 0


def test_bundle_load_by_suffixes_ignores_unrelated_files(tmp_path: Path) -> None:
    """Files that don't match the suffix patterns are ignored."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    # Create files that should be ignored
    (bundles_dir / "README.txt").write_text("notes")
    (bundles_dir / "no_extension").write_text("{}")
    # Create an unrelated bundle file with a different suffix
    unrelated_path = bundles_dir / "99999999999999.json"
    unrelated_path.write_text("{}")

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = _make_agent(raw_suffix="20250615100000")
        save_dismissed_bundle(agent)

        loaded = load_dismissed_bundles({"20250615100000"})
        assert len(loaded) == 1
        assert loaded[0].raw_suffix == "20250615100000"


def test_bundle_no_limit(tmp_path: Path) -> None:
    """Test that all bundles are preserved (no trimming)."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        total = 600
        for i in range(total):
            agent = _make_agent(raw_suffix=f"{i:014d}")
            save_dismissed_bundle(agent)
        loaded = load_dismissed_bundles()
        assert len(loaded) == total


def test_remove_bundle_by_identity(tmp_path: Path) -> None:
    """Test removing a bundle by identity."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent1 = _make_agent(cl_name="cl_1", raw_suffix="20250615100000")
        agent2 = _make_agent(cl_name="cl_2", raw_suffix="20250615110000")
        save_dismissed_bundle(agent1)
        save_dismissed_bundle(agent2)

        result = remove_bundle_by_identity(agent1.identity)
        assert result is True

        loaded = load_dismissed_bundles()
        assert len(loaded) == 1
        assert loaded[0].identity == agent2.identity


def test_remove_bundle_with_child_suffixes(tmp_path: Path) -> None:
    """Test that removing a parent also removes specified child bundles."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
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

        save_dismissed_bundle(parent)
        save_dismissed_bundle(child1)
        save_dismissed_bundle(child2)
        save_dismissed_bundle(unrelated)

        result = remove_bundle_by_identity(
            parent.identity,
            child_raw_suffixes={"child1_suffix", "child2_suffix"},
        )
        assert result is True

        loaded = load_dismissed_bundles()
        assert len(loaded) == 1
        assert loaded[0].identity == unrelated.identity


def test_remove_bundle_returns_false_when_not_found(tmp_path: Path) -> None:
    """Test that removing a nonexistent bundle returns False."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = _make_agent()
        save_dismissed_bundle(agent)

        fake_identity = (AgentType.RUNNING, "nonexistent", "00000000000000")
        result = remove_bundle_by_identity(fake_identity)
        assert result is False


def test_bundle_save_skips_none_suffix(tmp_path: Path) -> None:
    """Test that saving a bundle with None raw_suffix returns False."""
    bundles_dir = tmp_path / "bundles"
    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir):
        agent = _make_agent(raw_suffix=None)
        assert save_dismissed_bundle(agent) is False


# --- Migration Tests ---


def test_migration_from_monolithic_file(tmp_path: Path) -> None:
    """Test one-time migration from old monolithic bundles file."""
    import json

    bundles_dir = tmp_path / "bundles"
    old_file = tmp_path / "old_bundles.json"

    agent1 = _make_agent(cl_name="cl_1", raw_suffix="20250615100000")
    agent2 = _make_agent(cl_name="cl_2", raw_suffix="20250615110000")
    old_file.write_text(json.dumps([agent1.to_bundle_dict(), agent2.to_bundle_dict()]))

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", old_file),
    ):
        loaded = load_dismissed_bundles()
        assert len(loaded) == 2
        suffixes = {a.raw_suffix for a in loaded}
        assert suffixes == {"20250615100000", "20250615110000"}

        # Old file should be deleted after migration
        assert not old_file.exists()
        # Individual files should exist (under YYYYMM shard).
        assert (bundles_dir / "202506" / "20250615100000.json").exists()
        assert (bundles_dir / "202506" / "20250615110000.json").exists()


def test_migration_skips_when_no_old_file(tmp_path: Path) -> None:
    """Test that migration is a no-op when the old file doesn't exist."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        loaded = load_dismissed_bundles()
        assert loaded == []
