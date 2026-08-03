"""Synchronous and detached publication of committed bead state."""

from __future__ import annotations

from collections.abc import Callable
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _PushOutcome:
    """Result of attempting a post-commit ``git push``."""

    pushed: bool
    skipped_no_remote: bool
    error: str | None
    skipped_locked: bool = False
    log_path: Path | None = None


@dataclass(frozen=True)
class _AsyncPushHandle:
    """Bookkeeping for a detached ``git push`` started in the background."""

    pid: int
    log_path: Path


def push_bead_work_launch(
    beads_dir: Path,
    *,
    lock_timeout: float | None,
    worker_lock_wait: float,
    find_git_root: Callable[[Path], Path | None],
    new_sync_log_path: Callable[[], Path],
) -> _PushOutcome:
    """Synchronize and push the just-committed bead state without raising."""
    try:
        repo_root = find_git_root(beads_dir)
        if repo_root is None:
            return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

        if not _has_push_remote(repo_root):
            return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

        from sase.bead.sync_worker import run_managed_sync_worker

        log_path = new_sync_log_path()
        semantic_beads_dir = _semantic_beads_dir_for_sync(repo_root, beads_dir)
        result = run_managed_sync_worker(
            repo_root,
            semantic_beads_dir,
            log_path=log_path,
            lock_timeout=lock_timeout,
            worker_lock_wait=worker_lock_wait,
        )
        if result.pushed:
            return _PushOutcome(
                pushed=True,
                skipped_no_remote=False,
                error=None,
                log_path=log_path,
            )
        if result.skipped_locked:
            if _head_is_published(repo_root):
                return _PushOutcome(
                    pushed=True,
                    skipped_no_remote=False,
                    error=None,
                    log_path=log_path,
                )
            return _PushOutcome(
                pushed=False,
                skipped_no_remote=False,
                error=None,
                skipped_locked=True,
                log_path=log_path,
            )
        return _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error=result.error
            or f"managed bead sync did not push and reported no error (see {log_path})",
            log_path=log_path,
        )
    except Exception as exc:  # noqa: BLE001 - this API must never raise.
        return _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error=str(exc) or type(exc).__name__,
        )


def publish_bead_claim(
    beads_dir: Path,
    bead_id: str,
    agent_name: str,
    *,
    is_in_tree_beads_dir: Callable[[Path], bool],
    push: Callable[[Path], _PushOutcome],
) -> _PushOutcome:
    """Synchronously publish one runner-owned bead claim transition."""
    if is_in_tree_beads_dir(beads_dir):
        return _PushOutcome(pushed=False, skipped_no_remote=True, error=None)

    try:
        outcome = push(beads_dir)
    except Exception as exc:  # noqa: BLE001 - publication must preserve claims.
        outcome = _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error=str(exc),
        )

    if outcome.error and not getattr(outcome, "skipped_locked", False):
        detail = outcome.error
        if outcome.log_path is not None:
            detail = f"{detail} (managed sync log: {outcome.log_path})"
        print(
            f"Warning: Failed to publish bead claim transition for bead "
            f"'{bead_id}' and agent '{agent_name}': {detail}",
            file=sys.stderr,
        )
    return outcome


def _has_push_remote(repo_root: Path) -> bool:
    remotes = subprocess.run(
        ["git", "remote"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return remotes.returncode == 0 and bool(remotes.stdout.strip())


def _head_is_published(repo_root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", "HEAD", "@{upstream}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return result.returncode == 0


def push_bead_work_launch_async(
    beads_dir: Path,
    *,
    find_git_root: Callable[[Path], Path | None],
    new_sync_log_path: Callable[[], Path],
) -> _AsyncPushHandle | None:
    """Start a detached managed sync worker and return its log location."""
    repo_root = find_git_root(beads_dir)
    if repo_root is None or not _has_push_remote(repo_root):
        return None

    semantic_beads_dir = _semantic_beads_dir_for_sync(repo_root, beads_dir)
    log_path = new_sync_log_path()
    # Append rather than truncate: the worker writes its own JSON records to
    # this same file, so a child traceback must land after them, not over them.
    with open(log_path, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "sase.bead.sync_worker",
                str(repo_root),
                str(semantic_beads_dir),
                str(log_path),
            ],
            cwd=repo_root,
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return _AsyncPushHandle(pid=process.pid, log_path=log_path)


def _semantic_beads_dir_for_sync(repo_root: Path, requested_path: Path) -> Path:
    """Preserve the bead-store prefix when a generic caller passes a repo root."""
    requested = requested_path.expanduser().resolve()
    root = repo_root.expanduser().resolve()
    if requested != root:
        return requested

    from sase.bead.conflict_resolver import resolve_beads_dir

    return resolve_beads_dir(root) or requested
