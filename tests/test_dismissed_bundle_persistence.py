"""Tests for dismissed bundle persistence."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase import project_display_names as pdn
from sase.ace.dismissed_agents import (
    has_dismissed_bundle,
    load_dismissed_bundle_summaries,
    load_dismissed_bundles_page,
    load_dismissed_bundles,
    save_dismissed_bundle,
)
from sase.ace.tui.models.agent import AgentType, LinkedRepoMetadata
from tests._dismissed_agents_helpers import make_agent


def test_bundle_save_load_round_trip(tmp_path: Path) -> None:
    """Test save/load round-trip for dismissed bundles."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent()
        agent.tribe = "backend"
        assert save_dismissed_bundle(agent)

        loaded = load_dismissed_bundles()
        assert len(loaded) == 1
        assert loaded[0].identity == agent.identity
        assert loaded[0].cl_name == "test_cl"
        assert loaded[0].tribe == "backend"
        assert loaded[0].start_time == datetime(2025, 6, 15, 10, 30, 0)


def test_bundle_load_attaches_project_display_name_without_serializing_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dismissed bundles stay canonical while rehydrated agents render nicely."""
    bundles_dir = tmp_path / "bundles"
    monkeypatch.setattr(
        pdn,
        "_project_display_name_map_cached",
        lambda *_args, **_kwargs: {"gh_acme__widgets": "widgets"},
    )
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(
            cl_name="gh_acme__widgets",
            raw_suffix="20250615103000",
        )
        agent.project_file = "/tmp/projects/gh_acme__widgets/gh_acme__widgets.sase"
        agent.project_display_name = "widgets"
        assert save_dismissed_bundle(agent)

        bundle_path = bundles_dir / "202506" / "20250615103000.json"
        bundle = json.loads(bundle_path.read_text())
        assert "project_display_name" not in bundle

        loaded = load_dismissed_bundles({"20250615103000"})

    assert len(loaded) == 1
    assert loaded[0].cl_name == "gh_acme__widgets"
    assert loaded[0].project_display_name == "widgets"
    assert loaded[0].display_name == "widgets"


def test_bundle_save_load_round_trip_with_linked_repos(tmp_path: Path) -> None:
    """Linked repo metadata survives the actual dismissed-bundle file path."""
    bundles_dir = tmp_path / "bundles"
    linked_repo = LinkedRepoMetadata(
        name="sase-core",
        workspace_dir="/tmp/sase-core_12",
    )
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent()
        agent.linked_repos = (linked_repo,)

        assert save_dismissed_bundle(agent)

        bundle_path = bundles_dir / "202506" / "20250615103000.json"
        bundle = json.loads(bundle_path.read_text())
        assert bundle["linked_repos"] == [
            {
                "name": "sase-core",
                "workspace_dir": "/tmp/sase-core_12",
            }
        ]
        loaded = load_dismissed_bundles({"20250615103000"})
        assert len(loaded) == 1
        assert loaded[0].linked_repos == (linked_repo,)


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
        agent1 = make_agent(cl_name="cl_1", raw_suffix="20250615100000")
        agent2 = make_agent(cl_name="cl_2", raw_suffix="20250615110000")
        agent3 = make_agent(cl_name="cl_3", raw_suffix="20250615120000")
        save_dismissed_bundle(agent1)
        save_dismissed_bundle(agent2)
        save_dismissed_bundle(agent3)

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
        parent = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="cl_1",
            raw_suffix="20250615100000",
            workflow="wf",
        )
        child0 = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="cl_1",
            raw_suffix="20250615100000",
            parent_workflow="wf",
            parent_timestamp="20250615100000",
            step_index=0,
        )
        child1 = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="cl_1",
            raw_suffix="20250615100000",
            parent_workflow="wf",
            parent_timestamp="20250615100000",
            step_index=1,
        )
        unrelated = make_agent(cl_name="cl_2", raw_suffix="20250615110000")
        save_dismissed_bundle(parent)
        save_dismissed_bundle(child0)
        save_dismissed_bundle(child1)
        save_dismissed_bundle(unrelated)

        loaded = load_dismissed_bundles({"20250615100000"})
    assert len(loaded) == 3
    step_indices = sorted(a.step_index for a in loaded if a.step_index is not None)
    assert step_indices == [0, 1]


def test_load_dismissed_bundles_page_loads_parent_rows_with_children(
    tmp_path: Path,
) -> None:
    """Paged archive loading pages visible parents and includes their steps."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        old_parent = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="paged_cl",
            raw_suffix="20250615100000",
            workflow="wf",
        )
        old_child = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="paged_cl",
            raw_suffix="20250615100000",
            parent_workflow="wf",
            parent_timestamp="20250615100000",
            step_index=0,
        )
        new_parent = make_agent(cl_name="paged_cl", raw_suffix="20250615110000")
        other = make_agent(cl_name="other_cl", raw_suffix="20250615120000")
        old_parent.start_time = datetime.strptime("20250615100000", "%Y%m%d%H%M%S")
        old_child.start_time = old_parent.start_time
        new_parent.start_time = datetime.strptime("20250615110000", "%Y%m%d%H%M%S")
        other.start_time = datetime.strptime("20250615120000", "%Y%m%d%H%M%S")
        for agent in (old_parent, old_child, new_parent, other):
            save_dismissed_bundle(agent)

        first_page, first_exhausted = load_dismissed_bundles_page(
            cl_name="paged_cl",
            limit=1,
            offset=0,
        )
        second_page, second_exhausted = load_dismissed_bundles_page(
            cl_name="paged_cl",
            limit=1,
            offset=1,
        )

    assert first_exhausted is False
    assert [agent.raw_suffix for agent in first_page] == ["20250615110000"]
    assert all(agent._loaded_from_dismissed_bundle for agent in first_page)
    assert second_exhausted is True
    assert {agent.raw_suffix for agent in second_page} == {"20250615100000"}
    assert sorted(
        agent.step_index for agent in second_page if agent.step_index is not None
    ) == [0]


