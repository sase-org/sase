"""Tests for dismissed bundle indexing."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    ensure_dismissed_archive_ready,
    load_dismissed_bundle_summaries,
    load_dismissed_bundles,
    rebuild_dismissed_bundle_index,
    save_dismissed_bundle,
    verify_dismissed_bundle_index,
)
from sase.ace.dismissed_bundle_index import archive_index_exists
from sase.ace.tui.models.agent import AgentType
from tests._dismissed_agents_helpers import make_agent


def test_ensure_dismissed_archive_ready_builds_index(tmp_path: Path) -> None:
    """First call builds the legacy summary index; subsequent calls short-circuit."""
    bundles_dir = tmp_path / "bundles"
    shard = bundles_dir / "202506"
    shard.mkdir(parents=True)
    (shard / "20250615100000.json").write_text(
        json.dumps(
            {
                "raw_suffix": "20250615100000",
                "agent_type": "run",
                "cl_name": "ready_cl",
                "agent_name": "ready_agent",
                "status": "DONE",
                "start_time": "2026-05-12T12:00:00",
                "project_file": "/tmp/projects/p/p.sase",
                "model": "gpt",
                "llm_provider": "codex",
            }
        )
    )

    with patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir):
        assert not archive_index_exists(bundles_dir)
        ensure_dismissed_archive_ready()
        assert archive_index_exists(bundles_dir)
        ensure_dismissed_archive_ready()
        assert archive_index_exists(bundles_dir)


def test_dismissed_bundle_index_rebuild_and_query(tmp_path: Path) -> None:
    """Rebuild stores legacy summaries for sharded and top-level bundles."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        parent = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="indexed_cl",
            raw_suffix="20250615100000",
            workflow="wf",
        )
        child = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="indexed_cl",
            raw_suffix="20250615100000",
            parent_workflow="wf",
            parent_timestamp="20250615100000",
            step_index=0,
        )
        legacy = make_agent(cl_name="legacy_cl", raw_suffix="20250615110000")
        save_dismissed_bundle(parent)
        save_dismissed_bundle(child)
        bundles_dir.mkdir(parents=True, exist_ok=True)
        (bundles_dir / "20250615110000.json").write_text(
            json.dumps(legacy.to_bundle_dict())
        )

        indexed, skipped = rebuild_dismissed_bundle_index()
        assert (indexed, skipped) == (3, 0)

        summaries = load_dismissed_bundle_summaries(cl_name="indexed_cl")
        assert len(summaries) == 2
        assert {summary.filename for summary in summaries} == {
            "20250615100000.json",
            "20250615100000__c0.json",
        }
        assert any(summary.is_workflow_child for summary in summaries)
        assert load_dismissed_bundle_summaries(project_name="bundles") == []


