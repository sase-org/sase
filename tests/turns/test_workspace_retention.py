"""Adapter tests for terminal workspace-retention settlement."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_git_status import dirty_path_fingerprints
from sase.running_field import WorkspaceClaim, get_claimed_workspaces
from sase.turns.workspace_retention import (
    RETENTION_RECORD_LOCATOR,
    WorkspaceRetentionOwner,
    WorkspaceRetentionRepo,
    WorkspaceRetentionSuccessor,
    settle_stranded_workspace,
)
from sase.workspace_provider.occupant import (
    OccupantRecord,
    read_occupant_record,
    write_occupant_record,
)
from tests._running_field_helpers import create_project_file_with_running

_WORKFLOW = "ace(run)-260101_000000"
_CL_NAME = "feature"
_TIMESTAMP = "20260101000000"
_PID = 111
_WORKSPACE = 17


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(
    path: Path,
    *,
    tracked_dirty: bool = False,
    untracked: bool = False,
    staged: bool = False,
) -> Path:
    path.mkdir(parents=True)
    _git(path, "init")
    _git(path, "config", "user.email", "sase-test@example.invalid")
    _git(path, "config", "user.name", "SASE Test")
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-m", "init")
    if tracked_dirty:
        (path / "tracked.txt").write_text("session owned\n", encoding="utf-8")
    if untracked:
        (path / "untracked.txt").write_text("new file\n", encoding="utf-8")
    if staged:
        (path / "staged.txt").write_text("staged\n", encoding="utf-8")
        _git(path, "add", "staged.txt")
    return path


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


def _write_empty_baseline(artifacts: Path, repo_id: str, repo: Path) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
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
                "fingerprints": {},
            }
        ],
    }
    (artifacts / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _claim() -> WorkspaceClaim:
    return WorkspaceClaim(
        _WORKSPACE,
        _WORKFLOW,
        _CL_NAME,
        pid=_PID,
        artifacts_timestamp=_TIMESTAMP,
    )


def _owner(
    project_file: str,
    checkout: Path,
    artifacts: Path,
    *,
    repos: tuple[WorkspaceRetentionRepo, ...] | None = None,
) -> WorkspaceRetentionOwner:
    return WorkspaceRetentionOwner(
        project_file=project_file,
        workspace_num=_WORKSPACE,
        workflow=_WORKFLOW,
        cl_name=_CL_NAME,
        artifacts_timestamp=_TIMESTAMP,
        pid=_PID,
        artifacts_dir=str(artifacts),
        checkout_dir=str(checkout),
        repos=repos
        or (
            WorkspaceRetentionRepo(
                repo_id="primary",
                path=str(checkout),
                is_primary=True,
                positive_custody=True,
            ),
        ),
        terminal_reason="stopped",
        session_id="sess-1",
        turn_id="turn-1",
    )


def _occupant(checkout: Path) -> None:
    write_occupant_record(
        str(checkout),
        OccupantRecord(
            pid=_PID,
            workflow=_WORKFLOW,
            project="sase",
            workspace_num=_WORKSPACE,
            artifacts_timestamp=_TIMESTAMP,
            cl_name=_CL_NAME,
            claimed_at=1.0,
        ),
    )


def test_session_owned_dirt_pins_and_persists_record(tmp_path: Path) -> None:
    checkout = _init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [_claim()])

    result = settle_stranded_workspace(_owner(project_file, checkout, artifacts))

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


def test_proven_clean_releases_claim(tmp_path: Path) -> None:
    checkout = _init_repo(tmp_path / "ws")
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [_claim()])

    result = settle_stranded_workspace(_owner(project_file, checkout, artifacts))

    assert result.disposition == "release"
    assert result.reason == "proven_clean"
    assert get_claimed_workspaces(project_file) == []


def test_unchanged_foreign_dirt_releases(tmp_path: Path) -> None:
    checkout = _init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    _write_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [_claim()])

    result = settle_stranded_workspace(_owner(project_file, checkout, artifacts))

    assert result.disposition == "release"
    assert result.reason == "proven_clean"
    assert get_claimed_workspaces(project_file) == []
    assert (checkout / "tracked.txt").read_text(encoding="utf-8") == "session owned\n"


def test_primary_clean_linked_dirty_retains(tmp_path: Path) -> None:
    primary = _init_repo(tmp_path / "primary")
    linked = _init_repo(tmp_path / "linked", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "linked", linked)
    project_file = create_project_file_with_running(tmp_path, [_claim()])
    owner = _owner(
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

    result = settle_stranded_workspace(owner)

    assert result.disposition == "retain"
    assert result.reason == "session_owned_dirt"
    assert get_claimed_workspaces(project_file)[0].pinned is True
    payload = json.loads(Path(result.record_path or "").read_text(encoding="utf-8"))
    assert payload["affected_repo_ids"] == ["linked"]


def test_same_workspace_successor_releases_without_hold(tmp_path: Path) -> None:
    checkout = _init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [_claim()])

    result = settle_stranded_workspace(
        _owner(project_file, checkout, artifacts),
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
    checkout = _init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [_claim()])

    result = settle_stranded_workspace(
        _owner(project_file, checkout, artifacts),
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
    checkout = _init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [_claim()])

    result = settle_stranded_workspace(
        _owner(project_file, checkout, artifacts),
        successor=WorkspaceRetentionSuccessor(
            confirmed_active=False,
            same_workspace=True,
            inherited_obligations=True,
        ),
    )

    assert result.disposition == "retain"
    assert result.reason == "session_owned_dirt"


def test_claim_transfer_racing_settlement_is_noop(tmp_path: Path) -> None:
    checkout = _init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "primary", checkout)
    foreign = WorkspaceClaim(
        _WORKSPACE,
        _WORKFLOW,
        _CL_NAME,
        pid=999,
        artifacts_timestamp="20260101999999",
    )
    project_file = create_project_file_with_running(tmp_path, [foreign])
    _occupant(checkout)

    result = settle_stranded_workspace(_owner(project_file, checkout, artifacts))

    assert result.disposition == "ownership_moved"
    assert result.stale_attempt is True
    assert result.claim_changed is False
    claims = get_claimed_workspaces(project_file)
    assert claims[0].pid == 999
    assert claims[0].pinned is False
    occupant = read_occupant_record(str(checkout))
    assert occupant is not None
    assert occupant.pid == _PID


def test_missing_baseline_with_custody_retains(tmp_path: Path) -> None:
    checkout = _init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    project_file = create_project_file_with_running(tmp_path, [_claim()])

    result = settle_stranded_workspace(_owner(project_file, checkout, artifacts))

    assert result.disposition == "retain"
    assert result.reason == "missing_baseline_with_custody"
    assert get_claimed_workspaces(project_file)[0].pinned is True


def test_probe_failure_retains_and_is_not_clean(tmp_path: Path) -> None:
    checkout = tmp_path / "not-a-repo"
    checkout.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    project_file = create_project_file_with_running(tmp_path, [_claim()])

    result = settle_stranded_workspace(_owner(project_file, checkout, artifacts))

    assert result.disposition == "retain"
    assert result.reason == "evidence_unavailable"
    assert result.probe_errors
    assert get_claimed_workspaces(project_file)[0].pinned is True


def test_staged_and_untracked_edits_retain(tmp_path: Path) -> None:
    checkout = _init_repo(tmp_path / "ws", untracked=True, staged=True)
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [_claim()])

    result = settle_stranded_workspace(_owner(project_file, checkout, artifacts))

    assert result.disposition == "retain"
    assert result.reason == "session_owned_dirt"
    assert (checkout / "staged.txt").is_file()
    assert (checkout / "untracked.txt").is_file()
    assert get_claimed_workspaces(project_file)[0].pinned is True


def test_repeated_hold_is_idempotent(tmp_path: Path) -> None:
    checkout = _init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [_claim()])
    owner = _owner(project_file, checkout, artifacts)

    first = settle_stranded_workspace(owner)
    second = settle_stranded_workspace(owner)

    assert first.disposition == "retain"
    assert second.disposition == "retain"
    claims = get_claimed_workspaces(project_file)
    assert len(claims) == 1
    assert claims[0].pinned is True
    assert claims[0].pid == _PID


def test_creator_restored_releases_even_when_dirty(tmp_path: Path) -> None:
    checkout = _init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [_claim()])
    _occupant(checkout)

    result = settle_stranded_workspace(
        _owner(project_file, checkout, artifacts),
        creator_restored=True,
    )

    assert result.disposition == "release"
    assert result.reason == "creator_restored"
    assert get_claimed_workspaces(project_file) == []
    assert read_occupant_record(str(checkout)) is None


def test_gate_released_workspace_does_not_reacquire(tmp_path: Path) -> None:
    checkout = _init_repo(tmp_path / "ws", tracked_dirty=True)
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [])

    result = settle_stranded_workspace(
        _owner(project_file, checkout, artifacts),
        gate_released_workspace=True,
    )

    assert result.disposition == "ownership_moved"
    assert result.reason == "gate_released_workspace"
    assert result.stale_attempt is True
    assert get_claimed_workspaces(project_file) == []


def test_successful_release_clears_matching_occupant(tmp_path: Path) -> None:
    checkout = _init_repo(tmp_path / "ws")
    artifacts = tmp_path / "artifacts"
    _write_empty_baseline(artifacts, "primary", checkout)
    project_file = create_project_file_with_running(tmp_path, [_claim()])
    _occupant(checkout)

    result = settle_stranded_workspace(_owner(project_file, checkout, artifacts))

    assert result.disposition == "release"
    assert read_occupant_record(str(checkout)) is None
