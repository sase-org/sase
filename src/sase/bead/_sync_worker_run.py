"""Managed one-shot fetch/rebase/push orchestration for bead stores."""

from __future__ import annotations

from collections.abc import Callable
import fcntl
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.bead._sync_worker_common import (
    deadline_remaining,
    deadline_timeout,
    log_sync_event,
    resolve_git_dir,
    rev_parse_head,
)
from sase.bead._sync_worker_rollback import restore_pre_integration_head
from sase.sdd._push_race import is_retryable_push_race
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
    bead_relocations: tuple[Any, ...] = ()
    push_attempts: int = 0


def run_managed_sync_worker(
    repo_root: Path,
    beads_dir: Path,
    *,
    log_path: Path,
    worker_lock_wait: float = 0.0,
    deadline: float | None = None,
) -> _ManagedSyncOutcome:
    """Fetch, rebase with bead conflict repair, and push without prompting."""
    repo_root = repo_root.expanduser().resolve()
    beads_dir = beads_dir.expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = resolve_git_dir(repo_root) / "sase-bead-sync.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        # Lock ordering is fixed: the worker-only sync lock is outer, and the
        # store write lock used by all foreground writers is inner. Foreground
        # writers never acquire this outer lock, so this bounded wait cannot
        # deadlock.
        wait_started = time.monotonic()
        acquired = _acquire_worker_lock(
            lock_file.fileno(),
            timeout=_bounded_wait(worker_lock_wait, deadline),
        )
        waited_seconds = time.monotonic() - wait_started
        if not acquired:
            outcome = _ManagedSyncOutcome(
                pushed=False,
                integrated=False,
                skipped_locked=True,
            )
            log_sync_event(
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
            log_sync_event(
                log_path,
                "worker_lock_acquired",
                waited_seconds=waited_seconds,
            )

        try:
            return _run_locked_sync(
                repo_root,
                beads_dir,
                log_path,
                deadline=deadline,
            )
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
    repo_root: Path,
    beads_dir: Path,
    log_path: Path,
    *,
    deadline: float | None,
) -> _ManagedSyncOutcome:
    log_sync_event(
        log_path, "started", repo_root=str(repo_root), beads_dir=str(beads_dir)
    )

    from sase.bead._stream_integrity import (
        BeadStreamIntegrityError,
        refuse_unpublished_event_stream_shrink,
    )
    from sase.sdd._git import SddGitCommandTimeout
    from sase.sdd._git_contention import store_git_write_lock_factory
    from sase.sdd._repository_recovery_markers import clear_failed_integration_marker

    try:
        refuse_unpublished_event_stream_shrink(
            repo_root,
            beads_dir,
            ignore_unreadable=True,
        )
    except BeadStreamIntegrityError as exc:
        return _failure(log_path, str(exc))

    from sase.bead.relocation import (
        compose_bead_relocations,
        rewrite_head_subject_for_bead_relocations,
    )

    integrated = False
    bead_relocations: tuple[Any, ...] = ()
    git_runner = _git_runner_for_deadline(deadline)
    for push_attempt in range(1, _MAX_PUSH_ATTEMPTS + 1):
        pre_head = rev_parse_head(
            repo_root, git_runner, op="bead.sync.pre_integration_head"
        )
        try:
            integration = _integrate_with_transient_dirty_retry(
                repo_root,
                beads_dir,
                log_path,
                git_runner=git_runner,
                deadline=deadline,
            )
        except SddGitCommandTimeout as exc:
            rollback_summary = restore_pre_integration_head(
                repo_root,
                log_path,
                git_runner=git_runner,
                deadline=deadline,
                pre_head=pre_head,
                reason=f"integration timed out: {exc}",
            )
            return _failure(
                log_path,
                f"integration timed out: {exc}; {rollback_summary}",
                integrated=integrated,
                bead_relocations=bead_relocations,
            )
        integrated = integrated or integration.integrated
        integration_relocations = _integration_relocations(integration)
        bead_relocations = compose_bead_relocations(
            bead_relocations,
            integration_relocations,
        )
        if not integration.succeeded:
            return _failure(
                log_path,
                integration.error
                or f"SDD integration ended with {integration.status.value}",
                integrated=integrated,
                bead_relocations=bead_relocations,
            )
        if integration_relocations:
            rewritten = rewrite_head_subject_for_bead_relocations(
                repo_root,
                integration_relocations,
            )
            log_sync_event(
                log_path,
                "relocation_subject_rewrite",
                rewritten=rewritten,
                bead_relocations=[
                    relocation.to_json_dict() for relocation in integration_relocations
                ],
            )
        try:
            refuse_unpublished_event_stream_shrink(repo_root, beads_dir)
        except BeadStreamIntegrityError as exc:
            # The guard rejected the integrated HEAD. Roll back to the
            # pre-integration HEAD instead of leaving the rewritten HEAD in
            # place, which is what wedged clones in the first place.
            rollback_summary = restore_pre_integration_head(
                repo_root,
                log_path,
                git_runner=git_runner,
                deadline=deadline,
                pre_head=pre_head,
                reason=str(exc),
            )
            return _failure(
                log_path,
                f"{exc}; {rollback_summary}",
                integrated=integrated,
                bead_relocations=bead_relocations,
            )

        # Any successful integration ends the clone's failed-integration
        # cooldown, not only the pull path that recorded it.
        try:
            clear_failed_integration_marker(
                repo_root,
                git_runner=git_runner,
                lock_factory=store_git_write_lock_factory(
                    op="bead.sync.integration_success",
                    mutates_worktree=False,
                    timeout=deadline_timeout(deadline),
                ),
            )
        except SddGitCommandTimeout as exc:
            return _failure(
                log_path,
                f"timed out clearing the integration marker: {exc}",
                integrated=integrated,
                bead_relocations=bead_relocations,
            )

        try:
            pushed = git_runner(
                repo_root,
                ["push"],
                op="bead.sync.push",
                network=True,
            )
        except SddGitCommandTimeout as exc:
            return _failure(
                log_path,
                f"git push timed out: {exc}",
                integrated=integrated,
                bead_relocations=bead_relocations,
            )
        if pushed.returncode == 0:
            log_sync_event(
                log_path,
                "completed",
                pushed=True,
                integrated=integrated,
                push_attempts=push_attempt,
                bead_relocations=[
                    relocation.to_json_dict() for relocation in bead_relocations
                ],
            )
            return _ManagedSyncOutcome(
                pushed=True,
                integrated=integrated,
                bead_relocations=bead_relocations,
                push_attempts=push_attempt,
            )
        if not _is_non_fast_forward_rejection(pushed):
            return _failure(
                log_path,
                "git push failed",
                pushed,
                integrated=integrated,
                bead_relocations=bead_relocations,
                push_attempts=push_attempt,
            )
        if push_attempt == _MAX_PUSH_ATTEMPTS:
            return _failure(
                log_path,
                f"git push rejected after {_MAX_PUSH_ATTEMPTS} attempts",
                pushed,
                integrated=integrated,
                bead_relocations=bead_relocations,
                push_attempts=push_attempt,
            )
        log_sync_event(
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
    *,
    git_runner: Callable[..., subprocess.CompletedProcess[str]],
    deadline: float | None,
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
            git_runner=git_runner,
            lock_factory=store_git_write_lock_factory(
                op="bead.sync.transaction",
                mutates_worktree=True,
                timeout=deadline_timeout(deadline),
            ),
            event_logger=lambda event, **fields: log_sync_event(
                log_path, event, **fields
            ),
        )
        integration_relocations = _integration_relocations(integration)
        log_sync_event(
            log_path,
            "integration",
            attempt=attempt,
            status=integration.status.value,
            integrated=integration.integrated,
            restored=integration.restored,
            resolved_files=list(integration.resolved_files),
            bead_relocations=[
                relocation.to_json_dict() for relocation in integration_relocations
            ],
        )
        if (
            integration.status is not SddIntegrationStatus.LOCAL_CHANGES
            or attempt == _MAX_LOCAL_CHANGES_ATTEMPTS
        ):
            return integration
        log_sync_event(
            log_path,
            "local_changes_retry",
            attempt=attempt,
            max_attempts=_MAX_LOCAL_CHANGES_ATTEMPTS,
        )
        time.sleep(
            min(
                _LOCAL_CHANGES_RETRY_DELAY_SECONDS,
                deadline_remaining(deadline)
                if deadline is not None
                else _LOCAL_CHANGES_RETRY_DELAY_SECONDS,
            )
        )

    raise AssertionError("bounded local-changes loop ended without an outcome")


