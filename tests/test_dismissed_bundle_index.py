"""Tests for dismissed bundle indexing."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    dismissed_bundle_identities_snapshot,
    ensure_dismissed_archive_ready,
    load_dismissed_bundle_identities,
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


def test_dismissed_bundle_index_query_summaries_supports_offset(
    tmp_path: Path,
) -> None:
    """Offset paging returns disjoint newest-first summary pages."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        for suffix in (
            "20250615100000",
            "20250615110000",
            "20250615120000",
        ):
            agent = make_agent(cl_name="indexed_cl", raw_suffix=suffix)
            agent.start_time = datetime.strptime(suffix, "%Y%m%d%H%M%S")
            save_dismissed_bundle(agent)
        assert rebuild_dismissed_bundle_index() == (3, 0)

        first_page = load_dismissed_bundle_summaries(
            cl_name="indexed_cl",
            limit=2,
            offset=0,
        )
        second_page = load_dismissed_bundle_summaries(
            cl_name="indexed_cl",
            limit=2,
            offset=2,
        )

    assert [summary.raw_suffix for summary in first_page] == [
        "20250615120000",
        "20250615110000",
    ]
    assert [summary.raw_suffix for summary in second_page] == ["20250615100000"]


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


def test_dismissed_bundle_verify_skips_json_parse_of_indexed_bundles(
    tmp_path: Path,
) -> None:
    """Verify is signature-based: indexed bundles are never JSON-parsed."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        save_dismissed_bundle(make_agent(cl_name="cl", raw_suffix="20250615100000"))
        assert rebuild_dismissed_bundle_index() == (1, 0)

        def fail_read(path: Path) -> dict[str, object]:
            raise AssertionError(f"verify parsed an indexed bundle: {path}")

        with patch("sase.ace.dismissed_bundle_index._api.read_bundle", fail_read):
            result = verify_dismissed_bundle_index()

    assert result["ok"] is True
    assert result["indexed_rows"] == 1


def test_dismissed_bundle_verify_detects_changed_file_signature(
    tmp_path: Path,
) -> None:
    """A rewritten bundle (mtime/size drift) is reported as a stale row."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(cl_name="cl", raw_suffix="20250615100000")
        save_dismissed_bundle(agent)
        assert rebuild_dismissed_bundle_index() == (1, 0)
        bundle_path = bundles_dir / "202506" / "20250615100000.json"
        bundle = json.loads(bundle_path.read_text())
        bundle["status"] = "REWRITTEN_WITH_A_DIFFERENT_SIZE"
        bundle_path.write_text(json.dumps(bundle))

        result = verify_dismissed_bundle_index()

    assert result["ok"] is False
    assert result["stale_rows"] == 1
    assert result["missing_rows"] == 0


def test_dismissed_bundle_verify_treats_unindexed_corrupt_file_as_corrupt(
    tmp_path: Path,
) -> None:
    """A corrupt unindexed file counts as corrupt, not missing.

    Flagging it missing would make every verify fail and trigger a full
    rebuild on every sync, since rebuild rightly skips corrupt files.
    """
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        save_dismissed_bundle(make_agent(cl_name="cl", raw_suffix="20250615100000"))
        assert rebuild_dismissed_bundle_index() == (1, 0)
        (bundles_dir / "202506" / "20250615110000.json").write_text("{not json")

        result = verify_dismissed_bundle_index()

    assert result["ok"] is True
    assert result["corrupt_bundles"] == 1
    assert result["missing_rows"] == 0


def test_load_dismissed_bundle_identities_matches_summary_projection(
    tmp_path: Path,
) -> None:
    """The SQL identity projection equals the old summary-derived identity set."""
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
        other = make_agent(cl_name="other_cl", raw_suffix="20250615110000")
        for agent in (parent, child, other):
            save_dismissed_bundle(agent)
        assert rebuild_dismissed_bundle_index() == (3, 0)

        identities = load_dismissed_bundle_identities()
        summaries = load_dismissed_bundle_summaries(limit=None)

    expected = {
        (
            str(summary.agent_type),
            str(summary.cl_name or "unknown"),
            str(summary.raw_suffix) if summary.raw_suffix else None,
        )
        for summary in summaries
    }
    assert identities == expected
    assert identities == {
        ("workflow", "indexed_cl", "20250615100000"),
        ("run", "other_cl", "20250615110000"),
    }


def test_dismissed_bundle_identities_snapshot_reuses_unchanged_signature() -> None:
    signature = (1, 2, 3, 4)
    identity = ("run", "indexed_cl", "20250615110000")

    with (
        patch(
            "sase.ace.dismissed_agents.dismissed_bundle_index_signature",
            return_value=signature,
        ),
        patch(
            "sase.ace.dismissed_bundle_index.query_summary_identities",
            return_value={identity},
        ) as query,
        patch(
            "sase.ace.dismissed_agents."
            "_dismissed_bundle_identities_snapshot_initialized",
            False,
        ),
        patch(
            "sase.ace.dismissed_agents._dismissed_bundle_identities_snapshot_signature",
            None,
        ),
        patch(
            "sase.ace.dismissed_agents._dismissed_bundle_identities_snapshot_cache",
            frozenset(),
        ),
    ):
        first = dismissed_bundle_identities_snapshot()
        first.clear()
        second = dismissed_bundle_identities_snapshot()

    assert second == {
        (AgentType.RUNNING, "indexed_cl", "20250615110000"),
    }
    query.assert_called_once()


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
