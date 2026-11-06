"""Facade tests for journaled ACE-run trash, including purge protections."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from sase.core.agent_artifact_run_retention import (
    AceRunRetentionPolicy,
    plan_ace_run_retention,
)
from sase.core.agent_artifact_run_retention_models import AceRunProtectionSnapshot
from sase.core.agent_artifact_run_trash import (
    AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
    list_ace_run_trash,
    purge_ace_run_trash,
    quarantine_ace_runs,
)


def _terminal_run(projects_root: Path, timestamp: str) -> Path:
    path = (
        projects_root
        / "demo"
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    path.mkdir(parents=True)
    (path / "done.json").write_text('{"outcome":"completed"}', encoding="utf-8")
    (path / "payload.txt").write_text(f"run {timestamp}\n", encoding="utf-8")
    return path


def test_list_preserves_orphan_original_path(tmp_path: Path) -> None:
    trash_root = tmp_path / "trash"
    timestamp = "20200101000000"
    orphan = trash_root / "crash" / "runs" / "demo" / "202001" / "01" / timestamp
    orphan.mkdir(parents=True)
    (orphan / "done.json").write_text("{}\n", encoding="utf-8")
    (orphan / "payload.txt").write_text("orphan\n", encoding="utf-8")
    (trash_root / "crash" / "journal.jsonl").write_text(
        json.dumps(
            {
                "kind": "header",
                "schema_version": AGENT_ARTIFACT_RUN_TRASH_WIRE_SCHEMA_VERSION,
                "batch_id": "crash",
                "created_at": "2026-02-01T00:00:00Z",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    listed = list_ace_run_trash(trash_root)
    assert listed.batches[0].orphan_items[0].timestamp == timestamp
    assert (
        listed.batches[0].orphan_items[0].original_path
        == f"demo/artifacts/ace-run/202001/01/{timestamp}"
    )


def test_purge_restores_run_newly_protected_by_live_successor(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    trash_root = tmp_path / "trash"
    old = _terminal_run(projects_root, "20200101000000")
    (old / "agent_meta.json").write_text(
        json.dumps({"continuation_node_id": "parent1"}),
        encoding="utf-8",
    )
    expected = (old / "payload.txt").read_bytes()
    policy = AceRunRetentionPolicy(
        now=datetime(2026, 11, 5, tzinfo=UTC),
        keep_recent_months=2,
        projects_root=projects_root,
    )
    plan = plan_ace_run_retention(policy, protections=AceRunProtectionSnapshot())
    quarantined = quarantine_ace_runs(
        plan,
        AceRunProtectionSnapshot(),
        trash_root=trash_root,
    )
    assert quarantined.quarantined == 1
    assert not old.exists()

    live = _terminal_run(projects_root, "20261105000000")
    (live / "running.json").write_text("{}\n", encoding="utf-8")
    (live / "agent_meta.json").write_text(
        json.dumps(
            {
                "continuation_node_id": "child1",
                "continuation_parent_node_id": "parent1",
            }
        ),
        encoding="utf-8",
    )

    purged = purge_ace_run_trash(
        AceRunProtectionSnapshot(),
        purge_all=True,
        projects_root=projects_root,
        trash_root=trash_root,
    )
    assert purged.blocked_reason is None
    assert purged.restored == 1
    assert old.exists()
    assert (old / "payload.txt").read_bytes() == expected
    assert any("continuation_ancestry" in item.reasons for item in purged.items)


def test_purge_passes_agent_and_bead_protections(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    trash_root = tmp_path / "trash"
    old = _terminal_run(projects_root, "20200101000000")
    (old / "agent_meta.json").write_text(
        json.dumps({"name": "keeper", "bead_id": "sase-open"}),
        encoding="utf-8",
    )
    policy = AceRunRetentionPolicy(
        now=datetime(2026, 11, 5, tzinfo=UTC),
        keep_recent_months=2,
        projects_root=projects_root,
    )
    plan = plan_ace_run_retention(policy, protections=AceRunProtectionSnapshot())
    assert (
        quarantine_ace_runs(
            plan, AceRunProtectionSnapshot(), trash_root=trash_root
        ).quarantined
        == 1
    )

    purged = purge_ace_run_trash(
        AceRunProtectionSnapshot(
            protected_agent_names=frozenset({"keeper"}),
            non_closed_bead_ids_by_project={"demo": frozenset({"sase-open"})},
        ),
        purge_all=True,
        projects_root=projects_root,
        trash_root=trash_root,
    )
    assert purged.restored == 1
    assert old.exists()
    reasons = [reason for item in purged.items for reason in item.reasons]
    assert "referenced_agent" in reasons
    assert "non_closed_bead" in reasons