def test_save_dismissed_bundle_writes_legacy_sharded_file(tmp_path: Path) -> None:
    """New dismissed bundles use the legacy sharded JSON file contract."""
    bundles_dir = tmp_path / "bundles"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_xprompt.md").write_text("findable prompt")
    (artifacts_dir / "live_reply.md").write_text("findable reply")
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(cl_name="indexed_cl", raw_suffix="20250615100000")
        agent.artifacts_dir = str(artifacts_dir)
        assert save_dismissed_bundle(agent)
        bundle_path = bundles_dir / "202506" / "20250615100000.json"
        assert bundle_path.is_file()
        bundle = json.loads(bundle_path.read_text())
        assert bundle["raw_suffix"] == "20250615100000"
        assert bundle["cl_name"] == "indexed_cl"
        assert bundle["artifacts_dir"] == str(artifacts_dir)
        serialized = json.dumps(bundle)
        assert "findable prompt" not in serialized
        assert "findable reply" not in serialized

        for path in artifacts_dir.iterdir():
            path.unlink()

        loaded = load_dismissed_bundles({"20250615100000"})
        assert len(loaded) == 1
        assert loaded[0].identity == agent.identity


def test_re_dismiss_overwrites_legacy_bundle_path(
    tmp_path: Path,
) -> None:
    """Repeated dismissals return to the legacy single-bundle path."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(cl_name="indexed_cl", raw_suffix="20250615100000")
        agent.status = "FAILED"
        assert save_dismissed_bundle(agent)
        first_path = bundles_dir / "202506" / "20250615100000.json"
        first_payload = json.loads(first_path.read_text())
        assert first_payload["status"] == "FAILED"

        agent.status = "DONE"
        assert save_dismissed_bundle(agent)
        paths = sorted((bundles_dir / "202506").glob("*.json"))
        assert paths == [first_path]
        assert json.loads(first_path.read_text())["status"] == "DONE"

        summaries = load_dismissed_bundle_summaries(suffixes={"20250615100000"})
        assert [summary.raw_suffix for summary in summaries] == ["20250615100000"]
        loaded = load_dismissed_bundles({"20250615100000"})
        assert len(loaded) == 1
        assert loaded[0].status == "DONE"


@pytest.mark.slow
def test_save_dismissed_bundle_is_fast_with_many_existing_bundles(
    tmp_path: Path,
) -> None:
    """Saving a new bundle must not scale with the size of the archive."""
    import time

    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        for i in range(1000):
            agent = make_agent(cl_name=f"cl_{i}", raw_suffix=f"{i:014d}")
            assert save_dismissed_bundle(agent)

        target = make_agent(cl_name="hotpath", raw_suffix="99999999999999")
        start = time.perf_counter()
        assert save_dismissed_bundle(target)
        elapsed = time.perf_counter() - start

    assert elapsed < 1.0, f"save_dismissed_bundle took {elapsed:.3f}s with 1k bundles"


def test_dismissed_bundle_python_fallback_uses_atomic_legacy_file(
    tmp_path: Path,
) -> None:
    """Fallback writes through a temp file before replacing the legacy path."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
        patch("sase.core.agent_cleanup_execution.require_rust_binding") as binding,
    ):
        binding.side_effect = ImportError
        agent = make_agent(cl_name="indexed_cl", raw_suffix="20250615100000")
        assert save_dismissed_bundle(agent)

    bundle_path = bundles_dir / "202506" / "20250615100000.json"
    assert bundle_path.is_file()
    assert json.loads(bundle_path.read_text())["raw_suffix"] == "20250615100000"
    assert not list((bundles_dir / "202506").glob("*.tmp.*"))


