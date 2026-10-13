"""Rebuild and archive-readiness tests for dismissed bundle indexing.

Split from ``tests.test_dismissed_bundle_index``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.dismissed_agents import (
    ensure_dismissed_archive_ready,
    load_dismissed_bundle_summaries,
    rebuild_dismissed_bundle_index,
    save_dismissed_bundle,
)
from sase.ace.dismissed_bundle_index import (
    SCHEMA_VERSION,
    archive_index_exists,
    dismissed_bundle_index_progress,
    index_signature,
    rebuild_index,
)
from sase.ace.tui.models.agent import AgentType
from tests._dismissed_agents_helpers import make_agent
from tests._dismissed_bundle_index_fixtures import _create_legacy_index

__all__ = [
    "test_dismissed_bundle_index_rebuild_and_query",
    "test_dismissed_bundle_index_schema_mismatch_recreates_table",
    "test_ensure_dismissed_archive_ready_builds_index",
    "test_rebuild_indexes_sharded_bundles_and_clears_progress",
    "test_rebuild_quarantines_and_recreates_corrupt_index",
    "test_v2_index_is_refilled_by_archive_ready_check",
]


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


def test_rebuild_quarantines_and_recreates_corrupt_index(tmp_path: Path) -> None:
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    index_path = bundles_dir / "index.sqlite"
    index_path.write_bytes(b"not a sqlite database")

    result = rebuild_index(bundles_dir)

    assert result.indexed_rows == 0
    assert index_signature(bundles_dir) is not None
    assert list(bundles_dir.glob("index.sqlite.corrupt-*"))


def test_dismissed_bundle_index_schema_mismatch_recreates_table(
    tmp_path: Path,
) -> None:
    """Opening an obsolete schema rebuilds the summary index."""
    bundles_dir = tmp_path / "bundles"
    shard = bundles_dir / "202506"
    shard.mkdir(parents=True)
    agent = make_agent(cl_name="indexed_cl", raw_suffix="20250615100000")
    (shard / "20250615100000.json").write_text(json.dumps(agent.to_bundle_dict()))
    index_path = bundles_dir / "index.sqlite"
    _create_legacy_index(index_path, version=2, obsolete=True)

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        assert rebuild_dismissed_bundle_index() == (1, 0)
        summaries = load_dismissed_bundle_summaries(cl_name="indexed_cl")

    assert [summary.raw_suffix for summary in summaries] == ["20250615100000"]
    signature = index_signature(bundles_dir)
    assert signature is not None
    assert signature[0] == SCHEMA_VERSION == 3


def test_rebuild_indexes_sharded_bundles_and_clears_progress(
    tmp_path: Path,
) -> None:
    """Rebuild indexes sharded bundles and clears the progress marker."""
    bundles_dir = tmp_path / "bundles"
    bundle_paths = (
        bundles_dir / "202607" / "20260715100000.json",
        bundles_dir / "202608" / "20260815100000.json",
        bundles_dir / "202609" / "20260915100000.json",
    )
    for path in bundle_paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "raw_suffix": path.stem,
                    "agent_type": "run",
                    "cl_name": "ordered",
                    "status": "DONE",
                }
            ),
            encoding="utf-8",
        )

    result = rebuild_index(bundles_dir)
    assert result.indexed_rows == 3
    signature = index_signature(bundles_dir)
    assert signature is not None
    assert signature[3] == 3
    assert dismissed_bundle_index_progress(bundles_dir).rebuilding is False


def test_v2_index_is_refilled_by_archive_ready_check(tmp_path: Path) -> None:
    """The schema bump makes the existing v2 index stale and rebuilds it."""
    bundles_dir = tmp_path / "bundles"
    shard = bundles_dir / "202506"
    shard.mkdir(parents=True)
    bundle = {
        "raw_suffix": "20250615100000",
        "agent_type": "run",
        "cl_name": "migrated",
        "status": "DONE",
    }
    (shard / "20250615100000.json").write_text(json.dumps(bundle))
    index_path = bundles_dir / "index.sqlite"
    _create_legacy_index(index_path, version=2, obsolete=False)

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        from sase.ace.dismissed_agents import ensure_dismissed_archive_ready

        ensure_dismissed_archive_ready()
        summaries = load_dismissed_bundle_summaries(cl_name="migrated")

    assert [summary.raw_suffix for summary in summaries] == ["20250615100000"]
