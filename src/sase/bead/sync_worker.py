"""Managed one-shot integration worker for sidecar bead stores."""

from __future__ import annotations

import fcntl
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.sdd._repository_health import default_git_runner as _git


@dataclass(frozen=True)
class _ManagedSyncOutcome:
    """Terminal result from one managed fetch/rebase/push attempt."""

    pushed: bool
    integrated: bool
    skipped_locked: bool = False
    error: str | None = None


def run_managed_sync_worker(
    repo_root: Path,
    beads_dir: Path,
    *,
    log_path: Path,
) -> _ManagedSyncOutcome:
    """Fetch, rebase with bead conflict repair, and push without prompting."""
    repo_root = repo_root.expanduser().resolve()
    beads_dir = beads_dir.expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = _git_dir(repo_root) / "sase-bead-sync.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        # Lock ordering is fixed: the worker-only sync lock is outer, and the
        # store write lock used by all foreground writers is inner. Foreground
        # writers never acquire this outer lock, so this order cannot deadlock.
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            outcome = _ManagedSyncOutcome(
                pushed=False,
                integrated=False,
                skipped_locked=True,
            )
            _log(log_path, "skipped", reason="worker_already_running")
            return outcome

        try:
            return _run_locked_sync(repo_root, beads_dir, log_path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _run_locked_sync(
    repo_root: Path, beads_dir: Path, log_path: Path
) -> _ManagedSyncOutcome:
    _log(log_path, "started", repo_root=str(repo_root), beads_dir=str(beads_dir))

    from sase.sdd._git_contention import store_git_write_lock_factory
    from sase.sdd._repository_recovery_markers import clear_failed_integration_marker
    from sase.sdd._repository_transaction import integrate_sdd_repository

    integration = integrate_sdd_repository(
        repo_root,
        beads_dir=beads_dir,
        op_prefix="bead.sync",
        git_runner=_git,
        lock_factory=store_git_write_lock_factory(
            op="bead.sync.transaction",
            mutates_worktree=True,
        ),
        event_logger=lambda event, **fields: _log(log_path, event, **fields),
    )
    _log(
        log_path,
        "integration",
        status=integration.status.value,
        integrated=integration.integrated,
        restored=integration.restored,
        resolved_files=list(integration.resolved_files),
    )
    if not integration.succeeded:
        return _failure(
            log_path,
            integration.error
            or f"SDD integration ended with {integration.status.value}",
        )

    # Any successful integration ends the clone's failed-integration cooldown,
    # not only the pull path that recorded it.
    clear_failed_integration_marker(
        repo_root,
        git_runner=_git,
        lock_factory=store_git_write_lock_factory(
            op="bead.sync.integration_success",
            mutates_worktree=False,
        ),
    )

    integrated = integration.integrated
    pushed = _git(
        repo_root,
        ["push"],
        op="bead.sync.push",
        network=True,
    )
    if pushed.returncode != 0:
        return _failure(log_path, "git push failed", pushed, integrated=integrated)

    _log(log_path, "completed", pushed=True, integrated=integrated)
    return _ManagedSyncOutcome(pushed=True, integrated=integrated)


def _failure(
    log_path: Path,
    message: str,
    result: subprocess.CompletedProcess[str] | None = None,
    *,
    integrated: bool = False,
) -> _ManagedSyncOutcome:
    from sase.sdd._repository_health import format_git_error

    error = format_git_error(message, result) if result is not None else message
    _log(log_path, "failed", error=error, integrated=integrated)
    return _ManagedSyncOutcome(
        pushed=False,
        integrated=integrated,
        error=error,
    )


def _git_dir(repo_root: Path) -> Path:
    # This read-only probe cannot contend on the repository index.
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    path = Path(result.stdout.strip()) if result.returncode == 0 else Path(".git")
    return path if path.is_absolute() else repo_root / path


def _log(log_path: Path, event: str, **fields: Any) -> None:
    record = {"ts": time.time(), "event": event, **fields}
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(record, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 3:
        return 2
    outcome = run_managed_sync_worker(
        Path(args[0]),
        Path(args[1]),
        log_path=Path(args[2]),
    )
    return 0 if outcome.pushed or outcome.skipped_locked else 1


if __name__ == "__main__":
    raise SystemExit(main())
