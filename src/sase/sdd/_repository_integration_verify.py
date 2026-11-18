"""Completion verification and rollback for SDD repository integration."""

from __future__ import annotations

import logging
from pathlib import Path

from sase.sdd._git import SddGitCommandTimeout
from sase.sdd._repository_health import (
    SddRepositoryInspectionTimeout,
    format_git_error,
    inspect_sdd_repository,
    safe_git_error_text,
    sdd_rollback_mismatch,
    sdd_rollback_observation_delta,
    tracked_changes_error,
)
from sase.sdd._repository_types import (
    BeadIdRelocation,
    EventLogger,
    GitRunner,
    SddIntegrationOutcome,
    SddIntegrationStatus,
    SddRepositoryState,
    is_git_timeout,
)

_logger = logging.getLogger(__name__)


def successful_integration(
    repo_root: Path,
    starting: SddRepositoryState,
    runner: GitRunner,
    *,
    beads_dir: Path | None,
    upstream: str,
    upstream_present: bool,
    integrated: bool,
    repaired: bool,
    semantic_repaired: bool = False,
    resolved_files: tuple[str, ...],
    bead_relocations: tuple[BeadIdRelocation, ...] = (),
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
        return abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=manifest_error,
            runner=runner,
            op_prefix=op_prefix,
        )
    repaired = repaired or manifest_repaired
    integrated = integrated or manifest_repaired
    resolved_files = tuple(sorted(dict.fromkeys((*resolved_files, *manifest_files))))

    try:
        ancestor = runner(
            repo_root,
            ["merge-base", "--is-ancestor", upstream, "HEAD"],
            op=f"{op_prefix}.verify_ancestor",
        )
    except SddGitCommandTimeout as exc:
        return abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=f"git timed out: {exc}",
            runner=runner,
            op_prefix=op_prefix,
            timed_out=True,
        )
    if is_git_timeout(ancestor):
        detail = (ancestor.stderr or ancestor.stdout or "").strip()
        return abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=(
                f"git timed out: {detail}"
                if detail
                else "completed SDD integration verification timed out"
            ),
            runner=runner,
            op_prefix=op_prefix,
            timed_out=True,
        )
    if ancestor.returncode != 0:
        return abort_and_verify(
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
    except (SddGitCommandTimeout, SddRepositoryInspectionTimeout) as exc:
        return abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=(
                f"could not verify completed rebase: {safe_git_error_text(exc)}"
            ),
            runner=runner,
            op_prefix=op_prefix,
            timed_out=True,
        )
    except Exception as exc:  # noqa: BLE001 - attempt rollback below
        return abort_and_verify(
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
        return abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=f"rebase left an unsafe repository: {detail}",
            runner=runner,
            op_prefix=op_prefix,
        )
    if final.status_porcelain != starting.status_porcelain:
        return abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure="rebase changed the pre-existing worktree or index state",
            runner=runner,
            op_prefix=op_prefix,
        )
    try:
        dirty_error = tracked_changes_error(repo_root, runner, op_prefix)
    except SddGitCommandTimeout as exc:
        return abort_and_verify(
            repo_root,
            starting=starting,
            primary_failure=f"git timed out: {exc}",
            runner=runner,
            op_prefix=op_prefix,
            timed_out=True,
        )
    if dirty_error is not None:
        return abort_and_verify(
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
            SddIntegrationStatus.REPAIRED_SEMANTIC_CONFLICTS
            if semantic_repaired
            else SddIntegrationStatus.REPAIRED_BEAD_CONFLICTS
            if repaired
            else SddIntegrationStatus.SUCCESS
        ),
        integrated=integrated,
        upstream_present=upstream_present,
        resolved_files=resolved_files,
        bead_relocations=bead_relocations,
    )


def abort_and_verify(
    repo_root: Path,
    *,
    starting: SddRepositoryState,
    primary_failure: str,
    runner: GitRunner,
    op_prefix: str,
    timed_out: bool = False,
) -> SddIntegrationOutcome:
    from sase.sdd._deadline_git_runner import rollback_runner as _rollback_runner

    runner = _rollback_runner(runner)
    abort_failure: str | None = None
    current: SddRepositoryState | None = None
    try:
        current = inspect_sdd_repository(repo_root, runner)
        rebase_active = any(marker == "rebase" for marker in current.operation_markers)
    except Exception:
        rebase_active = True
    if rebase_active:
        try:
            aborted = runner(
                repo_root,
                ["rebase", "--abort"],
                op=f"{op_prefix}.rebase_abort",
            )
        except SddGitCommandTimeout as exc:
            abort_failure = f"git rebase --abort timed out: {exc}"
        else:
            if is_git_timeout(aborted):
                detail = (aborted.stderr or aborted.stdout or "").strip()
                abort_failure = (
                    f"git rebase --abort timed out: {detail}"
                    if detail
                    else "git rebase --abort timed out"
                )
            elif aborted.returncode != 0:
                abort_failure = format_git_error("git rebase --abort failed", aborted)
    elif (
        current is not None
        and current.branch == starting.branch
        and starting.head is not None
        and sdd_rollback_mismatch(starting, current) is not None
    ):
        try:
            restored = runner(
                repo_root,
                ["reset", "--hard", starting.head],
                op=f"{op_prefix}.rollback_reset",
            )
        except SddGitCommandTimeout as exc:
            abort_failure = f"git reset timed out while restoring integration: {exc}"
        else:
            if is_git_timeout(restored):
                detail = (restored.stderr or restored.stdout or "").strip()
                abort_failure = (
                    f"git reset timed out while restoring integration: {detail}"
                    if detail
                    else "git reset timed out while restoring integration"
                )
            elif restored.returncode != 0:
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
    if timed_out:
        return SddIntegrationOutcome(
            SddIntegrationStatus.TIMED_OUT,
            upstream_present=True,
            restored=True,
            error=error,
        )
    return SddIntegrationOutcome(
        SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS,
        upstream_present=True,
        restored=True,
        error=error,
    )
