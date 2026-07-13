"""Execution path for Agents-tab commit reverts."""

from __future__ import annotations

from collections.abc import Callable

from sase.ace.revert_agent_discovery import agent_tag_matches
from sase.ace.revert_agent_git import (
    commit_exists,
    commit_subject,
    is_git_worktree,
    worktree_is_clean,
)
from sase.ace.revert_agent_marker import write_revert_result
from sase.ace.revert_agent_models import (
    BulkRevertPreview,
    BulkRevertResult,
    RepoRevertOutcome,
    RepoRevertPlan,
    RevertCommit,
    RevertPreview,
    RevertResult,
)
from sase.ace.revert_agent_preview import ordered_matched_names
from sase.ace.revert_agent_transaction import (
    apply_revert_transaction,
    build_bulk_revert_message,
    build_revert_message,
    push_revert_commit,
    rollback_to,
    run_git_for_revert,
)
from sase.vcs_provider import get_vcs_provider


def execute_agent_revert(
    preview_or_workspace: RevertPreview | str,
    shas: tuple[str, ...] | list[str] | None = None,
    *,
    agent_name: str | None = None,
    artifacts_dir: str | None = None,
) -> RevertResult:
    """Execute a previewed single-agent revert across its repositories."""
    preview = _coerce_agent_execute_preview(
        preview_or_workspace,
        shas,
        agent_name=agent_name,
    )
    if preview is None:
        return RevertResult(False, "No commits to revert", error="no commits")

    outcomes = tuple(
        _execute_repo_plan(
            plan,
            lambda workspace_dir, ordered: build_revert_message(
                workspace_dir, preview.agent_name, ordered
            ),
        )
        for plan in preview.repos
        if plan.commits or plan.discard_local_changes
    )
    reverted_shas = _flatten_reverted_shas(outcomes)
    complete = _outcomes_complete(outcomes)
    pushed = any(outcome.pushed for outcome in outcomes)
    error = None if complete else _first_outcome_error(outcomes)
    message = _agent_result_message(preview.agent_name, outcomes)

    if artifacts_dir and (reverted_shas or _discarded_repo_count(outcomes)):
        write_revert_result(
            artifacts_dir,
            preview.agent_name,
            reverted_shas,
            repo_outcomes=outcomes,
            complete=complete,
        )

    return RevertResult(
        complete,
        message,
        reverted_shas=reverted_shas,
        pushed=pushed,
        error=error,
        repo_outcomes=outcomes,
        complete=complete,
    )


def execute_agents_revert(preview: BulkRevertPreview) -> BulkRevertResult:
    """Execute a previewed bulk revert as one transaction per repository."""
    if not preview.repos:
        return BulkRevertResult(False, "No commits to revert", error="no commits")

    matched_names = preview.matched_target_names or tuple(
        t.agent_name for t in preview.targets
    )
    outcomes = tuple(
        _execute_repo_plan(
            plan,
            lambda workspace_dir, ordered: build_bulk_revert_message(
                workspace_dir, matched_names, ordered
            ),
        )
        for plan in preview.repos
        if plan.commits or plan.discard_local_changes
    )
    reverted_shas = _flatten_reverted_shas(outcomes)
    complete = _outcomes_complete(outcomes)
    pushed = any(outcome.pushed for outcome in outcomes)
    error = None if complete else _first_outcome_error(outcomes)
    agent_names = _target_names_with_reverted_work(preview, outcomes)

    if reverted_shas or _discarded_repo_count(outcomes):
        for target in preview.targets:
            if target.artifacts_dir and target.agent_name in agent_names:
                write_revert_result(
                    target.artifacts_dir,
                    target.agent_name,
                    reverted_shas,
                    repo_outcomes=outcomes,
                    complete=complete,
                )

    return BulkRevertResult(
        complete,
        _bulk_result_message(matched_names, outcomes),
        reverted_shas=reverted_shas,
        agent_names=agent_names,
        pushed=pushed,
        error=error,
        repo_outcomes=outcomes,
        complete=complete,
    )


def _coerce_agent_execute_preview(
    preview_or_workspace: RevertPreview | str,
    shas: tuple[str, ...] | list[str] | None,
    *,
    agent_name: str | None,
) -> RevertPreview | None:
    if isinstance(preview_or_workspace, RevertPreview):
        return preview_or_workspace

    ordered = tuple(shas or ())
    if not ordered or not agent_name:
        return None
    workspace_dir = preview_or_workspace
    commits = tuple(
        RevertCommit(
            sha=sha[:12],
            full_sha=sha,
            subject=commit_subject(workspace_dir, sha),
            agent_tag=agent_name,
        )
        for sha in ordered
    )
    plan = RepoRevertPlan(
        repo_label="primary",
        workspace_dir=workspace_dir,
        is_primary=True,
        commits=commits,
    )
    return RevertPreview(
        agent_name=agent_name,
        scope="agent",
        workspace_dir=workspace_dir,
        commits=commits,
        repos=(plan,),
    )


