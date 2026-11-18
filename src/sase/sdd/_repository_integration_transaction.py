"""Transactional fetch/rebase entry point for SDD repositories."""

from __future__ import annotations

from pathlib import Path

from sase.sdd._git import SddGitCommandTimeout
from sase.sdd._repository_health import (
    SddRepositoryInspectionTimeout,
    format_git_error,
    health_error,
    inspect_sdd_repository,
    safe_git_error_text,
    sdd_state_blockers,
    tracked_changes_error,
)
from sase.sdd._repository_integration_repair import repair_or_abort_rebase
from sase.sdd._repository_integration_verify import (
    abort_and_verify,
    successful_integration,
)
from sase.sdd._repository_types import (
    EventLogger,
    GitRunner,
    LockFactory,
    SddIntegrationOutcome,
    SddIntegrationStatus,
    is_git_timeout,
)


def _timed_out_outcome(
    detail: str, *, upstream_present: bool = False
) -> SddIntegrationOutcome:
    return SddIntegrationOutcome(
        SddIntegrationStatus.TIMED_OUT,
        upstream_present=upstream_present,
        error=f"git timed out: {detail}",
    )


def integrate_sdd_repository_transaction(
    repo_root: Path,
    *,
    beads_dir: Path | None = None,
    upstream: str = "@{upstream}",
    fetch: bool = True,
    fetch_remote: str = "origin",
    expected_branch: str | None = None,
    op_prefix: str = "sdd.integrate",
    git_runner: GitRunner,
    lock_factory: LockFactory | None = None,
    event_logger: EventLogger | None = None,
) -> SddIntegrationOutcome:
    """Implement one transactional fetch/rebase attempt.

    Network fetch deliberately happens before the cooperative store write lock.
    The lock then covers health inspection, ancestry checks, rebase, semantic
    bead repair, continuation, and rollback verification.
    """
    root = repo_root.expanduser().resolve()
    if lock_factory is None:
        from sase.sdd._git_contention import store_git_write_lock_factory

        lock_factory = store_git_write_lock_factory(
            op=f"{op_prefix}.transaction",
            mutates_worktree=True,
        )

    # A read-only preflight prevents a known-poisoned checkout from having even
    # its remote-tracking refs changed by fetch. State is checked again under
    # the write lock because another actor may start an operation afterward.
    try:
        preflight = inspect_sdd_repository(root, git_runner)
    except (SddGitCommandTimeout, SddRepositoryInspectionTimeout) as exc:
        return _timed_out_outcome(
            f"could not inspect SDD repository {root}: {safe_git_error_text(exc)}"
        )
    except Exception as exc:  # noqa: BLE001 - returned as a typed outcome
        return SddIntegrationOutcome(
            SddIntegrationStatus.UNRECOVERABLE,
            error=f"could not inspect SDD repository {root}: {safe_git_error_text(exc)}",
        )
    preflight_blockers = sdd_state_blockers(preflight, expected_branch)
    if preflight_blockers:
        return SddIntegrationOutcome(
            SddIntegrationStatus.UNRECOVERABLE,
            error=health_error(root, preflight_blockers),
        )

    fetch_failure: str | None = None
    if fetch:
        try:
            fetched = git_runner(
                root,
                ["fetch", "--prune", fetch_remote or "origin"],
                op=f"{op_prefix}.fetch",
                network=True,
            )
        except SddGitCommandTimeout as exc:
            fetch_failure = f"git fetch timed out: {exc}"
        else:
            if is_git_timeout(fetched):
                detail = (fetched.stderr or fetched.stdout or "").strip()
                suffix = f": {detail}" if detail else ""
                fetch_failure = f"git fetch timed out{suffix}"
            elif fetched.returncode != 0:
                fetch_failure = format_git_error("git fetch failed", fetched)

    with lock_factory(root) as acquired:
        if not acquired:
            # Contention says another cooperating writer is busy, not that this
            # checkout is broken. Reporting UNRECOVERABLE here would authorize
            # destructive machine-managed recovery against a healthy clone.
            return SddIntegrationOutcome(
                SddIntegrationStatus.LOCK_UNAVAILABLE,
                error=(
                    f"SDD repository {root} could not acquire its store write "
                    "lock; retry after the active writer finishes"
                ),
            )
        try:
            starting = inspect_sdd_repository(root, git_runner)
        except (SddGitCommandTimeout, SddRepositoryInspectionTimeout) as exc:
            return _timed_out_outcome(
                f"could not inspect SDD repository {root}: {safe_git_error_text(exc)}"
            )
        except Exception as exc:  # noqa: BLE001 - returned as a typed outcome
            return SddIntegrationOutcome(
                SddIntegrationStatus.UNRECOVERABLE,
                error=f"could not inspect SDD repository {root}: {safe_git_error_text(exc)}",
            )

        try:
            blockers = sdd_state_blockers(starting, expected_branch)
            if blockers:
                return SddIntegrationOutcome(
                    SddIntegrationStatus.UNRECOVERABLE,
                    error=health_error(root, blockers),
                )

            if fetch_failure is not None:
                return SddIntegrationOutcome(
                    SddIntegrationStatus.REMOTE_UNAVAILABLE,
                    error=fetch_failure,
                )

            try:
                upstream_result = git_runner(
                    root,
                    ["rev-parse", "--verify", upstream],
                    op=f"{op_prefix}.upstream",
                )
            except SddGitCommandTimeout as exc:
                return _timed_out_outcome(str(exc))
            if is_git_timeout(upstream_result):
                detail = (
                    upstream_result.stderr or upstream_result.stdout or ""
                ).strip()
                return _timed_out_outcome(
                    detail or f"could not verify upstream {upstream}"
                )
            if upstream_result.returncode != 0:
                return SddIntegrationOutcome(SddIntegrationStatus.SUCCESS)

            try:
                clean_error = tracked_changes_error(root, git_runner, op_prefix)
            except SddGitCommandTimeout as exc:
                return _timed_out_outcome(str(exc), upstream_present=True)
            if clean_error is not None:
                return SddIntegrationOutcome(
                    SddIntegrationStatus.LOCAL_CHANGES,
                    upstream_present=True,
                    error=clean_error,
                )

            try:
                ancestor = git_runner(
                    root,
                    ["merge-base", "--is-ancestor", upstream, "HEAD"],
                    op=f"{op_prefix}.ancestor",
                )
            except SddGitCommandTimeout as exc:
                return _timed_out_outcome(str(exc), upstream_present=True)
            if is_git_timeout(ancestor):
                detail = (ancestor.stderr or ancestor.stdout or "").strip()
                return _timed_out_outcome(
                    detail or "could not compare SDD histories",
                    upstream_present=True,
                )
            if ancestor.returncode == 0:
                return successful_integration(
                    root,
                    starting,
                    git_runner,
                    beads_dir=beads_dir,
                    upstream=upstream,
                    upstream_present=True,
                    integrated=False,
                    repaired=False,
                    resolved_files=(),
                    op_prefix=op_prefix,
                    event_logger=event_logger,
                )
            if ancestor.returncode != 1:
                return SddIntegrationOutcome(
                    SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS,
                    upstream_present=True,
                    restored=True,
                    error=format_git_error("could not compare SDD histories", ancestor),
                )

            try:
                rebased = git_runner(
                    root,
                    ["rebase", upstream],
                    op=f"{op_prefix}.rebase",
                )
            except SddGitCommandTimeout as exc:
                return abort_and_verify(
                    root,
                    starting=starting,
                    primary_failure=f"git operation timed out: {exc}",
                    runner=git_runner,
                    op_prefix=op_prefix,
                    timed_out=True,
                )
            if is_git_timeout(rebased):
                detail = (rebased.stderr or rebased.stdout or "").strip()
                return abort_and_verify(
                    root,
                    starting=starting,
                    primary_failure=(
                        f"git timed out: {detail}" if detail else "git rebase timed out"
                    ),
                    runner=git_runner,
                    op_prefix=op_prefix,
                    timed_out=True,
                )
            if rebased.returncode == 0:
                return successful_integration(
                    root,
                    starting,
                    git_runner,
                    beads_dir=beads_dir,
                    upstream=upstream,
                    upstream_present=True,
                    integrated=True,
                    repaired=False,
                    resolved_files=(),
                    op_prefix=op_prefix,
                    event_logger=event_logger,
                )

            return repair_or_abort_rebase(
                root,
                beads_dir=beads_dir,
                upstream=upstream,
                starting=starting,
                primary_failure=format_git_error("git rebase failed", rebased),
                runner=git_runner,
                op_prefix=op_prefix,
                event_logger=event_logger,
            )
        except SddGitCommandTimeout as exc:
            # A deadline timeout mid-rebase must not leave the checkout
            # wedged: abort the in-progress operation and verify the rollback
            # to the locked starting state, mirroring every other failure.
            try:
                return abort_and_verify(
                    root,
                    starting=starting,
                    primary_failure=f"git operation timed out: {exc}",
                    runner=git_runner,
                    op_prefix=op_prefix,
                    timed_out=True,
                )
            except SddGitCommandTimeout as abort_exc:
                return SddIntegrationOutcome(
                    SddIntegrationStatus.UNRECOVERABLE,
                    upstream_present=True,
                    error=(
                        f"git operation timed out: {exc}; "
                        f"rollback also timed out: {abort_exc}"
                    ),
                )
