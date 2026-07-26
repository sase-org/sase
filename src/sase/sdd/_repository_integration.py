"""Transactional fetch/rebase integration for SDD repositories."""

from __future__ import annotations

import logging
from pathlib import Path

from sase.sdd._repository_health import (
    format_git_error,
    health_error,
    inspect_sdd_repository,
    safe_git_error_text,
    sdd_rollback_mismatch,
    sdd_rollback_observation_delta,
    sdd_state_blockers,
    tracked_changes_error,
    unmerged_paths,
)
from sase.sdd._repository_types import (
    EventLogger,
    GitRunner,
    LockFactory,
    SddIntegrationOutcome,
    SddIntegrationStatus,
    SddRepositoryState,
)

_logger = logging.getLogger(__name__)


def integrate_sdd_repository_transaction(
    repo_root: Path,
    *,
    beads_dir: Path | None = None,
    upstream: str = "@{upstream}",
    fetch: bool = True,
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
        fetched = git_runner(
            root,
            ["fetch", "--prune", "origin"],
            op=f"{op_prefix}.fetch",
            network=True,
        )
        if fetched.returncode != 0:
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
        except Exception as exc:  # noqa: BLE001 - returned as a typed outcome
            return SddIntegrationOutcome(
                SddIntegrationStatus.UNRECOVERABLE,
                error=f"could not inspect SDD repository {root}: {safe_git_error_text(exc)}",
            )

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

        upstream_result = git_runner(
            root,
            ["rev-parse", "--verify", upstream],
            op=f"{op_prefix}.upstream",
        )
        if upstream_result.returncode != 0:
            return SddIntegrationOutcome(SddIntegrationStatus.SUCCESS)

        clean_error = tracked_changes_error(root, git_runner, op_prefix)
        if clean_error is not None:
            return SddIntegrationOutcome(
                SddIntegrationStatus.LOCAL_CHANGES,
                upstream_present=True,
                error=clean_error,
            )

        ancestor = git_runner(
            root,
            ["merge-base", "--is-ancestor", upstream, "HEAD"],
            op=f"{op_prefix}.ancestor",
        )
        if ancestor.returncode == 0:
            return _successful_integration(
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

        rebased = git_runner(
            root,
            ["rebase", upstream],
            op=f"{op_prefix}.rebase",
        )
        if rebased.returncode == 0:
            return _successful_integration(
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

        return _repair_or_abort_rebase(
            root,
            beads_dir=beads_dir,
            upstream=upstream,
            starting=starting,
            primary_failure=format_git_error("git rebase failed", rebased),
            runner=git_runner,
            op_prefix=op_prefix,
            event_logger=event_logger,
        )


def _repair_or_abort_rebase(
    repo_root: Path,
    *,
    beads_dir: Path | None,
    upstream: str,
    starting: SddRepositoryState,
    primary_failure: str,
    runner: GitRunner,
    op_prefix: str,
    event_logger: EventLogger | None,
) -> SddIntegrationOutcome:
    from sase.bead.conflict_resolver import resolve_bead_conflicts

    resolved: list[str] = []
    for _ in range(100):
        conflicts = unmerged_paths(repo_root, runner, op_prefix)
        if conflicts.error is not None:
            # "Could not tell" must never be mistaken for "no conflicts": that
            # is what let an unstaged resolution reach ``rebase --continue``.
            # Abort to the starting state, but name the probe failure.
            return _abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=(
                    f"{primary_failure}; could not determine whether conflicts "
                    f"remain: {conflicts.error}"
                ),
                runner=runner,
                op_prefix=op_prefix,
            )
        if not conflicts.paths:
            return _abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=primary_failure,
                runner=runner,
                op_prefix=op_prefix,
            )
        try:
            resolution = resolve_bead_conflicts(repo_root, beads_dir=beads_dir)
        except Exception as exc:  # noqa: BLE001 - rollback owns the error
            message = (
                f"semantic bead conflict resolution failed: {safe_git_error_text(exc)}"
            )
            _emit_resolution(event_logger, False, message, ())
            return _abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=f"{primary_failure}; {message}",
                runner=runner,
                op_prefix=op_prefix,
            )
        _emit_resolution(
            event_logger,
            resolution.ok,
            resolution.message,
            resolution.resolved_files,
        )
        if not resolution.ok:
            return _abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=f"{primary_failure}; {resolution.message}",
                runner=runner,
                op_prefix=op_prefix,
            )
        resolved.extend(resolution.resolved_files)

        continued = runner(
            repo_root,
            ["-c", "core.editor=true", "rebase", "--continue"],
            op=f"{op_prefix}.rebase_continue",
        )
        if continued.returncode == 0:
            return _successful_integration(
                repo_root,
                starting,
                runner,
                beads_dir=beads_dir,
                upstream=upstream,
                upstream_present=True,
                integrated=True,
                repaired=True,
                resolved_files=tuple(sorted(dict.fromkeys(resolved))),
                op_prefix=op_prefix,
                event_logger=event_logger,
            )
        primary_failure = format_git_error("git rebase --continue failed", continued)

    return _abort_and_verify(
        repo_root,
        starting=starting,
        primary_failure="too many rebase conflict rounds",
        runner=runner,
        op_prefix=op_prefix,
    )