def _integration_relocations(integration: Any) -> tuple[Any, ...]:
    return tuple(getattr(integration, "bead_relocations", ()))


def _is_non_fast_forward_rejection(
    result: subprocess.CompletedProcess[str],
) -> bool:
    """Return whether a push lost a race and can succeed after integration."""
    return is_retryable_push_race(result.stdout, result.stderr)


def _git_runner_for_deadline(
    deadline: float | None,
) -> Callable[..., subprocess.CompletedProcess[str]]:
    if deadline is None:
        return _git

    from sase.sdd._git import network_git_timeout
    from sase.sdd._git_contention import run_sdd_git_write, run_sdd_git_write_network

    def _run(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        timeout = deadline_timeout(
            deadline,
            network_git_timeout() if network else None,
        )
        if network:
            return run_sdd_git_write_network(
                args,
                cwd=repo_root,
                op=op,
                timeout=timeout,
                deadline=deadline,
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        return run_sdd_git_write(
            args,
            cwd=repo_root,
            op=op,
            timeout=timeout,
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )

    return _run


def _bounded_wait(wait_seconds: float, deadline: float | None) -> float:
    wait = max(0.0, wait_seconds)
    if deadline is None:
        return wait
    return min(wait, deadline_remaining(deadline))


def _failure(
    log_path: Path,
    message: str,
    result: subprocess.CompletedProcess[str] | None = None,
    *,
    integrated: bool = False,
    bead_relocations: tuple[Any, ...] = (),
    push_attempts: int = 0,
) -> _ManagedSyncOutcome:
    from sase.sdd._repository_health import format_git_error

    error = format_git_error(message, result) if result is not None else message
    log_sync_event(
        log_path,
        "failed",
        error=error,
        integrated=integrated,
        push_attempts=push_attempts,
        bead_relocations=[relocation.to_json_dict() for relocation in bead_relocations],
    )
    return _ManagedSyncOutcome(
        pushed=False,
        integrated=integrated,
        error=error,
        bead_relocations=bead_relocations,
        push_attempts=push_attempts,
    )
