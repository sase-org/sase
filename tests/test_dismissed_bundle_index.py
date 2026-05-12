"""Tests for dismissed bundle indexing."""

import json
import sqlite3
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

from sase.ace.archive_search_text import ARCHIVE_BUNDLE_SCHEMA_VERSION
from sase.ace.dismissed_agents import (
    load_dismissed_bundle_summaries,
    load_dismissed_bundles,
    rebuild_dismissed_bundle_index,
    remove_bundle_by_identity,
    save_dismissed_bundle,
    verify_dismissed_bundle_index,
)
from sase.ace.tui.models.agent import AgentType
from tests._dismissed_agents_helpers import make_agent


def test_dismissed_bundle_index_rebuild_and_query(tmp_path: Path) -> None:
    """Rebuild stores queryable summaries for sharded and legacy bundles."""
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
        legacy_dir = bundles_dir
        legacy_dir.mkdir(parents=True, exist_ok=True)
        (legacy_dir / "20250615110000.json").write_text(
            json.dumps(legacy.to_bundle_dict())
        )

        indexed, skipped = rebuild_dismissed_bundle_index()
        assert (indexed, skipped) == (3, 0)

        summaries = load_dismissed_bundle_summaries(cl_name="indexed_cl")
        assert len(summaries) == 2
        assert all(summary.filename.endswith("/bundle.json") for summary in summaries)
        assert any(summary.is_workflow_child for summary in summaries)
        assert load_dismissed_bundle_summaries(project_name="bundles") == []


def test_dismissed_bundle_index_v2_summary_fields(tmp_path: Path) -> None:
    """V2 rows expose stable archive metadata and query-facing fields."""
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
        agent.error_message = "x" * 600
        bundle = agent.to_bundle_dict()
        bundle.update(
            {
                "archive_revision": 3,
                "bundle_schema_version": 2,
                "dismissed_at": "2026-05-12T16:00:00",
                "revived_at": "2026-05-12T16:30:00",
                "times_revived": 2,
                "cost_usd_micros": 12345,
                "usage": {"input_tokens": 101, "output_tokens": 202},
            }
        )
        shard = bundles_dir / "202506"
        shard.mkdir(parents=True)
        (shard / "20250615100000.json").write_text(json.dumps(bundle))

        assert rebuild_dismissed_bundle_index() == (1, 0)
        [summary] = load_dismissed_bundle_summaries(cl_name="indexed_cl")

    expected_agent_id = sha256(
        "\0".join(
            (
                "/tmp/test.sase",
                "20250615100000",
                AgentType.RUNNING.value,
                "",
            )
        ).encode("utf-8")
    ).hexdigest()
    assert summary.agent_id == expected_agent_id
    assert summary.archive_revision == 3
    assert summary.bundle_schema_version == 2
    assert summary.dismissed_at == "2026-05-12T16:00:00"
    assert summary.revived_at == "2026-05-12T16:30:00"
    assert summary.times_revived == 2
    assert summary.project_name == "tmp"
    assert summary.runtime == "codex"
    assert summary.cost_usd_micros == 12345
    assert summary.input_tokens == 101
    assert summary.output_tokens == 202
    assert summary.error_message_excerpt == "x" * 500


def test_dismissed_bundle_index_v2_defaults_legacy_bundles(
    tmp_path: Path,
) -> None:
    """Bundles missing new archive fields remain indexable."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(cl_name="legacy_cl", raw_suffix="20250615100000")
        bundle = agent.to_bundle_dict()
        bundle.pop("archive_revision", None)
        bundle.pop("bundle_schema_version", None)
        bundle.pop("archive_search_text", None)
        shard = bundles_dir / "202506"
        shard.mkdir(parents=True)
        (shard / "20250615100000.json").write_text(json.dumps(bundle))
        [summary] = load_dismissed_bundle_summaries(cl_name="legacy_cl")

    assert summary.archive_revision == 1
    assert summary.bundle_schema_version == ARCHIVE_BUNDLE_SCHEMA_VERSION
    assert summary.dismissed_at is not None
    assert summary.revived_at is None
    assert summary.times_revived == 0
    assert summary.cost_usd_micros is None
    assert summary.input_tokens is None
    assert summary.output_tokens is None


def test_next_archive_revision_does_not_scan_bundle_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The hot dismiss path trusts the SQLite index instead of scanning files."""
    from sase.ace.dismissed_bundle_index import next_archive_revision

    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(cl_name="indexed_cl", raw_suffix="20250615100000")
        assert save_dismissed_bundle(agent)
        assert save_dismissed_bundle(agent)

        def fail_read(*args, **kwargs):
            raise AssertionError("next_archive_revision should not read bundle files")

        def fail_iter(*args, **kwargs):
            raise AssertionError(
                "next_archive_revision should not iterate bundle paths"
            )

        monkeypatch.setattr(
            "sase.ace.dismissed_bundle_index._api.read_bundle", fail_read
        )
        monkeypatch.setattr(
            "sase.ace.dismissed_bundle_index._api.iter_bundle_paths", fail_iter
        )

        bundle = agent.to_bundle_dict()
        assert next_archive_revision(bundles_dir, bundle) == 3