def _successful_integration(
    repo_root: Path,
    starting: SddRepositoryState,
    runner: GitRunner,
    *,
    beads_dir: Path | None,
    upstream: str,
    upstream_present: bool,
    integrated: bool,
    repaired: bool,
    resolved_files: tuple[str, ...],
    op_prefix: str,
    event_logger: EventLogger | None,
) -> SddIntegrationOutcome:
    from sase.sdd._bead_manifest_repair import (
        repair_event_manifest_after_integration,
    )

    manifest_repaired, manifest_files, manifest_error = (
        repair_event_manifest_after_integration(
            repo_root,
            beads_dir=beads_dir,
            runner=runner,
            op_prefix=op_prefix,
            event_logger=event_logger,
        )
    )
    if manifest_error is not None:
        return _abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=manifest_error,
            runner=runner,
            op_prefix=op_prefix,
        )
    repaired = repaired or manifest_repaired
    integrated = integrated or manifest_repaired
    resolved_files = tuple(sorted(dict.fromkeys((*resolved_files, *manifest_files))))

    ancestor = runner(
        repo_root,
        ["merge-base", "--is-ancestor", upstream, "HEAD"],
        op=f"{op_prefix}.verify_ancestor",
    )
    if ancestor.returncode != 0:
        return _abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=format_git_error(
                "completed SDD integration does not contain upstream", ancestor
            ),
            runner=runner,
            op_prefix=op_prefix,
        )

    try:
        final = inspect_sdd_repository(repo_root, runner)
    except Exception as exc:  # noqa: BLE001 - attempt rollback below
        return _abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=f"could not verify completed rebase: {safe_git_error_text(exc)}",
            runner=runner,
            op_prefix=op_prefix,
        )
    if final.blockers or final.branch != starting.branch:
        detail = ", ".join(final.blockers) or (
            f"branch changed from {starting.branch!r} to {final.branch!r}"
        )
        return _abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=f"rebase left an unsafe repository: {detail}",
            runner=runner,
            op_prefix=op_prefix,
        )
    if final.status_porcelain != starting.status_porcelain:
        return _abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure="rebase changed the pre-existing worktree or index state",
            runner=runner,
            op_prefix=op_prefix,
        )
    dirty_error = tracked_changes_error(repo_root, runner, op_prefix)
    if dirty_error is not None:
        return _abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=(
                f"completed SDD integration left repository changes: {dirty_error}"
            ),
            runner=runner,
            op_prefix=op_prefix,
        )
    return SddIntegrationOutcome(
        (
            SddIntegrationStatus.REPAIRED_BEAD_CONFLICTS
            if repaired
            else SddIntegrationStatus.SUCCESS
        ),
        integrated=integrated,
        upstream_present=upstream_present,
        resolved_files=resolved_files,
    )


def _abort_and_verify(
    repo_root: Path,
    *,
    starting: SddRepositoryState,
    primary_failure: str,
    runner: GitRunner,
    op_prefix: str,
) -> SddIntegrationOutcome:
    abort_failure: str | None = None
    current: SddRepositoryState | None = None
    try:
        current = inspect_sdd_repository(repo_root, runner)
        rebase_active = any(marker == "rebase" for marker in current.operation_markers)
    except Exception:
        rebase_active = True
    if rebase_active:
        aborted = runner(
            repo_root,
            ["rebase", "--abort"],
            op=f"{op_prefix}.rebase_abort",
        )
        if aborted.returncode != 0:
            abort_failure = format_git_error("git rebase --abort failed", aborted)
    elif (
        current is not None
        and current.branch == starting.branch
        and starting.head is not None
        and sdd_rollback_mismatch(starting, current) is not None
    ):
        restored = runner(
            repo_root,
            ["reset", "--hard", starting.head],
            op=f"{op_prefix}.rollback_reset",
        )
        if restored.returncode != 0:
            abort_failure = format_git_error(
                "git reset failed while restoring completed integration", restored
            )

    verify_failure: str | None
    observation_delta: str | None = None
    try:
        final = inspect_sdd_repository(repo_root, runner)
    except Exception as exc:  # noqa: BLE001 - restoration cannot be proven
        verify_failure = f"could not inspect rollback state: {safe_git_error_text(exc)}"
    else:
        verify_failure = sdd_rollback_mismatch(starting, final)
        observation_delta = sdd_rollback_observation_delta(starting, final)

    if verify_failure is None and observation_delta is not None:
        _logger.warning(
            "SDD rollback restored SASE-owned repository invariants in %s, but %s",
            repo_root,
            observation_delta,
        )

    error_parts = [primary_failure]
    if abort_failure is not None:
        error_parts.append(abort_failure)
    if verify_failure is not None:
        error_parts.append(f"rollback verification failed: {verify_failure}")
    error = "; ".join(error_parts)
    if verify_failure is not None:
        return SddIntegrationOutcome(
            SddIntegrationStatus.UNRECOVERABLE,
            upstream_present=True,
            error=error,
        )
    return SddIntegrationOutcome(
        SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS,
        upstream_present=True,
        restored=True,
        error=error,
    )


def _emit_resolution(
    logger: EventLogger | None,
    ok: bool,
    message: str,
    resolved_files: tuple[str, ...],
) -> None:
    if logger is not None:
        logger(
            "conflict_resolution",
            ok=ok,
            message=message,
            resolved_files=list(resolved_files),
        )