def _execute_repo_plan(
    plan: RepoRevertPlan,
    message_builder: Callable[[str, tuple[str, ...]], str],
) -> RepoRevertOutcome:
    if plan.discard_local_changes:
        return _execute_external_cleanup(plan)

    ordered = tuple(commit.full_sha for commit in plan.commits)
    if not ordered:
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=True,
            skipped_reason="no matching commits",
        )
    if plan.blocked_reason is not None:
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            skipped_reason=plan.blocked_reason,
        )
    if not is_git_worktree(plan.workspace_dir):
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            skipped_reason="Workspace is not a git worktree (revert is git-only)",
        )

    clean = worktree_is_clean(plan.workspace_dir)
    if clean is None:
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            skipped_reason="Could not read git status for workspace",
        )
    if not clean:
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            skipped_reason="Workspace has uncommitted changes; aborting revert",
        )

    missing = [sha for sha in ordered if not commit_exists(plan.workspace_dir, sha)]
    if missing:
        short = ", ".join(sha[:9] for sha in missing)
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            skipped_reason=f"Commit(s) no longer exist: {short}",
        )

    message = message_builder(plan.workspace_dir, ordered)
    ok, detail = apply_revert_transaction(plan.workspace_dir, ordered, message)
    if not ok:
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            error=f"Revert failed and was rolled back: {detail}",
        )

    push = push_revert_commit(plan.workspace_dir)
    if push.error is not None:
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            reverted_shas=ordered,
            pushed=False,
            error=f"git push failed: {push.error}",
        )

    return RepoRevertOutcome(
        repo_label=plan.repo_label,
        workspace_dir=plan.workspace_dir,
        success=True,
        reverted_shas=ordered,
        pushed=push.pushed,
        push_skipped_reason=push.skipped_reason,
    )


def _execute_external_cleanup(plan: RepoRevertPlan) -> RepoRevertOutcome:
    """Discard changes in an existing external clone without network access."""
    if plan.blocked_reason is not None:
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            skipped_reason=plan.blocked_reason,
            repo_kind="external",
        )
    if plan.repo_kind != "external":
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            skipped_reason="Local cleanup is only supported for external repos",
        )
    if not is_git_worktree(plan.workspace_dir):
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            skipped_reason="Workspace is not a git worktree (revert is git-only)",
            repo_kind="external",
        )
    try:
        provider = get_vcs_provider(plan.workspace_dir)
        ok, error = provider.clean_workspace(plan.workspace_dir)
    except Exception as exc:
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            error=f"Could not discard local changes: {exc}",
            repo_kind="external",
        )
    if not ok:
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            error=error or "Could not discard local changes",
            repo_kind="external",
        )
    return RepoRevertOutcome(
        repo_label=plan.repo_label,
        workspace_dir=plan.workspace_dir,
        success=True,
        repo_kind="external",
        discarded_local_changes=True,
    )


def _flatten_reverted_shas(
    outcomes: tuple[RepoRevertOutcome, ...],
) -> tuple[str, ...]:
    return tuple(sha for outcome in outcomes for sha in outcome.reverted_shas)


def _outcomes_complete(outcomes: tuple[RepoRevertOutcome, ...]) -> bool:
    revert_outcomes = tuple(
        outcome
        for outcome in outcomes
        if (
            outcome.reverted_shas
            or outcome.discarded_local_changes
            or outcome.error
            or outcome.skipped_reason
        )
    )
    return bool(revert_outcomes) and all(outcome.success for outcome in revert_outcomes)


def _first_outcome_error(outcomes: tuple[RepoRevertOutcome, ...]) -> str | None:
    for outcome in outcomes:
        if outcome.error:
            return outcome.error
        if outcome.skipped_reason:
            return outcome.skipped_reason
    return "partial revert"


def _agent_result_message(
    agent_name: str,
    outcomes: tuple[RepoRevertOutcome, ...],
) -> str:
    reverted_count = len(_flatten_reverted_shas(outcomes))
    discarded_count = _discarded_repo_count(outcomes)
    successful = tuple(outcome for outcome in outcomes if outcome.success)
    failed = tuple(outcome for outcome in outcomes if not outcome.success)
    if not outcomes or reverted_count == 0 and discarded_count == 0 and not failed:
        return "No commits to revert"

    if not failed:
        repo_suffix = (
            "" if len(successful) <= 1 else f" across {len(successful)} repo(s)"
        )
        if reverted_count:
            summary = (
                f"Reverted {reverted_count} commit(s) for '{agent_name}'{repo_suffix}"
            )
        else:
            summary = f"Discarded local changes in {discarded_count} external repo(s)"
        if reverted_count and discarded_count:
            summary += (
                f"; discarded local changes in {discarded_count} external repo(s)"
            )
        summary += (
            " and pushed" if any(outcome.pushed for outcome in successful) else ""
        )
        return summary

    if (
        len(outcomes) == 1
        and reverted_count > 0
        and failed[0].error
        and failed[0].error.startswith("git push failed:")
    ):
        return (
            f"Reverted {reverted_count} commit(s) for '{agent_name}' locally, "
            f"but push to GitHub failed: {failed[0].error.removeprefix('git push failed: ')}"
        )

    detail = _format_failed_repo_summary(failed)
    if reverted_count:
        return (
            f"Partially reverted {reverted_count} commit(s) for '{agent_name}'; "
            f"{detail}"
        )
    return f"Revert failed for '{agent_name}'; {detail}"


