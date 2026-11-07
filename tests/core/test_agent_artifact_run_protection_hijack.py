"""ACE-run retention protects runs an unresolved Agent Hijack still needs."""

from __future__ import annotations

import json
from pathlib import Path

from sase._repo_inventory_models import RepoInventory
from sase.agent.hijack.ledger import (
    create_record,
    hijack_record_path,
    new_requested_record,
)
import sase.core.agent_artifact_run_protection as protection


def _artifacts_dir(projects_root: Path, timestamp: str) -> Path:
    return (
        projects_root
        / "proj"
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )


def _write_settled(hijack_id: str, artifacts_dir: Path, state: str) -> None:
    record = new_requested_record(
        hijack_id=hijack_id, agent_name=hijack_id, artifacts_dir=str(artifacts_dir)
    )
    record["state"] = state
    path = hijack_record_path(hijack_id, settled=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record), encoding="utf-8")


def test_unresolved_hijacks_protect_their_runs(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    held = _artifacts_dir(projects_root, "20260101000000")
    expired = _artifacts_dir(projects_root, "20260102000000")
    dismissed = _artifacts_dir(projects_root, "20260103000000")
    create_record(
        new_requested_record(
            hijack_id="held-hijack", agent_name="held", artifacts_dir=str(held)
        )
    )
    _write_settled("expired-hijack", expired, "expired")
    _write_settled("dismissed-hijack", dismissed, "dismissed")

    snapshot = protection.collect_ace_run_retention_protections(
        projects_root=projects_root,
        artifact_index_path=tmp_path / "missing.sqlite",
        inventory=RepoInventory(()),
    )

    assert str(held.resolve(strict=False)) in snapshot.protected_dirs
    assert str(expired.resolve(strict=False)) in snapshot.protected_dirs
    assert str(dismissed.resolve(strict=False)) not in snapshot.protected_dirs
    assert {"20260101000000", "20260102000000"} <= snapshot.protected_timestamps
    assert "20260103000000" not in snapshot.protected_timestamps
