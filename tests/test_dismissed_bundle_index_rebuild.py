"""Rebuild and archive-readiness tests for dismissed bundle indexing.

Split from ``tests.test_dismissed_bundle_index``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import sqlite3
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

__all__ = [
    "test_dismissed_bundle_index_rebuild_and_query",
    "test_dismissed_bundle_index_schema_mismatch_recreates_table",
    "test_ensure_dismissed_archive_ready_builds_index",
    "test_rebuild_indexes_newest_shards_first_and_reports_progress",
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
    assert {
        "bundle_path",
        "raw_suffix",
        "cl_name",
        "agent_session",
        "agent_session_role",
        "agent_clan",
        "agent_clan_generation",
        "agent_tab",
        "tribe",
        "clan_tribe",
        "mtime_ns",
        "size_bytes",
    } <= columns
    with sqlite3.connect(index_path) as conn:
        version = conn.execute(
            "SELECT value FROM dismissed_bundle_index_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert int(version) == SCHEMA_VERSION == 3


def test_rebuild_indexes_newest_shards_first_and_reports_progress(
    tmp_path: Path,
) -> None:
    """Rebuild scans recent bundles first and exposes cheap progress updates."""
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

    import sase.ace.dismissed_bundle_index._api as api
    import sase.ace.dismissed_bundle_index._schema as schema

    read_bundle = schema.read_bundle
    real_set_progress = api._set_rebuild_progress
    read_order: list[Path] = []
    progress_rows: list[int] = []

    def tracked_read(path: Path) -> dict[str, object]:
        read_order.append(path)
        return read_bundle(path)

    def tracked_progress(key: str, indexed_rows: int) -> None:
        real_set_progress(key, indexed_rows)
        progress = dismissed_bundle_index_progress(bundles_dir)
        assert progress.rebuilding is True
        progress_rows.append(progress.indexed_rows)

    with (
        patch.object(schema, "read_bundle", tracked_read),
        patch.object(api, "_set_rebuild_progress", tracked_progress),
    ):
        result = rebuild_index(bundles_dir)

    assert result.indexed_rows == 3
    assert read_order == [bundle_paths[2], bundle_paths[1], bundle_paths[0]]
    assert progress_rows == [0, 1, 2, 3]
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
    with sqlite3.connect(index_path) as conn:
        conn.execute(
            "CREATE TABLE dismissed_bundle_index_meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO dismissed_bundle_index_meta(key, value) VALUES "
            "('schema_version', '2')"
        )
        conn.execute(
            "CREATE TABLE dismissed_bundle_summaries "
            "(bundle_path TEXT PRIMARY KEY, mtime_ns INTEGER, size_bytes INTEGER)"
        )
        conn.commit()

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        from sase.ace.dismissed_agents import ensure_dismissed_archive_ready

        ensure_dismissed_archive_ready()
        summaries = load_dismissed_bundle_summaries(cl_name="migrated")

    assert [summary.raw_suffix for summary in summaries] == ["20250615100000"]
