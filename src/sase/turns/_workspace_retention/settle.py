"""Collect evidence, classify through Rust, and apply the selected effect."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

from .records import persist_record, settle_existing_record
from .types import (
    WorkspaceRetentionOwner,
    WorkspaceRetentionRepo,
    WorkspaceRetentionSuccessor,
)

_GIT_TIMEOUT_SECONDS = 10


@dataclass(frozen=True, slots=True)
class _WorkspaceRetentionResult:
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
) -> _WorkspaceRetentionResult:
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
    baselines = _baseline_by_path(owner.evidence_artifacts_dir or owner.artifacts_dir)

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
) -> _WorkspaceRetentionResult:
    # Crash ordering: best-effort snapshot, then pinning (custody), then
    # durable record publication. Custody must survive a crash between pin
    # and publish; publication must never overwrite a settled record.
    checkouts = tuple((repo.repo_id, repo.path) for repo in _relevant_repos(owner))
    snapshot_paths: tuple[str, ...]
    try:
        snapshot_paths = tuple(
            snapshot_owner_worktree_diffs(owner.artifacts_dir, checkouts)
        )
    except Exception:  # noqa: BLE001 - snapshots are best effort
        snapshot_paths = ()
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
        record_path = persist_record(
            owner,
            disposition=DISPOSITION_OWNERSHIP_MOVED,
            reason=hold.error or "claim_ownership_moved",
            affected_repo_ids=affected_repo_ids,
            snapshot_paths=snapshot_paths,
            probe_errors=probe_errors,
            stale_attempt=True,
        )
        return _WorkspaceRetentionResult(
            disposition=DISPOSITION_OWNERSHIP_MOVED,
            reason=hold.error or "claim_ownership_moved",
            record_path=record_path,
            snapshot_paths=tuple(snapshot_paths),
            probe_errors=tuple(probe_errors),
            stale_attempt=True,
        )
    record_path = persist_record(
        owner,
        disposition=DISPOSITION_RETAIN,
        reason=reason,
        affected_repo_ids=affected_repo_ids,
        snapshot_paths=snapshot_paths,
        probe_errors=probe_errors,
        stale_attempt=False,
    )
    if owner.notify_on_retain and record_path:
        from ..workspace_retention_surface import notify_retained_workspace

        notify_retained_workspace(owner, record_path, snapshot_paths)
    return _WorkspaceRetentionResult(
        disposition=DISPOSITION_RETAIN,
        reason=reason,
        record_path=record_path,
        claim_changed=True,
        snapshot_paths=tuple(snapshot_paths),
        probe_errors=tuple(probe_errors),
    )


def _apply_release(
    owner: WorkspaceRetentionOwner,
    *,
    reason: str,
    probe_errors: Sequence[str],
) -> _WorkspaceRetentionResult:
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
        return _WorkspaceRetentionResult(
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
    record_path = settle_existing_record(owner, reason=reason)
    return _WorkspaceRetentionResult(
        disposition=DISPOSITION_RELEASE,
        reason=reason,
        record_path=record_path,
        claim_changed=True,
        probe_errors=tuple(probe_errors),
    )


def _apply_ownership_moved(
    owner: WorkspaceRetentionOwner,
    *,
    reason: str,
    affected_repo_ids: Sequence[str],
    probe_errors: Sequence[str],
) -> _WorkspaceRetentionResult:
    record_path = persist_record(
        owner,
        disposition=DISPOSITION_OWNERSHIP_MOVED,
        reason=reason,
        affected_repo_ids=affected_repo_ids,
        snapshot_paths=(),
        probe_errors=probe_errors,
        stale_attempt=True,
    )
    return _WorkspaceRetentionResult(
        disposition=DISPOSITION_OWNERSHIP_MOVED,
        reason=reason,
        record_path=record_path,
        probe_errors=tuple(probe_errors),
        stale_attempt=True,
    )


__all__ = ["settle_stranded_workspace"]