def _bulk_result_message(
    matched_names: tuple[str, ...],
    outcomes: tuple[RepoRevertOutcome, ...],
) -> str:
    reverted_count = len(_flatten_reverted_shas(outcomes))
    discarded_count = _discarded_repo_count(outcomes)
    successful = tuple(outcome for outcome in outcomes if outcome.success)
    failed = tuple(outcome for outcome in outcomes if not outcome.success)
    agent_count = len(matched_names)
    if not outcomes or reverted_count == 0 and discarded_count == 0 and not failed:
        return "No commits to revert"

    if not failed:
        repo_suffix = "" if len(successful) <= 1 else f" in {len(successful)} repo(s)"
        if reverted_count:
            summary = (
                f"Reverted {reverted_count} commit(s) across {agent_count} "
                f"agent(s){repo_suffix}"
            )
        else:
            summary = f"Discarded local changes in {discarded_count} external repo(s)"
        if reverted_count and discarded_count:
            summary += (
                f"; discarded local changes in {discarded_count} external repo(s)"
            )
        summary += (
            " and pushed" if any(outcome.pushed for outcome in successful) else ""
        )
        return summary

    if (
        len(outcomes) == 1
        and reverted_count > 0
        and failed[0].error
        and failed[0].error.startswith("git push failed:")
    ):
        return (
            f"Reverted {reverted_count} commit(s) across {agent_count} agent(s) "
            "locally, but push to GitHub failed: "
            f"{failed[0].error.removeprefix('git push failed: ')}"
        )

    detail = _format_failed_repo_summary(failed)
    if reverted_count:
        return (
            f"Partially reverted {reverted_count} commit(s) across {agent_count} "
            f"agent(s); {detail}"
        )
    return f"Bulk revert failed for {agent_count} agent(s); {detail}"


def _format_failed_repo_summary(outcomes: tuple[RepoRevertOutcome, ...]) -> str:
    parts: list[str] = []
    for outcome in outcomes:
        reason = outcome.error or outcome.skipped_reason or "failed"
        parts.append(f"{outcome.repo_label}: {reason}")
    return "failed/skipped repo(s): " + "; ".join(parts)


def _target_names_with_reverted_work(
    preview: BulkRevertPreview,
    outcomes: tuple[RepoRevertOutcome, ...],
) -> tuple[str, ...]:
    reverted_by_repo = {
        (outcome.repo_label, outcome.workspace_dir): set(outcome.reverted_shas)
        for outcome in outcomes
        if outcome.reverted_shas
    }
    discarded_by_repo = {
        (outcome.repo_label, outcome.workspace_dir)
        for outcome in outcomes
        if outcome.discarded_local_changes
    }

    matched: set[str] = set()
    for plan in preview.repos:
        if (plan.repo_label, plan.workspace_dir) in discarded_by_repo:
            matched.update(plan.source_agent_names)
        reverted = reverted_by_repo.get((plan.repo_label, plan.workspace_dir))
        if not reverted:
            continue
        for commit in plan.commits:
            if commit.full_sha not in reverted:
                continue
            for target in preview.targets:
                if agent_tag_matches(
                    commit.agent_tag,
                    target.agent_name,
                    target.family_base,
                ):
                    matched.add(target.agent_name)
    return ordered_matched_names(preview.targets, matched)


def _discarded_repo_count(outcomes: tuple[RepoRevertOutcome, ...]) -> int:
    return sum(outcome.discarded_local_changes for outcome in outcomes)


_target_names_with_reverted_commits = _target_names_with_reverted_work


_apply_revert_transaction = apply_revert_transaction
_build_bulk_revert_message = build_bulk_revert_message
_build_revert_message = build_revert_message
_push_revert_commit = push_revert_commit
_rollback_to = rollback_to
_run_git = run_git_for_revert


__all__ = [
    "_agent_result_message",
    "_apply_revert_transaction",
    "_build_bulk_revert_message",
    "_build_revert_message",
    "_bulk_result_message",
    "_coerce_agent_execute_preview",
    "_execute_repo_plan",
    "_first_outcome_error",
    "_flatten_reverted_shas",
    "_format_failed_repo_summary",
    "_outcomes_complete",
    "_push_revert_commit",
    "_rollback_to",
    "_run_git",
    "_target_names_with_reverted_commits",
    "execute_agent_revert",
    "execute_agents_revert",
]
