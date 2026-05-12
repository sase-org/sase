"""Tests for dismissed bundle removal and legacy migration."""

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    load_dismissed_bundles,
    remove_bundle_by_identity,
    save_dismissed_bundle,
)
from sase.ace.tui.models.agent import AgentType
from tests._dismissed_agents_helpers import make_agent, saved_revision_bundles


def test_remove_bundle_by_identity(tmp_path: Path) -> None:
    """Test removing a bundle by identity."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent1 = make_agent(cl_name="cl_1", raw_suffix="20250615100000")
        agent2 = make_agent(cl_name="cl_2", raw_suffix="20250615110000")
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
        parent = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="my_cl",
            raw_suffix="20250615103000",
            workflow="gh",
        )
        child1 = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="my_cl",
            raw_suffix="child1_suffix",
            parent_workflow="gh",
            parent_timestamp="20250615103000",
            step_index=0,
        )
        child2 = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="my_cl",
            raw_suffix="child2_suffix",
            parent_workflow="gh",
            parent_timestamp="20250615103000",
            step_index=1,
        )
        unrelated = make_agent(cl_name="other", raw_suffix="20250615120000")

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
        agent = make_agent()
        save_dismissed_bundle(agent)

        fake_identity = (AgentType.RUNNING, "nonexistent", "00000000000000")
        result = remove_bundle_by_identity(fake_identity)
        assert result is False


def test_migration_from_monolithic_file(tmp_path: Path) -> None:
    """Test one-time migration from old monolithic bundles file."""
    bundles_dir = tmp_path / "bundles"
    old_file = tmp_path / "old_bundles.json"

    agent1 = make_agent(cl_name="cl_1", raw_suffix="20250615100000")
    agent2 = make_agent(cl_name="cl_2", raw_suffix="20250615110000")
    old_file.write_text(json.dumps([agent1.to_bundle_dict(), agent2.to_bundle_dict()]))

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", old_file),
    ):
        loaded = load_dismissed_bundles()
        assert len(loaded) == 2
        suffixes = {a.raw_suffix for a in loaded}
        assert suffixes == {"20250615100000", "20250615110000"}

        assert not old_file.exists()
        assert len(saved_revision_bundles(bundles_dir)) == 2


def test_migration_skips_when_no_old_file(tmp_path: Path) -> None:
    """Test that migration is a no-op when the old file doesn't exist."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        loaded = load_dismissed_bundles()
        assert loaded == []