def test_bundle_load_by_suffixes_child_only(tmp_path: Path) -> None:
    """Child-only suffix (no parent .json) still returns children."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        child0 = make_agent(
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


def test_has_dismissed_bundle_finds_sharded_and_legacy_files(tmp_path: Path) -> None:
    """Bundle existence checks understand sharded and legacy layouts."""
    bundles_dir = tmp_path / "bundles"
    shard_dir = bundles_dir / "202506"
    shard_dir.mkdir(parents=True)
    (shard_dir / "20250615100000.json").write_text("{}")
    (shard_dir / "20250615110000__c0.json").write_text("{}")
    bundles_dir.mkdir(exist_ok=True)
    (bundles_dir / "20250615120000.json").write_text("{}")
    (bundles_dir / "20250615130000__c0.json").write_text("{}")

    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir):
        assert has_dismissed_bundle("20250615100000")
        assert has_dismissed_bundle("20250615110000")
        assert has_dismissed_bundle("20250615120000")
        assert has_dismissed_bundle("20250615130000")
        assert not has_dismissed_bundle("20250615140000")


def test_bundle_load_by_suffixes_ignores_unrelated_files(tmp_path: Path) -> None:
    """Files that don't match the suffix patterns are ignored."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    (bundles_dir / "README.txt").write_text("notes")
    (bundles_dir / "no_extension").write_text("{}")
    (bundles_dir / "99999999999999.json").write_text("{}")

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(raw_suffix="20250615100000")
        save_dismissed_bundle(agent)

        loaded = load_dismissed_bundles({"20250615100000"})
        assert len(loaded) == 1
        assert loaded[0].raw_suffix == "20250615100000"


@pytest.mark.slow
def test_bundle_no_limit(tmp_path: Path) -> None:
    """Test that all bundles are preserved (no trimming)."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        total = 600
        for i in range(total):
            agent = make_agent(raw_suffix=f"{i:014d}")
            save_dismissed_bundle(agent)
        loaded = load_dismissed_bundles()
        assert len(loaded) == total


@pytest.mark.slow
def test_bundle_save_does_not_leak_index_file_descriptors(tmp_path: Path) -> None:
    """Repeated bundle saves should close SQLite index file descriptors."""
    fd_dir = Path("/proc/self/fd")
    if not fd_dir.is_dir():
        pytest.skip("/proc/self/fd is only available on Linux")

    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        before = len(list(fd_dir.iterdir()))
        for i in range(200):
            agent = make_agent(raw_suffix=f"{i:014d}")
            assert save_dismissed_bundle(agent)
        after = len(list(fd_dir.iterdir()))

    assert after - before < 20


def test_bundle_save_skips_none_suffix(tmp_path: Path) -> None:
    """Test that saving a bundle with None raw_suffix returns False."""
    bundles_dir = tmp_path / "bundles"
    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir):
        agent = make_agent(raw_suffix=None)
        assert save_dismissed_bundle(agent) is False
