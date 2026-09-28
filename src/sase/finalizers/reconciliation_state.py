"""Dirty-state snapshot and machine-owned preparation for ``builtin@commit``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sase.finalizers.reconciliation_auto_commit import (
    auto_commit_done_plan_status_if_possible,
    auto_commit_external_sdd_prompt_qa_if_possible,
    auto_commit_sdd_bead_reprojection_if_possible,
)
from sase.finalizers.reconciliation_bead_store import (
    auto_commit_separate_sdd_store_if_possible,
)
from sase.llm_provider.commit_finalizer_git import (
    dirty_path_fingerprints,
    normalize_path,
)
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.llm_provider.commit_finalizer_types import (
    DirtyRepo,
    DirtyState,
)


@dataclass(frozen=True)
class PreparedCommitDirtyState:
    """Dirty-state snapshot after machine-owned auto-commits.

    ``dirty_state_before`` and ``fingerprints_before`` are the worktree as it
    existed before bead, plan-status, Q&A, or artifact-link auto-commits.
    Declaration staleness is checked against that snapshot; stitches run
    against ``dirty_state``.
    """

    dirty_state: DirtyState
    done_plan_auto_committed: bool = False
    sdd_prompt_qa_auto_committed: bool = False
    sdd_bead_projection_auto_committed: bool = False
    sdd_store_auto_committed: bool = False
    artifact_links_auto_committed: bool = False
    bead_publication_error: str | None = None
    artifact_link_publication_error: str | None = None
    bead_reconcile_error: str | None = None
    bead_reconcile_error_kind: str | None = None
    bead_sidecar_path: str | None = None
    bead_remaining_files: tuple[str, ...] = ()
    dirty_state_before: DirtyState | None = None
    fingerprints_before: Mapping[str, Mapping[str, tuple[str, str | None]]] | None = (
        None
    )


def prepare_commit_dirty_state(
    project_dir: str,
    artifacts: Path | None,
) -> PreparedCommitDirtyState:
    """Auto-commit machine-owned SDD/bead work, then rescan remaining dirt."""

    dirty_before = collect_dirty_state(project_dir, artifact_root=artifacts)
    fingerprints_before = {
        normalize_path(repo.path): dict(dirty_path_fingerprints(repo.path))
        for repo in dirty_before.repos
    }
    _, bead_projection_auto_committed = auto_commit_sdd_bead_reprojection_if_possible(
        project_dir,
        dirty_before,
        artifacts,
    )
    bead_sync = auto_commit_separate_sdd_store_if_possible(project_dir, artifacts)
    dirty_state = collect_dirty_state(project_dir, artifact_root=artifacts)
    dirty_state, qa_auto_committed = auto_commit_external_sdd_prompt_qa_if_possible(
        project_dir,
        dirty_state,
        artifacts,
    )
    dirty_state, done_auto_committed = auto_commit_done_plan_status_if_possible(
        project_dir,
        dirty_state,
        artifacts,
    )
    dirty_state, links_auto_committed, link_publication_error = (
        _auto_commit_artifact_link_indexes_if_possible(
            project_dir,
            dirty_state,
            artifacts,
        )
    )
    return PreparedCommitDirtyState(
        dirty_state=dirty_state,
        done_plan_auto_committed=done_auto_committed,
        sdd_prompt_qa_auto_committed=qa_auto_committed,
        sdd_bead_projection_auto_committed=bead_projection_auto_committed,
        sdd_store_auto_committed=bead_sync.committed,
        artifact_links_auto_committed=links_auto_committed,
        bead_publication_error=bead_sync.publication_error,
        artifact_link_publication_error=link_publication_error,
        bead_reconcile_error=bead_sync.reconcile_error,
        bead_reconcile_error_kind=bead_sync.reconcile_error_kind,
        bead_sidecar_path=bead_sync.beads_root,
        bead_remaining_files=tuple(bead_sync.remaining_files),
        dirty_state_before=dirty_before,
        fingerprints_before=fingerprints_before,
    )


def pre_reconciliation_dirty_state(state: PreparedCommitDirtyState) -> DirtyState:
    if state.dirty_state_before is not None:
        return state.dirty_state_before
    return state.dirty_state


def pre_reconciliation_fingerprints(
    state: PreparedCommitDirtyState,
    repo: DirtyRepo,
) -> Mapping[str, tuple[str, str | None]] | None:
    snapshots = state.fingerprints_before
    if not snapshots:
        return None
    key = normalize_path(repo.path)
    if key in snapshots:
        return snapshots[key]
    return snapshots.get(repo.path)


def _auto_commit_artifact_link_indexes_if_possible(
    project_dir: str,
    dirty_state: DirtyState,
    artifact_root: Path | None,
) -> tuple[DirtyState, bool, str | None]:
    """Legacy artifact-link index auto-commit is retired."""

    return dirty_state, False, None
