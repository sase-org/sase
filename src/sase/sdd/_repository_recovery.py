"""Opt-in self-healing for machine-managed SDD sidecar clones."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import time

from sase.sdd._repository_recovery_git import (
    already_locked as _already_locked,
    configured_upstream as _configured_upstream,
    machine_recovery_cooldown_seconds as _machine_recovery_cooldown_seconds,
    managed_recovery_branch as _managed_recovery_branch,
    managed_recovery_failure as _managed_recovery_failure,
    recovery_error as _recovery_error,
    recovery_ref as _recovery_ref,
    update_and_verify_ref as _update_and_verify_ref,
    verify_managed_reset as _verify_managed_reset,
    verify_rebase_cleared as _verify_rebase_cleared,
)
from sase.sdd._repository_recovery_markers import (
    RECOVERY_ATTEMPT_MARKER as _RECOVERY_ATTEMPT_MARKER,
    admit_recovery_notice,
    read_recovery_marker as _read_marker,
    recovery_failure_signature,
    timestamp_is_recent as _timestamp_is_recent,
    write_recovery_marker as _write_marker,
)
from sase.sdd._repository_recovery_snapshot import (
    snapshot_managed_changes as _snapshot_managed_changes,
)
from sase.sdd._repository_transaction import (
    EventLogger,
    GitRunner,
    LockFactory,
    SddIntegrationOutcome,
    SddIntegrationStatus,
    default_git_runner,
    format_git_error,
    inspect_sdd_repository,
    integrate_sdd_repository_transaction,
    safe_git_error_text,
)


def recover_machine_managed_sdd_repository(
    repo_root: Path,
    *,
    original: SddIntegrationOutcome,
    beads_dir: Path | None,
    expected_branch: str | None,
    op_prefix: str,
    git_runner: GitRunner | None,
    lock_factory: LockFactory | None,
    clock: Callable[[], float] | None,
    recovery_cooldown_seconds: float | None,
    event_logger: EventLogger | None,
) -> SddIntegrationOutcome:
    root = repo_root.expanduser().resolve()
    runner = git_runner or default_git_runner
    if lock_factory is None:
        from sase.sdd._git_contention import store_git_write_lock_factory

        lock_factory = store_git_write_lock_factory(
            op=f"{op_prefix}.recovery",
            mutates_worktree=True,
        )
    now = (clock or time.time)()
    cooldown = (
        _machine_recovery_cooldown_seconds()
        if recovery_cooldown_seconds is None
        else max(0.0, recovery_cooldown_seconds)
    )

    with lock_factory(root) as acquired:
        if not acquired:
            # Recovery resets and stashes a shared clone. Doing that while
            # another cooperating writer holds the lock is exactly how committed
            # bead claims get discarded, so contention defers instead of
            # escalating to a reportable recovery failure.
            return SddIntegrationOutcome(
                SddIntegrationStatus.LOCK_UNAVAILABLE,
                error=(
                    f"SDD repository {root} could not acquire its store write "
                    "lock for machine-managed recovery; retry after the active "
                    "writer finishes"
                ),
            )
        try:
            starting = inspect_sdd_repository(root, runner)
        except Exception as exc:  # noqa: BLE001 - typed unsafe outcome
            return SddIntegrationOutcome(
                SddIntegrationStatus.UNRECOVERABLE,
                error=_recovery_error(
                    original,
                    f"could not inspect the managed clone: {safe_git_error_text(exc)}",
                ),
            )

        branch, branch_error = _managed_recovery_branch(starting)
        if branch_error is not None or branch is None:
            return SddIntegrationOutcome(
                SddIntegrationStatus.UNRECOVERABLE,
                error=_recovery_error(
                    original,
                    branch_error or "could not resolve the attached branch",
                ),
            )
        if expected_branch is not None and branch != expected_branch:
            return SddIntegrationOutcome(
                SddIntegrationStatus.UNRECOVERABLE,
                error=_recovery_error(
                    original,
                    f"expected branch {expected_branch!r}, found {branch!r}",
                ),
            )

        attempt_marker = starting.git_dir / _RECOVERY_ATTEMPT_MARKER
        attempt_record = _read_marker(attempt_marker)
        if _timestamp_is_recent(attempt_record.get("timestamp"), now, cooldown):
            return SddIntegrationOutcome(
                SddIntegrationStatus.RECOVERY_COOLDOWN,
                upstream_present=original.upstream_present,
                error=original.error,
            )
        if not _write_marker(
            attempt_marker,
            {
                "clone_path": str(root),
                "timestamp": now,
            },
        ):
            return _managed_recovery_failure(
                root,
                original=original,
                detail="could not persist the recovery-attempt marker",
                runner=runner,
                expected_branch=branch,
            )

        upstream_ref, remote, upstream_error = _configured_upstream(
            root,
            branch,
            runner,
            op_prefix,
        )
        if upstream_error is not None or upstream_ref is None or remote is None:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=upstream_error or "could not resolve the configured upstream",
                runner=runner,
                expected_branch=branch,
            )

        branch_head = runner(
            root,
            ["rev-parse", "--verify", f"refs/heads/{branch}"],
            op=f"{op_prefix}.recovery.branch_head",
        )
        if branch_head.returncode != 0 or not branch_head.stdout.strip():
            return _managed_recovery_failure(
                root,
                original=original,
                detail=format_git_error(
                    "could not resolve the managed branch", branch_head
                ),
                runner=runner,
                expected_branch=branch,
            )
        branch_sha = branch_head.stdout.strip()
        recovery_ref = _recovery_ref(root, branch, branch_sha, now)
        ref_error = _update_and_verify_ref(
            root,
            recovery_ref,
            branch_sha,
            runner,
            op_prefix,
        )
        if ref_error is not None:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=ref_error,
                runner=runner,
                expected_branch=branch,
            )

        if starting.operation_markers:
            aborted = runner(
                root,
                ["rebase", "--abort"],
                op=f"{op_prefix}.recovery.rebase_abort",
            )
            if aborted.returncode != 0:
                return _managed_recovery_failure(
                    root,
                    original=original,
                    detail=format_git_error(
                        "could not abort the stale rebase", aborted
                    ),
                    runner=runner,
                    expected_branch=branch,
                    recovery_ref=recovery_ref,
                )
            rebase_error = _verify_rebase_cleared(root, branch, runner)
            if rebase_error is not None:
                return _managed_recovery_failure(
                    root,
                    original=original,
                    detail=rebase_error,
                    runner=runner,
                    expected_branch=branch,
                    recovery_ref=recovery_ref,
                )

        if remote != ".":
            fetched = runner(
                root,
                ["fetch", "--prune", remote],
                op=f"{op_prefix}.recovery.fetch",
                network=True,
            )
            if fetched.returncode != 0:
                return _managed_recovery_failure(
                    root,
                    original=original,
                    detail=format_git_error("git fetch for recovery failed", fetched),
                    runner=runner,
                    expected_branch=branch,
                    recovery_ref=recovery_ref,
                )

        upstream_sha_result = runner(
            root,
            ["rev-parse", "--verify", upstream_ref],
            op=f"{op_prefix}.recovery.upstream",
        )
        if (
            upstream_sha_result.returncode != 0
            or not upstream_sha_result.stdout.strip()
        ):
            return _managed_recovery_failure(
                root,
                original=original,
                detail=format_git_error(
                    "could not resolve the fetched recovery upstream",
                    upstream_sha_result,
                ),
                runner=runner,
                expected_branch=branch,
                recovery_ref=recovery_ref,
            )
        upstream_sha = upstream_sha_result.stdout.strip()

        snapshot_ref, snapshot_error, snapshot_safe = _snapshot_managed_changes(
            root,
            branch=branch,
            recovery_ref=recovery_ref,
            runner=runner,
            op_prefix=op_prefix,
        )
        if snapshot_error is not None:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=snapshot_error,
                runner=runner,
                expected_branch=branch,
                recovery_ref=snapshot_ref,
                force_unsafe=not snapshot_safe,
            )

        reset = runner(
            root,
            ["reset", "--hard", upstream_ref],
            op=f"{op_prefix}.recovery.reset",
        )
        if reset.returncode != 0:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=format_git_error("could not reset the managed branch", reset),
                runner=runner,
                expected_branch=branch,
                recovery_ref=snapshot_ref,
            )
        reset_error = _verify_managed_reset(
            root,
            branch=branch,
            upstream_sha=upstream_sha,
            runner=runner,
        )
        if reset_error is not None:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=reset_error,
                runner=runner,
                expected_branch=branch,
                recovery_ref=snapshot_ref,
            )

        retried = integrate_sdd_repository_transaction(
            root,
            beads_dir=beads_dir,
            upstream=upstream_ref,
            fetch=False,
            expected_branch=branch,
            op_prefix=f"{op_prefix}.recovery_retry",
            git_runner=runner,
            lock_factory=_already_locked,
            event_logger=event_logger,
        )
        if not retried.succeeded:
            return _managed_recovery_failure(
                root,
                original=original,
                detail=(
                    "integration retry failed: "
                    + (retried.error or retried.status.value)
                ),
                runner=runner,
                expected_branch=branch,
                recovery_ref=snapshot_ref,
            )
        return SddIntegrationOutcome(
            SddIntegrationStatus.RECOVERED,
            integrated=True,
            upstream_present=True,
            resolved_files=retried.resolved_files,
            recovery_ref=snapshot_ref,
        )


__all__ = [
    "admit_recovery_notice",
    "recovery_failure_signature",
]
