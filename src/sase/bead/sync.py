"""Remote synchronization and public sync API for bead stores."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.bead._sync_git import (
    BeadWorkLaunchCommitError as BeadWorkLaunchCommitError,
)
from sase.bead._sync_git import (
    bead_state_is_clean as bead_state_is_clean,
    bead_store_write_lock as bead_store_write_lock,
    commit_bead_claim as commit_bead_claim,
    commit_bead_claim_release as commit_bead_claim_release,
    commit_bead_work_launch as commit_bead_work_launch,
    commit_epic_creation_rollback as commit_epic_creation_rollback,
    commit_epic_graph_checkpoint as commit_epic_graph_checkpoint,
    find_git_root as _find_git_root,
    git_sync as git_sync,
    rebuild_from_jsonl as rebuild_from_jsonl,
    relative_pathspec as _relative_pathspec,
)


BeadRefreshMode = Literal["background", "blocking", "off"]


class _BeadStoreRefreshError(RuntimeError):
    """Raised when a blocking refresh cannot integrate the bead store."""


@dataclass(frozen=True)
class _PushOutcome:
    """Result of attempting a post-commit ``git push``."""

    pushed: bool
    skipped_no_remote: bool
    error: str | None


@dataclass(frozen=True)
class _AsyncPushHandle:
    """Bookkeeping for a detached ``git push`` started in the background."""

    pid: int
    log_path: Path


def push_bead_work_launch(beads_dir: Path) -> _PushOutcome:
    """Synchronize and push the just-committed bead state.

    Returns a :class:`_PushOutcome` describing whether the push happened, was
    skipped because no remote is configured, or failed (with the error text).
    Never raises — push failures must not undo a successful local commit.
    """
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

    if not _has_push_remote(repo_root):
        return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

    from sase.bead.sync_worker import run_managed_sync_worker

    result = run_managed_sync_worker(
        repo_root,
        beads_dir.resolve(),
        log_path=_new_sync_log_path(),
    )
    if result.pushed:
        return _PushOutcome(pushed=True, skipped_no_remote=False, error=None)
    return _PushOutcome(
        pushed=False,
        skipped_no_remote=False,
        error=result.error or "managed bead sync did not push",
    )


def _has_push_remote(repo_root: Path) -> bool:
    remotes = subprocess.run(
        ["git", "remote"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return remotes.returncode == 0 and bool(remotes.stdout.strip())


def push_bead_work_launch_async(beads_dir: Path) -> _AsyncPushHandle | None:
    """Start a detached managed sync worker and return its log location.

    Returns ``None`` when there is no git repo or no configured remote (nothing
    to push). Unlike :func:`push_bead_work_launch`, this never blocks the caller
    on remote network/credential latency: the push runs in its own session with
    its output captured to a log file so ``sase bead work`` can return as soon as
    the agents are launched. Because it is detached, stdin is closed — a push
    that needs interactive credentials will fail and record the failure in the
    log rather than prompting.
    """
    repo_root = _find_git_root(beads_dir)
    if repo_root is None or not _has_push_remote(repo_root):
        return None

    log_path = _new_sync_log_path()
    with open(log_path, "w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sase.bead.sync_worker",
                str(repo_root),
                str(beads_dir.resolve()),
                str(log_path),
            ],
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return _AsyncPushHandle(pid=process.pid, log_path=log_path)


def _maybe_schedule_bead_refresh(beads_dir: Path) -> _AsyncPushHandle | None:
    """Launch a TTL-gated background integration for a warm sidecar store."""
    if bead_refresh_mode() != "background":
        return None
    repo_root = _find_git_root(beads_dir)
    if repo_root is None or _integration_is_fresh(repo_root):
        return None
    return push_bead_work_launch_async(beads_dir)


def bead_refresh_mode() -> BeadRefreshMode:
    """Return the configured remote-freshness policy for bead commands."""
    from sase.sdd._integration_marker import bead_refresh_mode as sdd_refresh_mode

    return sdd_refresh_mode()


def _integration_is_fresh(repo_root: Path) -> bool:
    """Compatibility wrapper for the SDD-owned integration marker."""
    from sase.sdd._integration_marker import integration_is_fresh

    return integration_is_fresh(repo_root)


def mark_bead_integration(repo_root: Path) -> None:
    """Compatibility wrapper for the SDD-owned integration marker."""
    from sase.sdd._integration_marker import mark_bead_integration as mark_integration

    mark_integration(repo_root)


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
    """Synchronously integrate the current remote-backed bead store.

    In-tree and non-remote stores need no integration. Unlike the managed sync
    worker, this read-recovery path deliberately stops after fetch/rebase and
    never pushes local state.
    """
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


def refresh_bead_store(beads_dir: Path) -> None:
    """Synchronously integrate one remote-backed project bead store.

    A recovery refresh is serialized with other store writers. The integration
    marker lets waiters skip work when another process completed the same
    recovery after they started waiting for the lock.
    """
    beads_dir = beads_dir.expanduser().resolve()
    if _is_in_tree_beads_dir(beads_dir):
        return

    repo_root = _find_git_root(beads_dir)
    if repo_root is None or not _has_push_remote(repo_root):
        return

    from sase.sdd._git_contention import (
        handoff_store_git_write_lock,
        store_git_write_lock,
    )
    from sase.sdd._integration_marker import integration_marker_generation
    from sase.sdd._repository_recovery_markers import (
        clear_failed_integration_marker,
    )
    from sase.sdd._repository_transaction import integrate_sdd_repository

    observed_generation = integration_marker_generation(repo_root)
    with store_git_write_lock(
        repo_root,
        op="bead.refresh",
        mutates_worktree=True,
    ) as acquired:
        current_generation = integration_marker_generation(repo_root)
        if current_generation is not None and current_generation != observed_generation:
            return
        if not acquired:
            raise _BeadStoreRefreshError(
                f"could not acquire the bead-store refresh lock for {repo_root}"
            )
        outcome = integrate_sdd_repository(
            repo_root,
            beads_dir=beads_dir,
            op_prefix="bead.refresh",
            lock_factory=handoff_store_git_write_lock,
        )
        if outcome.succeeded:
            # Any successful integration ends the clone's failed-integration
            # cooldown, not only the pull path that recorded it.
            clear_failed_integration_marker(
                repo_root,
                lock_factory=handoff_store_git_write_lock,
            )
    if outcome.succeeded:
        return

    detail = outcome.error or f"SDD integration ended with {outcome.status.value}"
    raise _BeadStoreRefreshError(detail)


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
    repo_root = _find_git_root(beads_dir)
    if repo_root is None:
        return []
    messages: list[str] = []
    git_dir = _git_state_path(repo_root, "")
    if (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir():
        messages.append("WARNING: bead store is mid-rebase")

    counts = subprocess.run(
        ["git", "rev-list", "--left-right", "--count", "@{upstream}...HEAD"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if counts.returncode == 0:
        try:
            behind, ahead = (int(value) for value in counts.stdout.split())
        except (TypeError, ValueError):
            behind = ahead = 0
        if behind and ahead:
            messages.append(
                f"WARNING: bead store has diverged ({ahead} local, {behind} remote commits)"
            )
        elif ahead:
            messages.append(f"WARNING: bead store has {ahead} unpushed commit(s)")
        elif behind:
            messages.append(f"WARNING: bead store is {behind} commit(s) behind")
        if ahead:
            bead_commits = _unpushed_bead_commit_count(
                repo_root,
                beads_dir,
            )
            if bead_commits:
                messages.append(
                    "WARNING: bead store has "
                    f"{bead_commits} unpushed local bead commit(s)"
                )

    from sase.sdd._repository_recovery_reaper import (
        RECOVERY_REF_PREFIX,
        RECOVERY_STASH_SUBJECT_FRAGMENT,
    )

    recovery_refs = subprocess.run(
        [
            "git",
            "for-each-ref",
            "--format=%(refname)",
            RECOVERY_REF_PREFIX,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if recovery_refs.returncode == 0:
        ref_count = len(
            [line for line in recovery_refs.stdout.splitlines() if line.strip()]
        )
        if ref_count:
            messages.append(f"WARNING: bead store retains {ref_count} recovery ref(s)")

    recovery_stashes = subprocess.run(
        ["git", "stash", "list", "--format=%gs"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if recovery_stashes.returncode == 0:
        stash_count = sum(
            RECOVERY_STASH_SUBJECT_FRAGMENT in subject
            for subject in recovery_stashes.stdout.splitlines()
        )
        if stash_count:
            messages.append(
                f"WARNING: bead store retains {stash_count} recovery stash(es)"
            )

    if messages:
        latest = _latest_bead_sync_log()
        if latest is not None:
            messages.append(f"INFO: latest bead sync log: {latest}")
    return messages


def _unpushed_bead_commit_count(repo_root: Path, beads_dir: Path) -> int:
    """Count local-only commits that touch canonical bead state."""
    try:
        rel_beads = _relative_pathspec(beads_dir, repo_root)
    except ValueError:
        return 0
    result = subprocess.run(
        [
            "git",
            "rev-list",
            "--count",
            "@{upstream}..HEAD",
            "--",
            f"{rel_beads}/",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return 0
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def _latest_bead_sync_log() -> Path | None:
    """Return the newest managed-sync log, when one exists."""
    from sase.core.paths import ensure_sase_directory

    log_dir = Path(ensure_sase_directory("bead_push_logs"))
    logs = list(log_dir.glob("sync-*.log"))
    return max(logs, key=lambda path: path.stat().st_mtime, default=None)


def _new_sync_log_path() -> Path:
    from sase.core.paths import ensure_sase_directory
    from sase.core.time import generate_timestamp

    log_dir = Path(ensure_sase_directory("bead_push_logs"))
    return log_dir / f"sync-{generate_timestamp()}.log"


def _git_state_path(repo_root: Path, name: str) -> Path:
    """Compatibility wrapper for resolving files in a checkout's Git dir."""
    from sase.sdd._integration_marker import git_state_path

    return git_state_path(repo_root, name)
