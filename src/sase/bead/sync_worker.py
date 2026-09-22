"""Managed one-shot integration worker for sidecar bead stores."""

from __future__ import annotations

from collections.abc import Callable
import fcntl
import json
import os
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
    bead_relocations: tuple[Any, ...] = ()


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
            timeout=_bounded_wait(worker_lock_wait, deadline),
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
    _log(log_path, "started", repo_root=str(repo_root), beads_dir=str(beads_dir))

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
        pre_head = _rev_parse_head(
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
            rollback_summary = _restore_pre_integration_head(
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
            _log(
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
            rollback_summary = _restore_pre_integration_head(
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
                    timeout=_deadline_timeout(deadline),
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
            _log(
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
            )
        if not _is_non_fast_forward_rejection(pushed):
            return _failure(
                log_path,
                "git push failed",
                pushed,
                integrated=integrated,
                bead_relocations=bead_relocations,
            )
        if push_attempt == _MAX_PUSH_ATTEMPTS:
            return _failure(
                log_path,
                f"git push rejected after {_MAX_PUSH_ATTEMPTS} attempts",
                pushed,
                integrated=integrated,
                bead_relocations=bead_relocations,
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
                timeout=_deadline_timeout(deadline),
            ),
            event_logger=lambda event, **fields: _log(log_path, event, **fields),
        )
        integration_relocations = _integration_relocations(integration)
        _log(
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
        _log(
            log_path,
            "local_changes_retry",
            attempt=attempt,
            max_attempts=_MAX_LOCAL_CHANGES_ATTEMPTS,
        )
        time.sleep(
            min(
                _LOCAL_CHANGES_RETRY_DELAY_SECONDS,
                _deadline_remaining(deadline)
                if deadline is not None
                else _LOCAL_CHANGES_RETRY_DELAY_SECONDS,
            )
        )

    raise AssertionError("bounded local-changes loop ended without an outcome")


def _integration_relocations(integration: Any) -> tuple[Any, ...]:
    return tuple(getattr(integration, "bead_relocations", ()))


def _rev_parse_head(
    repo_root: Path,
    git_runner: Callable[..., subprocess.CompletedProcess[str]],
    *,
    op: str,
) -> str | None:
    """Resolve HEAD without raising; None when it cannot be read."""
    try:
        result = git_runner(repo_root, ["rev-parse", "--verify", "HEAD"], op=op)
    except Exception:  # noqa: BLE001 - a missing HEAD only skips the rollback
        return None
    head = result.stdout.strip() if result.returncode == 0 else ""
    return head or None


def _current_branch(
    repo_root: Path,
    git_runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    """Resolve the current branch without raising; falls back to a label."""
    try:
        result = git_runner(
            repo_root,
            ["symbolic-ref", "--quiet", "--short", "HEAD"],
            op="bead.sync.rollback_branch",
        )
    except Exception:  # noqa: BLE001 - the branch only names the recovery ref
        return "bead-sync"
    branch = result.stdout.strip() if result.returncode == 0 else ""
    return branch or "bead-sync"


def _restore_pre_integration_head(
    repo_root: Path,
    log_path: Path,
    *,
    git_runner: Callable[..., subprocess.CompletedProcess[str]],
    deadline: float | None,
    pre_head: str | None,
    reason: str,
) -> str:
    """Pin the rejected HEAD and restore *pre_head*; never raises.

    Mirrors ``_abort_and_verify`` in ``sase.sdd._repository_integration``:
    aborts an in-progress rebase when markers are present, otherwise resets
    ``--hard`` under the store write lock. Returns a short summary for the
    failure message; the full detail goes to the sync log.
    """
    from sase.sdd._git_contention import store_git_write_lock_factory
    from sase.sdd._repository_recovery_git import (
        recovery_ref,
        update_and_verify_ref,
    )

    lock_factory = store_git_write_lock_factory(
        op="bead.sync.post_guard_rollback",
        mutates_worktree=True,
        timeout=_deadline_timeout(deadline),
    )
    try:
        return _rollback_with_lock(
            repo_root,
            log_path,
            git_runner=git_runner,
            lock_factory=lock_factory,
            pre_head=pre_head,
            reason=reason,
            recovery_ref=recovery_ref,
            update_and_verify_ref=update_and_verify_ref,
        )
    except Exception as exc:  # noqa: BLE001 - rollback is best-effort
        summary = f"rollback failed: {exc}"
        _log(log_path, "post_guard_rollback", reason=reason, summary=summary)
        return summary


def _rollback_with_lock(
    repo_root: Path,
    log_path: Path,
    *,
    git_runner: Callable[..., subprocess.CompletedProcess[str]],
    lock_factory: Callable[[Path], Any],
    pre_head: str | None,
    reason: str,
    recovery_ref: Callable[..., str],
    update_and_verify_ref: Callable[..., str | None],
) -> str:
    rejected_head = _rev_parse_head(repo_root, git_runner, op="bead.sync.rejected_head")
    branch = _current_branch(repo_root, git_runner)
    fields: dict[str, Any] = {
        "reason": reason,
        "pre_head": pre_head,
        "rejected_head": rejected_head,
    }
    with lock_factory(repo_root) as acquired:
        if not acquired:
            summary = "rollback skipped: store write lock unavailable"
            _log(log_path, "post_guard_rollback", **fields, summary=summary)
            return summary
        if rejected_head is not None:
            recovery_name = recovery_ref(repo_root, branch, rejected_head, time.time())
            try:
                ref_error = update_and_verify_ref(
                    repo_root,
                    recovery_name,
                    rejected_head,
                    git_runner,
                    "bead.sync.post_guard_rollback",
                )
            except Exception as exc:  # noqa: BLE001 - pinning is best-effort
                ref_error = f"could not pin a recovery ref: {exc}"
            fields["recovery_ref"] = recovery_name
            fields["recovery_ref_error"] = ref_error
        else:
            fields["recovery_ref_error"] = "no rejected HEAD to preserve"
        git_dir = _git_dir(repo_root)
        rebase_active = (git_dir / "rebase-merge").exists() or (
            git_dir / "rebase-apply"
        ).exists()
        fields["rebase_active"] = rebase_active
        restore_error: str | None = None
        if rebase_active:
            try:
                aborted = git_runner(
                    repo_root,
                    ["rebase", "--abort"],
                    op="bead.sync.rollback_rebase_abort",
                )
            except Exception as exc:  # noqa: BLE001 - record, then verify
                restore_error = f"git rebase --abort failed: {exc}"
            else:
                if aborted.returncode != 0:
                    restore_error = (
                        "git rebase --abort failed: "
                        f"{(aborted.stderr or aborted.stdout or '').strip()}"
                    )
        current_head = _rev_parse_head(
            repo_root, git_runner, op="bead.sync.rollback_verify_head"
        )
        if restore_error is None and pre_head is not None and current_head != pre_head:
            try:
                restored = git_runner(
                    repo_root,
                    ["reset", "--hard", pre_head],
                    op="bead.sync.rollback_reset",
                )
            except Exception as exc:  # noqa: BLE001 - record, then verify
                restore_error = f"git reset --hard failed: {exc}"
            else:
                if restored.returncode != 0:
                    restore_error = (
                        "git reset --hard failed: "
                        f"{(restored.stderr or restored.stdout or '').strip()}"
                    )
                current_head = _rev_parse_head(
                    repo_root, git_runner, op="bead.sync.rollback_verify_head"
                )
        markers_remain = (git_dir / "rebase-merge").exists() or (
            git_dir / "rebase-apply"
        ).exists()
        fields["restore_error"] = restore_error
        fields["current_head"] = current_head
        fields["rebase_markers_remain"] = markers_remain
        if (
            restore_error is None
            and not markers_remain
            and (pre_head is None or current_head == pre_head)
        ):
            if pre_head is None:
                summary = "left HEAD untouched (no pre-integration HEAD recorded)"
            else:
                summary = f"restored pre-integration HEAD {pre_head[:12]}"
                if fields.get("recovery_ref") is not None:
                    summary += f"; rejected HEAD preserved at {fields['recovery_ref']}"
            _log(log_path, "post_guard_rollback", **fields, summary=summary)
            return summary
        problems = []
        if restore_error is not None:
            problems.append(restore_error)
        if markers_remain:
            problems.append("rebase markers remain after abort")
        if pre_head is not None and current_head != pre_head:
            problems.append(
                f"HEAD is {current_head!r}, expected pre-integration {pre_head!r}"
            )
        summary = "rollback verification failed: " + "; ".join(problems)
        _log(log_path, "post_guard_rollback", **fields, summary=summary)
        return summary


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
        timeout = _deadline_timeout(
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
    return min(wait, _deadline_remaining(deadline))


def _deadline_timeout(
    deadline: float | None,
    cap: float | None = None,
) -> float | None:
    if deadline is None:
        return cap
    remaining = max(0.001, _deadline_remaining(deadline))
    return remaining if cap is None else min(cap, remaining)


def _deadline_remaining(deadline: float | None) -> float:
    if deadline is None:
        return 0.0
    return max(0.0, deadline - time.monotonic())


def _failure(
    log_path: Path,
    message: str,
    result: subprocess.CompletedProcess[str] | None = None,
    *,
    integrated: bool = False,
    bead_relocations: tuple[Any, ...] = (),
) -> _ManagedSyncOutcome:
    from sase.sdd._repository_health import format_git_error

    error = format_git_error(message, result) if result is not None else message
    _log(
        log_path,
        "failed",
        error=error,
        integrated=integrated,
        bead_relocations=[relocation.to_json_dict() for relocation in bead_relocations],
    )
    return _ManagedSyncOutcome(
        pushed=False,
        integrated=integrated,
        error=error,
        bead_relocations=bead_relocations,
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
