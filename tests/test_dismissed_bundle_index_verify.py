"""Verify and identity tests for dismissed bundle indexing.

Split from ``tests.test_dismissed_bundle_index``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.dismissed_agents import (
    dismissed_bundle_identities_snapshot,
    dismissed_bundle_index_signature,
    load_dismissed_bundle_identities,
    load_dismissed_bundle_summaries,
    rebuild_dismissed_bundle_index,
    save_dismissed_bundle,
    verify_dismissed_bundle_index,
)
from sase.ace.dismissed_bundle_index import (
    query_summary_identities,
    rebuild_index,
)
from sase.ace.tui.models.agent import AgentType
from tests._dismissed_agents_helpers import make_agent

__all__ = [
    "test_dismissed_bundle_identities_snapshot_reuses_unchanged_signature",
    "test_dismissed_bundle_identity_query_missing_and_schema_less_are_read_only",
    "test_dismissed_bundle_identity_snapshot_real_index_is_read_only",
    "test_dismissed_bundle_verify_detects_changed_file_signature",
    "test_dismissed_bundle_verify_reports_stale_and_missing_rows",
    "test_dismissed_bundle_verify_skips_json_parse_of_indexed_bundles",
    "test_dismissed_bundle_verify_treats_unindexed_corrupt_file_as_corrupt",
    "test_load_dismissed_bundle_identities_matches_summary_projection",
]


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
        second = dismissed_bundle_identities_snapshot()

    assert isinstance(first, frozenset)
    # Repeated hits share the cached frozenset instead of fresh copies.
    assert second is first
    # Caller mutation fails loudly instead of corrupting the cache.
    with pytest.raises(AttributeError):
        first.add((AgentType.RUNNING, "indexed_cl", "20250615110000"))  # type: ignore[attr-defined]
    assert second == {
        (AgentType.RUNNING, "indexed_cl", "20250615110000"),
    }
    query.assert_called_once()


def test_dismissed_bundle_identity_snapshot_real_index_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real index keeps its signature and hits the identity cache on repeat."""
    import sase.ace.dismissed_agents as dismissed_agents

    bundles_dir = tmp_path / "bundles"
    monkeypatch.setattr(dismissed_agents, "_DISMISSED_BUNDLES_DIR", bundles_dir)
    monkeypatch.setattr(
        dismissed_agents, "_dismissed_bundle_identities_snapshot_initialized", False
    )
    monkeypatch.setattr(
        dismissed_agents, "_dismissed_bundle_identities_snapshot_signature", None
    )
    monkeypatch.setattr(
        dismissed_agents, "_dismissed_bundle_identities_snapshot_cache", frozenset()
    )
    rebuild_index(bundles_dir)
    signature_before = dismissed_bundle_index_signature()

    with patch(
        "sase.ace.dismissed_bundle_index.query_summary_identities",
        wraps=query_summary_identities,
    ) as query:
        first = dismissed_bundle_identities_snapshot()
        second = dismissed_bundle_identities_snapshot()

    assert first is second
    assert query.call_count == 1
    assert dismissed_bundle_index_signature() == signature_before


def test_dismissed_bundle_identity_query_missing_and_schema_less_are_read_only(
    tmp_path: Path,
) -> None:
    from sase.ace.dismissed_bundle_index import INDEX_FILENAME

    bundles_dir = tmp_path / "bundles"
    assert query_summary_identities(bundles_dir) is None
    assert not (bundles_dir / INDEX_FILENAME).exists()

    bundles_dir.mkdir()
    db_path = bundles_dir / INDEX_FILENAME
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE dismissed_bundle_index_meta "
            "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO dismissed_bundle_index_meta VALUES ('schema_version', '1')"
        )
        conn.execute("CREATE TABLE legacy_data (value TEXT)")
        conn.execute("INSERT INTO legacy_data VALUES ('keep')")
    mtime_before = db_path.stat().st_mtime_ns

    assert query_summary_identities(bundles_dir) is None

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT value FROM legacy_data").fetchone() == ("keep",)
        assert (
            conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'dismissed_bundle_summaries'"
            ).fetchone()
            is None
        )
    assert db_path.stat().st_mtime_ns == mtime_before