def test_rebuild_index_backfills_legacy_bundle_search_projection(
    tmp_path: Path,
) -> None:
    """Index rebuild backfills old bundle JSON from surviving artifact files."""
    bundles_dir = tmp_path / "bundles"
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    (artifacts_dir / "raw_xprompt.md").write_text("legacy prompt")
    bundle = make_agent(
        cl_name="legacy_cl",
        raw_suffix="20250615100000",
    ).to_bundle_dict()
    bundle["artifacts_dir"] = str(artifacts_dir)
    bundle.pop("archive_search_text", None)
    bundle.pop("bundle_schema_version", None)
    shard = bundles_dir / "202506"
    shard.mkdir(parents=True)
    bundle_path = shard / "20250615100000.json"
    bundle_path.write_text(json.dumps(bundle))

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        assert rebuild_dismissed_bundle_index() == (1, 0)

    backfilled = json.loads(bundle_path.read_text())
    assert backfilled["bundle_schema_version"] == ARCHIVE_BUNDLE_SCHEMA_VERSION
    assert "legacy prompt" in backfilled["archive_search_text"]


def test_dismissed_bundle_index_v1_migration_rebuilds_from_bundles(
    tmp_path: Path,
) -> None:
    """Opening a v1 index rebuilds v2 summaries from bundle files."""
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
            "VALUES ('schema_version', '1')"
        )
        conn.execute(
            "CREATE TABLE dismissed_bundle_summaries "
            "(bundle_path TEXT PRIMARY KEY, raw_suffix TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO dismissed_bundle_summaries(bundle_path, raw_suffix) "
            "VALUES ('/stale/path.json', 'stale')"
        )

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        summaries = load_dismissed_bundle_summaries(cl_name="indexed_cl")

    assert [summary.raw_suffix for summary in summaries] == ["20250615100000"]
    with sqlite3.connect(index_path) as conn:
        version = conn.execute(
            "SELECT value FROM dismissed_bundle_index_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
        columns = {
            row[1]
            for row in conn.execute("PRAGMA table_info(dismissed_bundle_summaries)")
        }
    assert version == "2"
    assert {"agent_id", "dismissed_at", "runtime", "input_tokens"}.issubset(columns)


def test_rebuild_shards_legacy_root_bundle_files(tmp_path: Path) -> None:
    """Archive maintenance moves pre-shard root bundles before indexing."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    legacy = make_agent(cl_name="legacy_cl", raw_suffix="20250615110000")
    root_path = bundles_dir / "20250615110000.json"
    root_path.write_text(json.dumps(legacy.to_bundle_dict()))

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        indexed, skipped = rebuild_dismissed_bundle_index()

        assert (indexed, skipped) == (1, 0)
        assert not root_path.exists()
        assert (bundles_dir / "202506" / "20250615110000.json").exists()
        assert (bundles_dir / ".root_bundles_sharded").exists()


def test_dismissed_bundle_index_schema_mismatch_recreates_table(
    tmp_path: Path,
) -> None:
    """Opening an older dismissed archive index schema rebuilds the table."""
    bundles_dir = tmp_path / "bundles"
    bundles_dir.mkdir()
    index_path = bundles_dir / "index.sqlite"
    with sqlite3.connect(index_path) as conn:
        conn.execute(
            "CREATE TABLE dismissed_bundle_index_meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO dismissed_bundle_index_meta(key, value) "
            "VALUES ('schema_version', '0')"
        )
        conn.execute(
            "CREATE TABLE dismissed_bundle_summaries "
            "(bundle_path TEXT PRIMARY KEY, raw_suffix TEXT NOT NULL)"
        )

    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(cl_name="indexed_cl", raw_suffix="20250615100000")
        save_dismissed_bundle(agent)
        summaries = load_dismissed_bundle_summaries(cl_name="indexed_cl")

    assert [summary.raw_suffix for summary in summaries] == ["20250615100000"]


def test_indexed_suffix_load_avoids_scanning_unrelated_children(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Targeted bundle loading uses indexed paths when the index is available."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        target = make_agent(cl_name="target", raw_suffix="20250615100000")
        unrelated = make_agent(cl_name="other", raw_suffix="20250615110000")
        save_dismissed_bundle(target)
        save_dismissed_bundle(unrelated)
        rebuild_dismissed_bundle_index()

        def fail_scan(*args, **kwargs):
            raise AssertionError("fallback scan should not be used")

        monkeypatch.setattr("sase.ace.dismissed_agents._iter_bundle_paths", fail_scan)
        loaded = load_dismissed_bundles({"20250615100000"})

        assert [agent.identity for agent in loaded] == [target.identity]


def test_dismissed_bundle_index_remove_and_verify(tmp_path: Path) -> None:
    """Removing bundles deletes matching index rows and verify reports clean."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(cl_name="delete_me", raw_suffix="20250615100000")
        save_dismissed_bundle(agent)
        assert load_dismissed_bundle_summaries(suffixes={"20250615100000"})

        assert remove_bundle_by_identity(agent.identity)
        assert load_dismissed_bundle_summaries(suffixes={"20250615100000"}) == []
        assert verify_dismissed_bundle_index()["ok"] is True


def test_dismissed_bundle_verify_reports_fts_orphans(tmp_path: Path) -> None:
    """Verify+ catches FTS rows that no longer have summary rows."""
    bundles_dir = tmp_path / "bundles"
    with (
        patch("sase.ace.dismissed_agents._DISMISSED_BUNDLES_DIR", bundles_dir),
        patch("sase.ace.dismissed_agents._OLD_BUNDLES_FILE", tmp_path / "old.json"),
    ):
        agent = make_agent(cl_name="indexed_cl", raw_suffix="20250615100000")
        save_dismissed_bundle(agent)
        rebuild_dismissed_bundle_index()
        with sqlite3.connect(bundles_dir / "index.sqlite") as conn:
            conn.execute(
                "INSERT INTO dismissed_bundle_search_fts"
                "(bundle_path, archive_search_text) VALUES (?, ?)",
                ("/tmp/orphan-bundle.json", "orphan"),
            )

        result = verify_dismissed_bundle_index()

    assert result["ok"] is False
    assert result["fts_orphan_rows"] == 1
