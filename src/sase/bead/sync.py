"""Public synchronization API for bead stores.

Implementation lives in focused sibling modules. This facade intentionally
keeps the established import and monkeypatch surface stable for callers.
"""

from __future__ import annotations

from pathlib import Path

from sase.bead import _sync_diagnostics, _sync_logs, _sync_publication, _sync_refresh
from sase.bead._sync_git import (
    BeadWorkLaunchCommitError as BeadWorkLaunchCommitError,
)
from sase.bead._sync_git import (
    bead_state_is_clean as bead_state_is_clean,
    bead_store_write_lock as bead_store_write_lock,
    commit_bead_claim as commit_bead_claim,
    commit_bead_claim_reconciliation as commit_bead_claim_reconciliation,
    commit_bead_claim_release as commit_bead_claim_release,
    commit_epic_creation_rollback as commit_epic_creation_rollback,
    commit_epic_graph_checkpoint as commit_epic_graph_checkpoint,
    commit_failed_work_launch_recovery as commit_failed_work_launch_recovery,
    commit_task_work_launch as commit_task_work_launch,
    find_git_root as _find_git_root,
    git_sync as git_sync,
    rebuild_from_jsonl as rebuild_from_jsonl,
    relative_pathspec as _relative_pathspec,
)
from sase.bead._sync_logs import new_sync_log_path as _new_sync_log_path_impl
from sase.bead._sync_refresh import integration_is_fresh as _integration_is_fresh


BeadRefreshMode = _sync_refresh.BeadRefreshMode
_BeadStoreRefreshError = _sync_refresh.BeadStoreRefreshError
_SyncLogOutcome = _sync_logs.SyncLogOutcome
_PushOutcome = _sync_publication.PushOutcome
_AsyncPushHandle = _sync_publication.AsyncPushHandle

_DEEP_DIVERGENCE_SIDE_THRESHOLD = _sync_diagnostics._DEEP_DIVERGENCE_SIDE_THRESHOLD
_SYNC_LOG_SCAN_LIMIT = _sync_logs._SYNC_LOG_SCAN_LIMIT
_SYNC_LOG_HEAD_BYTES = _sync_logs._SYNC_LOG_HEAD_BYTES
_SYNC_LOG_TAIL_BYTES = _sync_logs._SYNC_LOG_TAIL_BYTES
_SYNC_LOG_RECURRING_FAILURE_THRESHOLD = _sync_logs._SYNC_LOG_RECURRING_FAILURE_THRESHOLD

# Launch-critical publication waits through observed multi-second integration,
# retry, and push windows instead of treating an active worker as fatal.
PUBLICATION_WORKER_LOCK_WAIT_SECONDS = 120.0


def push_bead_work_launch(
    beads_dir: Path,
    *,
    lock_timeout: float | None = None,
    worker_lock_wait: float = 0.0,
) -> _PushOutcome:
    """Synchronize and push just-committed bead state without raising."""
    return _sync_publication.push_bead_work_launch(
        beads_dir,
        lock_timeout=lock_timeout,
        worker_lock_wait=worker_lock_wait,
        find_git_root=_find_git_root,
        new_sync_log_path=_new_sync_log_path,
    )


def publish_bead_claim(
    beads_dir: Path,
    bead_id: str,
    agent_name: str,
) -> _PushOutcome:
    """Synchronously publish one runner-owned bead claim transition."""
    return _sync_publication.publish_bead_claim(
        beads_dir,
        bead_id,
        agent_name,
        is_in_tree_beads_dir=_is_in_tree_beads_dir,
        push=push_bead_work_launch,
    )


_has_push_remote = _sync_publication.has_push_remote
_head_is_published = _sync_publication.head_is_published


def push_bead_work_launch_async(beads_dir: Path) -> _AsyncPushHandle | None:
    """Start a detached managed sync worker and return its log location."""
    return _sync_publication.push_bead_work_launch_async(
        beads_dir,
        find_git_root=_find_git_root,
        new_sync_log_path=_new_sync_log_path,
    )


