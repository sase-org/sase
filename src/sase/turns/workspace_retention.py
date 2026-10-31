"""Shared settlement adapter for terminal workspace retention.

Python collects workspace/repository evidence and applies the Rust-selected
effect. Classification stays in ``sase_core``; this module never substitutes
a Python policy fallback.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.atomic_json import write_json_marker_atomic
from sase.core.workspace_retention import (
    DISPOSITION_OWNERSHIP_MOVED,
    DISPOSITION_RELEASE,
    DISPOSITION_RETAIN,
    WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION,
    decide_workspace_retention,
)
from sase.llm_provider.commit_finalizer_baseline import (
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_git_status import (
    changed_files_from_git_status,
    split_pre_existing_changed_files,
)
from sase.monitor.worktree_recovery import snapshot_owner_worktree_diffs
from sase.running_field import hold_workspace_claim, release_workspace
from sase.workspace_provider.occupant import clear_owned_occupant_record

RETENTION_RECORD_LOCATOR = "diagnostics/workspace_retention.json"
RETENTION_META_FIELD = "workspace_retention_record_path"
_GIT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True, slots=True)
class WorkspaceRetentionRepo:
    """One relevant repository belonging to the settling owner."""

    repo_id: str
    path: str
    is_primary: bool = False
    positive_custody: bool = False


@dataclass(frozen=True, slots=True)
class WorkspaceRetentionOwner:
    """Exact claim and checkout being relinquished."""

    project_file: str
    workspace_num: int
    workflow: str
    cl_name: str
    artifacts_timestamp: str
    pid: int
    artifacts_dir: str
    checkout_dir: str | None = None
    repos: tuple[WorkspaceRetentionRepo, ...] = ()
    origin_repo_ids: tuple[str, ...] = ()
    staged_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    terminal_reason: str = ""


@dataclass(frozen=True, slots=True)
class WorkspaceRetentionSuccessor:
    """Confirmed successor custody for the workspace being settled."""

    confirmed_active: bool = False
    same_workspace: bool = False
    inherited_obligations: bool = False


@dataclass(frozen=True, slots=True)
class WorkspaceRetentionResult:
    """Effect applied for one settlement attempt."""

    disposition: str
    reason: str
    record_path: str | None = None
    claim_changed: bool = False
    snapshot_paths: tuple[str, ...] = ()
    probe_errors: tuple[str, ...] = ()
    stale_attempt: bool = False


def settle_stranded_workspace(
    owner: WorkspaceRetentionOwner,
    *,
    successor: WorkspaceRetentionSuccessor | None = None,
    creator_restored: bool = False,
    gate_released_workspace: bool = False,
) -> WorkspaceRetentionResult:
    """Collect evidence, classify through Rust, and apply the selected effect."""
    successor = successor or WorkspaceRetentionSuccessor()
    observed = _observed_claim(owner)
    dirt, probe_errors, affected_repo_ids = _collect_dirt(owner)
    decision = decide_workspace_retention(
        {
            "schema_version": WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION,
            "expected_claim": _claim_wire(owner),
            "observed_claim": observed,
            "successor": {
                "confirmed_active": successor.confirmed_active,
                "same_workspace": successor.same_workspace,
                "inherited_obligations": successor.inherited_obligations,
            },
            "creator_restored": creator_restored,
            "gate_released_workspace": gate_released_workspace,
            "dirt": dirt,
            "probe_failed": bool(probe_errors),
        }
    )
    disposition = str(decision.get("disposition") or "")
    reason = str(decision.get("reason") or "")

    if disposition == DISPOSITION_RETAIN:
        return _apply_retain(
            owner,
            reason=reason,
            affected_repo_ids=affected_repo_ids,
            probe_errors=probe_errors,
        )
    if disposition == DISPOSITION_RELEASE:
        return _apply_release(owner, reason=reason, probe_errors=probe_errors)
    return _apply_ownership_moved(
        owner,
        reason=reason,
        affected_repo_ids=affected_repo_ids,
        probe_errors=probe_errors,
    )


def _claim_wire(owner: WorkspaceRetentionOwner) -> dict[str, Any]:
    return {
        "workspace_num": owner.workspace_num,
        "workflow": owner.workflow,
        "cl_name": owner.cl_name or "",
        "artifacts_timestamp": owner.artifacts_timestamp or "",
        "pid": owner.pid,
    }


def _observed_claim(owner: WorkspaceRetentionOwner) -> dict[str, Any] | None:
    from sase.running_field import get_claimed_workspaces

    try:
        claims = get_claimed_workspaces(owner.project_file)
    except OSError:
        return None
    for claim in claims:
        if (
            claim.workspace_num == owner.workspace_num
            and claim.workflow == owner.workflow
            and (claim.cl_name or "") == (owner.cl_name or "")
            and (claim.artifacts_timestamp or "") == (owner.artifacts_timestamp or "")
            and claim.pid == owner.pid
        ):
            return {
                "workspace_num": claim.workspace_num,
                "workflow": claim.workflow,
                "cl_name": claim.cl_name or "",
                "artifacts_timestamp": claim.artifacts_timestamp or "",
                "pid": claim.pid,
            }
    return None


def _collect_dirt(
    owner: WorkspaceRetentionOwner,
) -> tuple[dict[str, bool], tuple[str, ...], tuple[str, ...]]:
    repos = _relevant_repos(owner)
    session_owned = False
    only_unchanged_foreign = False
    saw_unchanged_foreign = False
    saw_dirty = False
    all_proven_clean = True
    missing_baseline = False
    positive_custody = False
    probe_errors: list[str] = []
    affected: list[str] = []
    baselines = _baseline_by_path(owner.artifacts_dir)

    if not repos:
        return (
            {
                "session_owned": False,
                "only_unchanged_foreign": False,
                "all_proven_clean": True,
                "missing_baseline": False,
                "positive_custody": False,
            },
            (),
            (),
        )

    for repo in repos:
        if repo.positive_custody or repo.is_primary:
            positive_custody = True
        dirty_paths, error = _probe_dirty_paths(repo.path)
        if error is not None:
            probe_errors.append(f"{repo.repo_id}: {error}")
            all_proven_clean = False
            continue
        if not dirty_paths:
            continue
        saw_dirty = True
        all_proven_clean = False
        affected.append(repo.repo_id)
        baseline = baselines.get(normalize_path(repo.path))
        if baseline is None:
            missing_baseline = True
            continue
        still, pre_existing = split_pre_existing_changed_files(
            repo.path,
            dirty_paths,
            baseline,
        )
        if still:
            session_owned = True
        elif pre_existing:
            saw_unchanged_foreign = True

    if saw_unchanged_foreign and not session_owned:
        only_unchanged_foreign = True
    if not saw_dirty and not probe_errors:
        all_proven_clean = True

    return (
        {
            "session_owned": session_owned,
            "only_unchanged_foreign": only_unchanged_foreign,
            "all_proven_clean": all_proven_clean,
            "missing_baseline": missing_baseline,
            "positive_custody": positive_custody,
        },
        tuple(probe_errors),
        tuple(dict.fromkeys(affected)),
    )


def _relevant_repos(
    owner: WorkspaceRetentionOwner,
) -> tuple[WorkspaceRetentionRepo, ...]:
    if owner.repos:
        return owner.repos
    if owner.checkout_dir:
        return (
            WorkspaceRetentionRepo(
                repo_id="primary",
                path=owner.checkout_dir,
                is_primary=True,
                positive_custody=True,
            ),
        )
    return ()


def _baseline_by_path(
    artifacts_dir: str,
) -> dict[str, dict[str, tuple[str, str | None]]]:
    if not artifacts_dir:
        return {}
    records = load_finalizer_baseline_records(Path(artifacts_dir))
    if not records:
        return {}
    by_path: dict[str, dict[str, tuple[str, str | None]]] = {}
    for record in records:
        by_path[normalize_path(record.path)] = dict(record.fingerprints)
    return by_path


def _probe_dirty_paths(repo_path: str) -> tuple[list[str] | None, str | None]:
    import subprocess

    try:
        result = subprocess.run(
            [
                "git",
                "--no-optional-locks",
                "-C",
                repo_path,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    if result.returncode != 0:
        stderr = (
            result.stderr or ""
        ).strip() or f"git status exited {result.returncode}"
        return None, stderr
    return changed_files_from_git_status(result.stdout), None


def _apply_retain(
    owner: WorkspaceRetentionOwner,
    *,
    reason: str,
    affected_repo_ids: Sequence[str],
    probe_errors: Sequence[str],
) -> WorkspaceRetentionResult:
    checkouts = tuple((repo.repo_id, repo.path) for repo in _relevant_repos(owner))
    snapshot_paths = snapshot_owner_worktree_diffs(owner.artifacts_dir, checkouts)
    record_path = _persist_record(
        owner,
        disposition=DISPOSITION_RETAIN,
        reason=reason,
        affected_repo_ids=affected_repo_ids,
        snapshot_paths=snapshot_paths,
        probe_errors=probe_errors,
        stale_attempt=False,
    )
    hold = hold_workspace_claim(
        owner.project_file,
        owner.workspace_num,
        owner.workflow,
        owner.cl_name,
        owner.artifacts_timestamp,
        caller_tag="workspace-retention",
        expected_pid=owner.pid,
    )
    if not hold.success:
        record_path = _persist_record(
            owner,
            disposition=DISPOSITION_OWNERSHIP_MOVED,
            reason=hold.error or "claim_ownership_moved",
            affected_repo_ids=affected_repo_ids,
            snapshot_paths=snapshot_paths,
            probe_errors=probe_errors,
            stale_attempt=True,
        )
        return WorkspaceRetentionResult(
            disposition=DISPOSITION_OWNERSHIP_MOVED,
            reason=hold.error or "claim_ownership_moved",
            record_path=record_path,
            snapshot_paths=snapshot_paths,
            probe_errors=tuple(probe_errors),
            stale_attempt=True,
        )
    return WorkspaceRetentionResult(
        disposition=DISPOSITION_RETAIN,
        reason=reason,
        record_path=record_path,
        claim_changed=True,
        snapshot_paths=snapshot_paths,
        probe_errors=tuple(probe_errors),
    )


def _apply_release(
    owner: WorkspaceRetentionOwner,
    *,
    reason: str,
    probe_errors: Sequence[str],
) -> WorkspaceRetentionResult:
    released = release_workspace(
        owner.project_file,
        owner.workspace_num,
        owner.workflow,
        owner.cl_name,
        caller_tag="workspace-retention",
        expected_pid=owner.pid,
        artifacts_timestamp=owner.artifacts_timestamp,
    )
    if not released.success:
        return WorkspaceRetentionResult(
            disposition=DISPOSITION_OWNERSHIP_MOVED,
            reason=released.error or "claim_ownership_moved",
            probe_errors=tuple(probe_errors),
            stale_attempt=True,
        )
    if owner.checkout_dir:
        clear_owned_occupant_record(
            owner.checkout_dir,
            owner.pid,
            artifacts_timestamp=owner.artifacts_timestamp or None,
            workflow=owner.workflow,
            cl_name=owner.cl_name or None,
            workspace_num=owner.workspace_num,
        )
    return WorkspaceRetentionResult(
        disposition=DISPOSITION_RELEASE,
        reason=reason,
        claim_changed=True,
        probe_errors=tuple(probe_errors),
    )


def _apply_ownership_moved(
    owner: WorkspaceRetentionOwner,
    *,
    reason: str,
    affected_repo_ids: Sequence[str],
    probe_errors: Sequence[str],
) -> WorkspaceRetentionResult:
    record_path = _persist_record(
        owner,
        disposition=DISPOSITION_OWNERSHIP_MOVED,
        reason=reason,
        affected_repo_ids=affected_repo_ids,
        snapshot_paths=(),
        probe_errors=probe_errors,
        stale_attempt=True,
    )
    return WorkspaceRetentionResult(
        disposition=DISPOSITION_OWNERSHIP_MOVED,
        reason=reason,
        record_path=record_path,
        probe_errors=tuple(probe_errors),
        stale_attempt=True,
    )


def _persist_record(
    owner: WorkspaceRetentionOwner,
    *,
    disposition: str,
    reason: str,
    affected_repo_ids: Sequence[str],
    snapshot_paths: Sequence[str],
    probe_errors: Sequence[str],
    stale_attempt: bool,
) -> str | None:
    if not owner.artifacts_dir:
        return None
    payload: dict[str, object] = {
        "schema_version": WORKSPACE_RETENTION_WIRE_SCHEMA_VERSION,
        "kind": "terminal_workspace_retention",
        "workspace_num": owner.workspace_num,
        "project_file": owner.project_file,
        "workflow": owner.workflow,
        "cl_name": owner.cl_name,
        "artifacts_timestamp": owner.artifacts_timestamp,
        "pid": owner.pid,
        "artifacts_dir": owner.artifacts_dir,
        "session_id": owner.session_id,
        "turn_id": owner.turn_id,
        "origin_repo_ids": list(owner.origin_repo_ids),
        "staged_id": owner.staged_id,
        "terminal_reason": owner.terminal_reason,
        "disposition": disposition,
        "policy_reason": reason,
        "affected_repo_ids": list(affected_repo_ids),
        "snapshot_paths": list(snapshot_paths),
        "probe_errors": list(probe_errors),
        "stale_attempt": stale_attempt,
        "created_at": time.time(),
    }
    record_path = Path(owner.artifacts_dir) / RETENTION_RECORD_LOCATOR
    try:
        write_json_marker_atomic(record_path, payload)
    except OSError:
        return None
    _record_meta_path(owner.artifacts_dir, str(record_path))
    return str(record_path)


def _record_meta_path(artifacts_dir: str, record_path: str) -> None:
    from sase.axe.run_agent_helpers_artifacts import update_meta_field

    if not (Path(artifacts_dir) / "agent_meta.json").is_file():
        return
    update_meta_field(artifacts_dir, RETENTION_META_FIELD, record_path)


__all__ = [
    "RETENTION_META_FIELD",
    "RETENTION_RECORD_LOCATOR",
    "WorkspaceRetentionOwner",
    "WorkspaceRetentionRepo",
    "WorkspaceRetentionResult",
    "WorkspaceRetentionSuccessor",
    "settle_stranded_workspace",
]
