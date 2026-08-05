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
from sase.sdd._repository_types import SddIntegrationOutcome

_MAX_PUSH_ATTEMPTS = 3
_MAX_LOCAL_CHANGES_ATTEMPTS = 3
_LOCAL_CHANGES_RETRY_DELAY_SECONDS = 0.05
_WORKER_LOCK_POLL_SECONDS = 0.05


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
    worker_lock_wait: float = 0.0,
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
        # writers never acquire this outer lock, so this bounded wait cannot
        # deadlock.
        wait_started = time.monotonic()
        acquired = _acquire_worker_lock(
            lock_file.fileno(),
            timeout=worker_lock_wait,
        )
        waited_seconds = time.monotonic() - wait_started
        if not acquired:
            outcome = _ManagedSyncOutcome(
                pushed=False,
                integrated=False,
                skipped_locked=True,
            )
            _log(
                log_path,
                "skipped",
                reason="worker_already_running",
                waited_seconds=waited_seconds,
            )
            return outcome
        if (
            worker_lock_wait > 0.0
            and waited_seconds >= min(_WORKER_LOCK_POLL_SECONDS, worker_lock_wait) / 2
        ):
            _log(
                log_path,
                "worker_lock_acquired",
                waited_seconds=waited_seconds,
            )

        try:
            return _run_locked_sync(repo_root, beads_dir, log_path)
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _acquire_worker_lock(fd: int, *, timeout: float) -> bool:
    if timeout <= 0:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(_WORKER_LOCK_POLL_SECONDS, remaining))
        else:
            return True


def _run_locked_sync(
    repo_root: Path, beads_dir: Path, log_path: Path
) -> _ManagedSyncOutcome:
    _log(log_path, "started", repo_root=str(repo_root), beads_dir=str(beads_dir))

    from sase.sdd._git_contention import store_git_write_lock_factory
    from sase.sdd._repository_recovery_markers import clear_failed_integration_marker

    integrated = False
    for push_attempt in range(1, _MAX_PUSH_ATTEMPTS + 1):
        integration = _integrate_with_transient_dirty_retry(
            repo_root,
            beads_dir,
            log_path,
        )
        integrated = integrated or integration.integrated
        if not integration.succeeded:
            return _failure(
                log_path,
                integration.error
                or f"SDD integration ended with {integration.status.value}",
                integrated=integrated,
            )

        # Any successful integration ends the clone's failed-integration
        # cooldown, not only the pull path that recorded it.
        clear_failed_integration_marker(
            repo_root,
            git_runner=_git,
            lock_factory=store_git_write_lock_factory(
                op="bead.sync.integration_success",
                mutates_worktree=False,
            ),
        )

        pushed = _git(
            repo_root,
            ["push"],
            op="bead.sync.push",
            network=True,
        )
        if pushed.returncode == 0:
            _log(
                log_path,
                "completed",
                pushed=True,
                integrated=integrated,
                push_attempts=push_attempt,
            )
            return _ManagedSyncOutcome(pushed=True, integrated=integrated)
        if not _is_non_fast_forward_rejection(pushed):
            return _failure(
                log_path,
                "git push failed",
                pushed,
                integrated=integrated,
            )
        if push_attempt == _MAX_PUSH_ATTEMPTS:
            return _failure(
                log_path,
                f"git push rejected after {_MAX_PUSH_ATTEMPTS} attempts",
                pushed,
                integrated=integrated,
            )
        _log(
            log_path,
            "push_rejected_retry",
            attempt=push_attempt,
            max_attempts=_MAX_PUSH_ATTEMPTS,
        )

    raise AssertionError("bounded push loop ended without a terminal outcome")


def _integrate_with_transient_dirty_retry(
    repo_root: Path,
    beads_dir: Path,
    log_path: Path,
) -> SddIntegrationOutcome:
    """Retry a short-lived dirty state without accepting persistent edits."""
    from sase.sdd._git_contention import store_git_write_lock_factory
    from sase.sdd._repository_transaction import (
        SddIntegrationStatus,
        integrate_sdd_repository,
    )

    for attempt in range(1, _MAX_LOCAL_CHANGES_ATTEMPTS + 1):
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
            attempt=attempt,
            status=integration.status.value,
            integrated=integration.integrated,
            restored=integration.restored,
            resolved_files=list(integration.resolved_files),
        )
        if (
            integration.status is not SddIntegrationStatus.LOCAL_CHANGES
            or attempt == _MAX_LOCAL_CHANGES_ATTEMPTS
        ):
            return integration
        _log(
            log_path,
            "local_changes_retry",
            attempt=attempt,
            max_attempts=_MAX_LOCAL_CHANGES_ATTEMPTS,
        )
        time.sleep(_LOCAL_CHANGES_RETRY_DELAY_SECONDS)

    raise AssertionError("bounded local-changes loop ended without an outcome")


def _is_non_fast_forward_rejection(
    result: subprocess.CompletedProcess[str],
) -> bool:
    """Return whether a push lost a race and can succeed after integration."""
    output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
    return (
        "non-fast-forward" in output
        or "fetch first" in output
        or ("[rejected]" in output and "failed to push some refs" in output)
    )


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
