"""Retain-versus-release policy tests for terminal workspace retention.

Split from ``tests.turns.test_workspace_retention``; the original module
re-exports these tests so its import path keeps working.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_git_status import dirty_path_fingerprints
from sase.running_field import get_claimed_workspaces
from sase.turns.workspace_retention import (
    RETENTION_RECORD_LOCATOR,
    WorkspaceRetentionRepo,
    WorkspaceRetentionSuccessor,
    settle_stranded_workspace,
)
from sase.workspace_provider.occupant import read_occupant_record
from tests._running_field_helpers import create_project_file_with_running
from tests.turns._workspace_retention_helpers import (
    PID,
    TIMESTAMP,
    claim,
    init_repo,
    occupant,
    owner,
    write_empty_baseline,
)

__all__ = [
    "test_creator_restored_releases_even_when_dirty",
    "test_different_workspace_successor_retains_original",
    "test_gate_released_workspace_does_not_reacquire",
    "test_historical_carried_to_does_not_count_as_successor",
    "test_late_retention_publishes_recovery_notification",
    "test_missing_baseline_with_custody_retains",
    "test_primary_clean_linked_dirty_retains",
    "test_probe_failure_retains_and_is_not_clean",
    "test_proven_clean_releases_claim",
    "test_repeated_hold_is_idempotent",
    "test_same_workspace_successor_releases_without_hold",
    "test_session_owned_dirt_pins_and_persists_record",
    "test_staged_and_untracked_edits_retain",
    "test_unchanged_foreign_dirt_releases",
]


def _write_baseline(artifacts: Path, repo_id: str, repo: Path) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    fingerprints = {
        path: list(fingerprint)
        for path, fingerprint in dirty_path_fingerprints(str(repo)).items()
    }
    payload = {
        "schema_version": 1,
        "repositories": [
            {
                "repo_id": repo_id,
                "path": normalize_path(str(repo)),
                "kind": "primary" if repo_id == "primary" else "linked",
                "name": repo_id,
                "scope": "run_start",
                "captured_at": "2026-01-01T00:00:00+00:00",
                "fingerprints": fingerprints,
            }
        ],
    }
    (artifacts / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_session_owned_dirt_pins_and_persists_record(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])

    result = settle_stranded_workspace(owner(project_file, checkout, artifacts))

    assert result.disposition == "retain"
    assert result.reason == "session_owned_dirt"
    assert result.claim_changed is True
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    record_path = Path(result.record_path or "")
    assert record_path == artifacts / RETENTION_RECORD_LOCATOR
    payload = json.loads(record_path.read_text(encoding="utf-8"))
    assert payload["disposition"] == "retain"
    assert payload["policy_reason"] == "session_owned_dirt"
    assert payload["affected_repo_ids"] == ["primary"]
    assert result.snapshot_paths
    assert Path(result.snapshot_paths[0]).is_file()
    assert (checkout / "tracked.txt").read_text(encoding="utf-8") == "session owned\n"


def test_late_retention_publishes_recovery_notification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    from sase.notifications.store import load_notifications

    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    held_owner = owner(project_file, checkout, artifacts)
    held_owner = replace(held_owner, notify_on_retain=True)

    result = settle_stranded_workspace(held_owner)

    assert result.disposition == "retain"
    rows = load_notifications()
    assert len(rows) == 1
    assert "Workspace held: stranded work" in rows[0].notes
    assert rows[0].action == "JumpToAgent"
    assert rows[0].action_data["raw_suffix"] == TIMESTAMP

    repeat = settle_stranded_workspace(held_owner)

    assert repeat.disposition == "retain"
    assert len(load_notifications()) == 1


def test_proven_clean_releases_claim(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws")
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])

    result = settle_stranded_workspace(owner(project_file, checkout, artifacts))

    assert result.disposition == "release"
    assert result.reason == "proven_clean"
    assert get_claimed_workspaces(project_file) == []


def test_unchanged_foreign_dirt_releases(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    _write_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])

    result = settle_stranded_workspace(owner(project_file, checkout, artifacts))

    assert result.disposition == "release"
    assert result.reason == "proven_clean"
    assert get_claimed_workspaces(project_file) == []
    assert (checkout / "tracked.txt").read_text(encoding="utf-8") == "session owned\n"


def test_primary_clean_linked_dirty_retains(tmp_path: Path) -> None:
    primary = init_repo(tmp_path / "primary")
    linked = init_repo(tmp_path / "linked", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "linked", linked)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    held_owner = owner(
        project_file,
        primary,
        artifacts,
        repos=(
            WorkspaceRetentionRepo(
                repo_id="primary",
                path=str(primary),
                is_primary=True,
                positive_custody=True,
            ),
            WorkspaceRetentionRepo(
                repo_id="linked",
                path=str(linked),
                positive_custody=True,
            ),
        ),
    )

    result = settle_stranded_workspace(held_owner)

    assert result.disposition == "retain"
    assert result.reason == "session_owned_dirt"
    assert get_claimed_workspaces(project_file)[0].pinned is True
    payload = json.loads(Path(result.record_path or "").read_text(encoding="utf-8"))
    assert payload["affected_repo_ids"] == ["linked"]


def test_same_workspace_successor_releases_without_hold(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])

    result = settle_stranded_workspace(
        owner(project_file, checkout, artifacts),
        successor=WorkspaceRetentionSuccessor(
            confirmed_active=True,
            same_workspace=True,
            inherited_obligations=True,
        ),
    )

    assert result.disposition == "release"
    assert result.reason == "same_workspace_successor"
    assert get_claimed_workspaces(project_file) == []


def test_different_workspace_successor_retains_original(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])

    result = settle_stranded_workspace(
        owner(project_file, checkout, artifacts),
        successor=WorkspaceRetentionSuccessor(
            confirmed_active=True,
            same_workspace=False,
            inherited_obligations=True,
        ),
    )

    assert result.disposition == "retain"
    assert result.reason == "session_owned_dirt"
    assert get_claimed_workspaces(project_file)[0].pinned is True


def test_historical_carried_to_does_not_count_as_successor(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])

    result = settle_stranded_workspace(
        owner(project_file, checkout, artifacts),
        successor=WorkspaceRetentionSuccessor(
            confirmed_active=False,
            same_workspace=True,
            inherited_obligations=True,
        ),
    )

    assert result.disposition == "retain"
    assert result.reason == "session_owned_dirt"


def test_missing_baseline_with_custody_retains(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    project_file = create_project_file_with_running(tmp_path, [claim()])

    result = settle_stranded_workspace(owner(project_file, checkout, artifacts))

    assert result.disposition == "retain"
    assert result.reason == "missing_baseline_with_custody"
    assert get_claimed_workspaces(project_file)[0].pinned is True


def test_probe_failure_retains_and_is_not_clean(tmp_path: Path) -> None:
    checkout = tmp_path / "not-a-repo"
    checkout.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    project_file = create_project_file_with_running(tmp_path, [claim()])

    result = settle_stranded_workspace(owner(project_file, checkout, artifacts))

    assert result.disposition == "retain"
    assert result.reason == "evidence_unavailable"
    assert result.probe_errors
    assert get_claimed_workspaces(project_file)[0].pinned is True


def test_staged_and_untracked_edits_retain(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", untracked=True, staged=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])

    result = settle_stranded_workspace(owner(project_file, checkout, artifacts))

    assert result.disposition == "retain"
    assert result.reason == "session_owned_dirt"
    assert (checkout / "staged.txt").is_file()
    assert (checkout / "untracked.txt").is_file()
    assert get_claimed_workspaces(project_file)[0].pinned is True


def test_repeated_hold_is_idempotent(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    held_owner = owner(project_file, checkout, artifacts)

    first = settle_stranded_workspace(held_owner)
    second = settle_stranded_workspace(held_owner)

    assert first.disposition == "retain"
    assert second.disposition == "retain"
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert claims[0].pid == PID


def test_creator_restored_releases_even_when_dirty(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [claim()])
    occupant(checkout)

    result = settle_stranded_workspace(
        owner(project_file, checkout, artifacts),
        creator_restored=True,
    )

    assert result.disposition == "release"
    assert result.reason == "creator_restored"
    assert get_claimed_workspaces(project_file) == []
    assert read_occupant_record(str(checkout)) is None


def test_gate_released_workspace_does_not_reacquire(tmp_path: Path) -> None:
    checkout = init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [])

    result = settle_stranded_workspace(
        owner(project_file, checkout, artifacts),
        gate_released_workspace=True,
    )

    assert result.disposition == "ownership_moved"
    assert result.reason == "gate_released_workspace"
    assert result.stale_attempt is True
    assert get_claimed_workspaces(project_file) == []