def test_dismissed_bundle_index_legacy_summary_fields(tmp_path: Path) -> None:
    """Legacy summary rows expose only storage and revive lookup fields."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(
            cl_name="indexed_cl",
            raw_suffix="20250615100000",
            status="FAILED",
        )
        agent.agent_name = "indexed_agent"
        agent.model = "gpt-test"
        agent.llm_provider = "codex"
        bundle = agent.to_bundle_dict()
        shard = bundles_dir / "202506"
        shard.mkdir(parents=True)
        (shard / "20250615100000.json").write_text(json.dumps(bundle))

        assert rebuild_dismissed_bundle_index() == (1, 0)
        [summary] = load_dismissed_bundle_summaries(cl_name="indexed_cl")

    assert summary.raw_suffix == "20250615100000"
    assert summary.bundle_path.endswith("20250615100000.json")
    assert summary.shard == "202506"
    assert summary.filename == "20250615100000.json"
    assert summary.agent_type == AgentType.RUNNING.value
    assert summary.cl_name == "indexed_cl"
    assert summary.agent_name == "indexed_agent"
    assert summary.status == "FAILED"
    assert summary.model == "gpt-test"
    assert summary.llm_provider == "codex"
    assert set(summary.__dataclass_fields__) == {
        "agent_name",
        "agent_type",
        "bundle_path",
        "cl_name",
        "filename",
        "is_workflow_child",
        "llm_provider",
        "meta_changespec",
        "model",
        "parent_timestamp",
        "project_file",
        "raw_suffix",
        "retried_as_timestamp",
        "retry_attempt",
        "retry_chain_root_timestamp",
        "retry_of_timestamp",
        "shard",
        "start_time",
        "status",
        "step_index",
        "step_name",
        "stop_time",
        "vcs_provider",
        "workflow",
    }


def test_dismissed_bundle_index_schema_mismatch_recreates_table(
    tmp_path: Path,
) -> None:
    """Opening a non-legacy schema drops and rebuilds the summary table."""
    bundles_dir = tmp_path / "bundles"
    shard = bundles_dir / "202506"
    shard.mkdir(parents=True)
    agent = make_agent(cl_name="indexed_cl", raw_suffix="20250615100000")
    (shard / "20250615100000.json").write_text(json.dumps(agent.to_bundle_dict()))
    index_path = bundles_dir / "index.sqlite"
    with sqlite3.connect(index_path) as conn:
        conn.execute(
            "CREATE TABLE dismissed_bundle_index_meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO dismissed_bundle_index_meta(key, value) "
            "VALUES ('schema_version', '2')"
        )
        conn.execute(
            "CREATE TABLE dismissed_bundle_summaries "
            "(bundle_path TEXT PRIMARY KEY, obsolete_col INTEGER)"
        )

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        assert rebuild_dismissed_bundle_index() == (1, 0)
        summaries = load_dismissed_bundle_summaries(cl_name="indexed_cl")

    assert [summary.raw_suffix for summary in summaries] == ["20250615100000"]
    with sqlite3.connect(index_path) as conn:
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(dismissed_bundle_summaries)")
        }
    assert "obsolete_col" not in columns
    assert {"bundle_path", "raw_suffix", "cl_name", "mtime_ns", "size_bytes"} <= columns


def test_dismissed_bundle_verify_reports_stale_and_missing_rows(
    tmp_path: Path,
) -> None:
    """Verification compares legacy summary rows against source bundle files."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        target = make_agent(cl_name="indexed_cl", raw_suffix="20250615100000")
        unrelated = make_agent(cl_name="other", raw_suffix="20250615110000")
        save_dismissed_bundle(target)
        save_dismissed_bundle(unrelated)
        assert rebuild_dismissed_bundle_index() == (2, 0)
        (bundles_dir / "202506" / "20250615110000.json").unlink()
        extra = make_agent(cl_name="extra", raw_suffix="20250615120000")
        (bundles_dir / "202506" / "20250615120000.json").write_text(
            json.dumps(extra.to_bundle_dict())
        )
        result = verify_dismissed_bundle_index()

    assert result["ok"] is False
    assert result["indexed_rows"] == 2
    assert result["valid_bundles"] == 2
    assert result["stale_rows"] == 1
    assert result["missing_rows"] == 1


def test_load_dismissed_bundles_by_suffix_uses_legacy_index(tmp_path: Path) -> None:
    """Indexed suffix loads return parent and child legacy bundle files."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        parent = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="indexed_cl",
            raw_suffix="20250615100000",
            workflow="wf",
        )
        child = make_agent(
            agent_type=AgentType.WORKFLOW,
            cl_name="indexed_cl",
            raw_suffix="20250615100000",
            parent_workflow="wf",
            parent_timestamp="20250615100000",
            step_index=0,
        )
        save_dismissed_bundle(parent)
        save_dismissed_bundle(child)
        assert rebuild_dismissed_bundle_index() == (2, 0)

        loaded = load_dismissed_bundles({"20250615100000"})

    assert len(loaded) == 2
    assert sorted(
        agent.step_index for agent in loaded if agent.step_index is not None
    ) == [0]
