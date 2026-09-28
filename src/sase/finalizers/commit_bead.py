"""Late bead-sidecar residual handling for the built-in commit finalizer."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import Any

from sase.finalizers.commit_declaration import repository_decision_id
from sase.finalizers.commit_dispatch_types import DeferredRepoOutcome
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    failed_result,
)
from sase.finalizers.reconciliation import bead_sidecar_reconcile_diagnostic
from sase.llm_provider.commit_finalizer_prompting import failure_message
from sase.llm_provider.commit_finalizer_types import (
    BeadStateSyncOutcome,
    DirtyRepo,
    DirtyState,
)
from sase.llm_provider.types import InvokeResult


def _residual_includes_bead_sidecar(
    residual_repos: Sequence[DirtyRepo],
) -> bool:
    """Return whether any residual repo is an SDD/beads sidecar checkout."""

    return any(repo.kind == "sdd" for repo in residual_repos)


def _merge_late_bead_sync_into_state(
    state: Any,
    refreshed: Any,
    bead_sync: Any,
) -> Any:
    """Refresh the dirty snapshot after the bounded late bead pass.

    ``refreshed`` is the post-pass ``prepare_commit_dirty_state`` snapshot.
    The late bead commit flag, any reconcile failure, and any publication
    failure are folded in so ``raise_if_unpublished_machine_state`` still
    fails an unpublished bead commit even when the worktree looks clean,
    and integrity/lock failures are never swallowed as clean.
    """

    try:
        merged_publication_error = bead_sync.publication_error or getattr(
            refreshed, "bead_publication_error", None
        )
        merged_committed = bool(
            getattr(refreshed, "sdd_store_auto_committed", False)
            or getattr(bead_sync, "committed", False)
        )
        merged_reconcile_error = getattr(bead_sync, "reconcile_error", None) or getattr(
            refreshed, "bead_reconcile_error", None
        )
        merged_reconcile_kind = getattr(
            bead_sync, "reconcile_error_kind", None
        ) or getattr(refreshed, "bead_reconcile_error_kind", None)
        merged_sidecar = getattr(bead_sync, "beads_root", None) or getattr(
            refreshed, "bead_sidecar_path", None
        )
        merged_remaining = tuple(
            getattr(bead_sync, "remaining_files", ()) or ()
        ) or tuple(getattr(refreshed, "bead_remaining_files", ()) or ())
        return dataclass_replace(
            refreshed,
            sdd_store_auto_committed=merged_committed,
            bead_publication_error=merged_publication_error,
            bead_reconcile_error=merged_reconcile_error,
            bead_reconcile_error_kind=merged_reconcile_kind,
            bead_sidecar_path=merged_sidecar,
            bead_remaining_files=merged_remaining,
        )
    except Exception:
        return refreshed


def _state_bead_sync_outcome(state: Any) -> BeadStateSyncOutcome:
    """Project a prepared state back into a bead-sync outcome for diagnostics."""

    return BeadStateSyncOutcome(
        committed=bool(getattr(state, "sdd_store_auto_committed", False)),
        publication_error=getattr(state, "bead_publication_error", None),
        beads_root=getattr(state, "bead_sidecar_path", None),
        remaining_files=tuple(getattr(state, "bead_remaining_files", ()) or ()),
        reconcile_error=getattr(state, "bead_reconcile_error", None),
        reconcile_error_kind=getattr(state, "bead_reconcile_error_kind", None),
    )


def _late_bead_failure_message(
    state: Any,
    residual_repos: Sequence[DirtyRepo],
    bead_sync: Any,
) -> str:
    """Explain unresolved late bead dirt with the typed sidecar diagnostic."""

    base = failure_message(
        DirtyState(
            project_dir=state.dirty_state.project_dir,
            repos=tuple(residual_repos),
            details=state.dirty_state.details,
        ),
        max_passes=1,
        no_progress_passes=0,
    )
    # When the late pass left no residual but the bead sidecar hit a
    # reconcile or publication failure, the base message has no repo to
    # name; report the sidecar diagnostic on its own so the failure stays
    # actionable.
    if not residual_repos and (
        getattr(bead_sync, "publication_error", None)
        or getattr(bead_sync, "reconcile_error", None)
    ):
        diagnostic = bead_sidecar_reconcile_diagnostic(bead_sync)
        if diagnostic:
            return diagnostic
        detail = getattr(bead_sync, "publication_error", None) or getattr(
            bead_sync, "reconcile_error", None
        )
        return str(detail) if detail else base
    diagnostic = bead_sidecar_reconcile_diagnostic(bead_sync)
    if diagnostic:
        return f"{base}\n{diagnostic}"
    reconcile_error = getattr(bead_sync, "reconcile_error", None)
    if reconcile_error:
        kind = getattr(bead_sync, "reconcile_error_kind", None) or "commit"
        sidecar = getattr(bead_sync, "beads_root", None) or "(unknown bead sidecar)"
        return (
            f"{base}\nbead sidecar {sidecar} could not be reconciled\n"
            f"reason ({kind}): {reconcile_error}\n"
            "Recovery: inspect `git status --short --branch` in the sidecar, "
            "resolve the lock/integrity/push failure, then re-run the commit; "
            "no primary stitch was retried and no sidecar file was deleted."
        )
    return base


def ensure_no_residual_dirt(
    state: Any,
    deferred_outcomes: Sequence[DeferredRepoOutcome],
    *,
    project_dir: str,
    artifacts: Path | None,
    instance_id: str,
    invoke_result: InvokeResult,
    attempts: Sequence[Any],
    evidence: Sequence[Any],
    auto_bead_sync: Callable[[str, Path | None], Any],
    prepare_dirty_state: Callable[[str, Path | None], Any],
) -> Any:
    """Fail when stitch left residual dirt, with one bounded late bead pass.

    Runs at most one ``auto_commit_separate_sdd_store_if_possible`` pass when
    residuals include an SDD/beads sidecar checkout; never retries the primary
    stitch and never deletes sidecar files. Returns the (possibly refreshed)
    state on success, mirroring the original ``commit.py`` control flow.
    """

    deferred_repo_ids = {
        repository_decision_id(item.repo) for item in deferred_outcomes
    }
    residual_repos = tuple(
        repo
        for repo in state.dirty_state.repos
        if repository_decision_id(repo) not in deferred_repo_ids
    )
    late_bead_sync = None
    if not residual_repos:
        # A dispatch-time bead auto-commit may have hit a lock, integrity,
        # or commit failure yet left the tree clean via the integrity
        # guard's restore. Never swallow that as success.
        state_sync = _state_bead_sync_outcome(state)
        if state_sync.reconcile_error is not None:
            message_text = _late_bead_failure_message(state, (), state_sync)
            result = failed_result(
                instance_id,
                "dirty_after_commit_decisions",
                message_text,
                attempts=attempts,  # type: ignore[arg-type]
                evidence=evidence,  # type: ignore[arg-type]
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=invoke_result,
            )
    if residual_repos and _residual_includes_bead_sidecar(residual_repos):
        # One bounded pass for late SDD/beads dirt that landed after the
        # primary stitch (reconciliation race, publication, or another
        # sidecar writer). Reuses the store lock, event-stream integrity
        # guard, commit marker, and publication verification inside
        # ``auto_commit_separate_sdd_store_if_possible``; never retries the
        # primary stitch and never deletes sidecar files.
        late_bead_sync = auto_bead_sync(project_dir, artifacts)
        refreshed = prepare_dirty_state(project_dir, artifacts)
        state = _merge_late_bead_sync_into_state(state, refreshed, late_bead_sync)
        residual_repos = tuple(
            repo
            for repo in state.dirty_state.repos
            if repository_decision_id(repo) not in deferred_repo_ids
        )
        if (
            not residual_repos
            and late_bead_sync.publication_error is None
            and late_bead_sync.reconcile_error is None
        ):
            # Success only when every checkout is clean, the late bead
            # commit (when one was created) is published, and no
            # lock/integrity/commit failure was swallowed.
            residual_repos = ()
        # Any remaining dirt, an unreconciled bead failure, or an
        # unpublished late bead commit fails below with the typed bead
        # diagnostic attached.
    if (
        residual_repos
        or (late_bead_sync is not None and late_bead_sync.publication_error is not None)
        or (late_bead_sync is not None and late_bead_sync.reconcile_error is not None)
    ):
        if late_bead_sync is not None:
            message_text = _late_bead_failure_message(
                state, residual_repos, late_bead_sync
            )
        else:
            message_text = failure_message(
                DirtyState(
                    project_dir=state.dirty_state.project_dir,
                    repos=residual_repos,
                    details=state.dirty_state.details,
                ),
                max_passes=1,
                no_progress_passes=0,
            )
        result = failed_result(
            instance_id,
            "dirty_after_commit_decisions",
            message_text,
            attempts=attempts,  # type: ignore[arg-type]
            evidence=evidence,  # type: ignore[arg-type]
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=result,
            invoke_result=invoke_result,
        )
    return state


__all__ = [
    "ensure_no_residual_dirt",
]
