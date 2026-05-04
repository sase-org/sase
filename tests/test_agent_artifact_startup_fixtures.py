"""Regression fixture tests for agent artifact startup performance work."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.ace import dismissed_agents
from sase.ace.dismissed_agents import load_dismissed_bundles
from sase.ace.tui.models.agent import Agent
from tests.ace.agent_artifact_startup_fixtures import (
    build_dismissed_bundle_archive,
    build_retry_chain_agents,
    build_retry_chain_marker_edges,
    build_workflow_collision_archive,
)


def test_dismissed_archive_fixture_covers_shards_legacy_and_corrupt_files(
    tmp_path: Path,
) -> None:
    bundles_dir = tmp_path / "bundles"
    fixture = build_dismissed_bundle_archive(
        bundles_dir,
        total=12,
        legacy_count=3,
        corrupt_count=2,
    )

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        loaded = load_dismissed_bundles()

    assert len(fixture.agents) == 12
    assert len(loaded) == 12
    assert len(fixture.corrupt_paths) == 2
    assert all(
        (bundles_dir / "202501" / f"{a.raw_suffix}.json").exists()
        for a in fixture.agents[3:]
    )
    assert all(
        (bundles_dir / f"{a.raw_suffix}.json").exists() for a in fixture.agents[:3]
    )


def test_suffix_filtered_bundle_load_does_not_hydrate_unrelated_parent(
    tmp_path: Path,
) -> None:
    bundles_dir = tmp_path / "bundles"
    parent, children, unrelated = build_workflow_collision_archive(bundles_dir)
    loaded_paths: list[str] = []
    original_load = dismissed_agents._load_bundle_file

    def track_loaded_path(path: Path) -> Agent | None:
        loaded_paths.append(path.name)
        return original_load(path)

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
        patch(
            "sase.ace.dismissed_agents._load_bundle_file",
            side_effect=track_loaded_path,
        ),
    ):
        loaded = load_dismissed_bundles({parent.raw_suffix or ""})

    assert {agent.identity for agent in loaded} == {
        parent.identity,
        *(child.identity for child in children),
    }
    assert set(loaded_paths) == {
        f"{parent.raw_suffix}.json",
        f"{parent.raw_suffix}__c0.json",
        f"{parent.raw_suffix}__c1.json",
    }
    assert f"{unrelated.raw_suffix}.json" not in loaded_paths


def test_retry_chain_fixture_preserves_forward_and_backward_edges() -> None:
    root, child, grandchild = build_retry_chain_agents()
    round_tripped = [
        Agent.from_bundle_dict(agent.to_bundle_dict())
        for agent in (root, child, grandchild)
    ]

    assert round_tripped[0].retried_as_timestamp == child.raw_suffix
    assert round_tripped[1].retry_of_timestamp == root.raw_suffix
    assert round_tripped[1].retried_as_timestamp == grandchild.raw_suffix
    assert round_tripped[2].retry_of_timestamp == child.raw_suffix
    assert {agent.retry_chain_root_timestamp for agent in round_tripped} == {
        root.raw_suffix
    }


def test_retry_chain_marker_fixture_writes_edge_fields(tmp_path: Path) -> None:
    fixture = build_retry_chain_marker_edges(tmp_path / "artifacts")
    root, child, grandchild = fixture.agents
    root_dir, child_dir, grandchild_dir = fixture.marker_dirs

    assert (root_dir / "agent_meta.json").read_text(encoding="utf-8")
    assert f'"retried_as_timestamp": "{child.raw_suffix}"' in (
        root_dir / "done.json"
    ).read_text(encoding="utf-8")
    assert f'"retry_of_timestamp": "{root.raw_suffix}"' in (
        child_dir / "agent_meta.json"
    ).read_text(encoding="utf-8")
    assert f'"retry_of_timestamp": "{child.raw_suffix}"' in (
        grandchild_dir / "done.json"
    ).read_text(encoding="utf-8")