_semantic_beads_dir_for_sync = _sync_publication.semantic_beads_dir_for_sync


def _maybe_schedule_bead_refresh(beads_dir: Path) -> _AsyncPushHandle | None:
    """Launch a TTL-gated background integration for a warm sidecar store."""
    if bead_refresh_mode() != "background":
        return None
    repo_root = _find_git_root(beads_dir)
    if repo_root is None or _integration_is_fresh(repo_root):
        return None
    return push_bead_work_launch_async(beads_dir)


bead_refresh_mode = _sync_refresh.bead_refresh_mode
mark_bead_integration = _sync_refresh.mark_bead_integration


def bead_store_git_root(path: Path) -> Path | None:
    """Return the Git worktree root owning a bead-store path, when present."""
    return _find_git_root(path)


def schedule_current_bead_refresh() -> _AsyncPushHandle | None:
    """Best-effort post-command refresh for the currently resolved store."""
    try:
        from sase.bead.cli_common import resolve_beads_location

        location = resolve_beads_location(require_existing=True)
        if location is None or location.is_in_tree:
            return None
        return _maybe_schedule_bead_refresh(location.beads_dir)
    except Exception:
        return None


def refresh_current_bead_store() -> None:
    """Synchronously integrate the current remote-backed bead store."""
    from sase.bead.cli_common import resolve_beads_location

    location = resolve_beads_location(require_existing=True)
    if (
        location is None
        or location.is_in_tree
        or location.store is None
        or not location.store.remote_url
    ):
        return

    refresh_bead_store(location.beads_dir)


def refresh_bead_store(beads_dir: Path, *, lock_timeout: float | None = None) -> None:
    """Synchronously integrate one remote-backed project bead store."""
    _sync_refresh.refresh_bead_store(
        beads_dir,
        lock_timeout=lock_timeout,
        find_git_root=_find_git_root,
        has_push_remote=_has_push_remote,
        is_in_tree_beads_dir=_is_in_tree_beads_dir,
    )


def _is_in_tree_beads_dir(beads_dir: Path) -> bool:
    """Return whether *beads_dir* is the primary repo's ``sdd/beads`` store."""
    parts = beads_dir.parts
    return (
        len(parts) >= 2
        and parts[-2:] == ("sdd", "beads")
        and not (len(parts) >= 3 and parts[-3:] == (".sase", "sdd", "beads"))
    )


def bead_sync_diagnostics(beads_dir: Path) -> list[str]:
    """Report convergence problems visible from the local clone."""
    return _sync_diagnostics.bead_sync_diagnostics(
        beads_dir,
        find_git_root=_find_git_root,
    )


def unpushed_bead_commit_count(repo_root: Path, beads_dir: Path) -> int:
    """Count local-only commits that touch canonical bead state."""
    return _sync_diagnostics.unpushed_bead_commit_count(repo_root, beads_dir)


_managed_sync_log_diagnostics = _sync_logs.managed_sync_log_diagnostics
_recent_bead_sync_log_paths = _sync_logs.recent_bead_sync_log_paths
_parse_sync_log_outcome = _sync_logs.parse_sync_log_outcome
_read_sync_log_records = _sync_logs.read_sync_log_records
_classify_sync_error = _sync_logs.classify_sync_error
_normalize_logged_repo_root = _sync_logs.normalize_logged_repo_root
_normalized_path_string = _sync_logs.normalized_path_string
_latest_bead_sync_log = _sync_logs.latest_bead_sync_log
_bead_sync_log_dir = _sync_logs.bead_sync_log_dir


def _new_sync_log_path() -> Path:
    """Return a fresh managed-sync log path that no concurrent push can reuse."""
    return _new_sync_log_path_impl()


_git_state_path = _sync_diagnostics.git_state_path_for_checkout
