"""Semantic conflict repair loop for SDD repository integration."""

from __future__ import annotations

from pathlib import Path

from sase.sdd._git import SddGitCommandTimeout
from sase.sdd._repository_health import (
    format_git_error,
    safe_git_error_text,
    unmerged_paths,
)
from sase.sdd._repository_integration_verify import (
    abort_and_verify,
    successful_integration,
)
from sase.sdd._repository_types import (
    BeadIdRelocation,
    EventLogger,
    GitRunner,
    SddIntegrationOutcome,
    SddRepositoryState,
    is_git_timeout,
)


def repair_or_abort_rebase(
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
    from sase.bead.relocation import compose_bead_relocations
    from sase.sdd._semantic_conflict_resolver import resolve_semantic_conflicts

    resolved: list[str] = []
    bead_relocations: tuple[BeadIdRelocation, ...] = ()
    for _ in range(100):
        try:
            conflicts = unmerged_paths(repo_root, runner, op_prefix)
        except SddGitCommandTimeout as exc:
            return abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=f"{primary_failure}; git timed out: {exc}",
                runner=runner,
                op_prefix=op_prefix,
                timed_out=True,
            )
        if conflicts.error is not None:
            # "Could not tell" must never be mistaken for "no conflicts": that
            # is what let an unstaged resolution reach ``rebase --continue``.
            # Abort to the starting state, but name the probe failure.
            return abort_and_verify(
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
            return abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=primary_failure,
                runner=runner,
                op_prefix=op_prefix,
            )
        try:
            resolution = resolve_semantic_conflicts(repo_root, beads_dir=beads_dir)
        except Exception as exc:  # noqa: BLE001 - rollback owns the error
            message = f"semantic conflict resolution failed: {safe_git_error_text(exc)}"
            _emit_resolution(event_logger, False, message, (), ())
            return abort_and_verify(
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
            resolution.bead_relocations,
        )
        if not resolution.ok:
            return abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=f"{primary_failure}; {resolution.message}",
                runner=runner,
                op_prefix=op_prefix,
            )
        resolved.extend(resolution.resolved_files)
        bead_relocations = compose_bead_relocations(
            bead_relocations,
            resolution.bead_relocations,
        )

        try:
            continued = runner(
                repo_root,
                ["-c", "core.editor=true", "rebase", "--continue"],
                op=f"{op_prefix}.rebase_continue",
            )
        except SddGitCommandTimeout as exc:
            return abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=f"{primary_failure}; git timed out: {exc}",
                runner=runner,
                op_prefix=op_prefix,
                timed_out=True,
            )
        if is_git_timeout(continued):
            detail = (continued.stderr or continued.stdout or "").strip()
            return abort_and_verify(
                repo_root,
                starting=starting,
                primary_failure=(
                    f"{primary_failure}; git timed out: {detail}"
                    if detail
                    else f"{primary_failure}; git rebase --continue timed out"
                ),
                runner=runner,
                op_prefix=op_prefix,
                timed_out=True,
            )
        if continued.returncode == 0:
            return successful_integration(
                repo_root,
                starting,
                runner,
                beads_dir=beads_dir,
                upstream=upstream,
                upstream_present=True,
                integrated=True,
                repaired=True,
                semantic_repaired=True,
                resolved_files=tuple(sorted(dict.fromkeys(resolved))),
                bead_relocations=bead_relocations,
                op_prefix=op_prefix,
                event_logger=event_logger,
            )
        primary_failure = format_git_error("git rebase --continue failed", continued)

    return abort_and_verify(
        repo_root,
        starting=starting,
        primary_failure="too many rebase conflict rounds",
        runner=runner,
        op_prefix=op_prefix,
    )


def _emit_resolution(
    logger: EventLogger | None,
    ok: bool,
    message: str,
    resolved_files: tuple[str, ...],
    bead_relocations: tuple[BeadIdRelocation, ...],
) -> None:
    if logger is not None:
        logger(
            "conflict_resolution",
            ok=ok,
            message=message,
            resolved_files=list(resolved_files),
            bead_relocations=[
                relocation.to_json_dict() for relocation in bead_relocations
            ],
        )
