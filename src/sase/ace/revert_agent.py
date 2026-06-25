"""Backend for reverting commits associated with done agents.

Powers the Agents-tab leader ``,r`` action. Commits are associated with an
agent by the exact ``AGENT=<name>`` provenance tag written into commit messages
(see :mod:`sase.workflows.commit.runtime_tags`). This is git-only: non-git
workspaces fail with an explicit unsupported message rather than reusing
ChangeSpec prune/abandon semantics.

The flow is two-phase so the TUI can confirm before mutating anything:

1. :func:`preview_agent_revert` discovers candidate commits newest-first across
   the primary workspace and eligible linked workspaces.
2. :func:`execute_agent_revert` re-validates each repository, applies
   ``git revert --no-commit`` for that repo's previewed SHAs, creates one
   revert commit per repository, and pushes each repo when an ``origin`` remote
   and branch are available.

A parallel *bulk* path (:func:`preview_agents_revert` /
:func:`execute_agents_revert`) reverts the combined commit set of several
marked agents with the same per-repository transaction semantics.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.ace.revert_agent_discovery import (
    agent_tag_matches,
    discover_agent_commits as _discover_agent_commits,
    discover_bulk_commits as _discover_bulk_commits,
)
from sase.ace.revert_agent_git import (
    commit_exists,
    commit_subject,
    current_head,
    is_git_worktree,
    run_git as _run_git,
    worktree_is_clean,
)
from sase.ace.revert_agent_models import (
    BulkRevertPreview,
    BulkRevertResult,
    RepoRevertOutcome,
    RepoRevertPlan,
    RevertCommit,
    RevertPreview,
    RevertRepo,
    RevertResult,
    RevertTarget,
)
from sase.ace.revert_agent_resolution import (
    resolve_revert_agent_name,
    resolve_revert_family_base,
    resolve_revert_repos,
    resolve_revert_repos_for_agents,
    resolve_revert_workspace_dir,
)

_REVERT_RESULT_FILENAME = "revert_result.json"


@dataclass(frozen=True)
class _PushOutcome:
    """Result of attempting to push a revert commit to ``origin``.

    Distinguishes three outcomes the old ``bool`` return collapsed: a skipped
    push (no remote/branch, ``attempted=False``), a successful push
    (``pushed=True``), and a failed push to an available remote (``error`` set).
    """

    attempted: bool
    pushed: bool
    skipped_reason: str | None = None
    error: str | None = None


def agent_is_reverted(artifacts_dir: str | None) -> bool:
    """Return True when an agent artifacts dir carries a persisted revert marker."""
    if not artifacts_dir:
        return False
    try:
        return (Path(artifacts_dir) / _REVERT_RESULT_FILENAME).is_file()
    except OSError:
        return False


def preview_agent_revert(
    repos: Sequence[RevertRepo] | str | None,
    agent_name: str,
    *,
    family_base: str | None = None,
) -> RevertPreview:
    """Discover per-repository commits to revert for one agent."""
    scope = "family" if family_base else "agent"
    repo_tuple = _coerce_revert_repos(repos)
    workspace_dir = _primary_workspace_dir(repo_tuple)

    def _fail(error: str, plans: tuple[RepoRevertPlan, ...] = ()) -> RevertPreview:
        return RevertPreview(
            agent_name=agent_name,
            scope=scope,
            workspace_dir=workspace_dir,
            commits=_flatten_revertable_commits(plans),
            repos=plans,
            error=error,
        )

    if not repo_tuple:
        return _fail("No workspace directory for agent")

    plans = tuple(
        _preview_agent_repo(repo, agent_name, family_base=family_base)
        for repo in repo_tuple
    )
    commits = _flatten_revertable_commits(plans)
    if not commits:
        error = _preview_empty_error(
            plans,
            f"family '{family_base}'" if family_base else f"agent '{agent_name}'",
        )
        return _fail(error, plans)

    return RevertPreview(
        agent_name=agent_name,
        scope=scope,
        workspace_dir=workspace_dir,
        commits=commits,
        repos=plans,
    )


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
            lambda workspace_dir, ordered: _build_revert_message(
                workspace_dir, preview.agent_name, ordered
            ),
        )
        for plan in preview.repos
        if plan.commits
    )
    reverted_shas = _flatten_reverted_shas(outcomes)
    complete = _outcomes_complete(outcomes)
    pushed = any(outcome.pushed for outcome in outcomes)
    error = None if complete else _first_outcome_error(outcomes)
    message = _agent_result_message(preview.agent_name, outcomes)

    if artifacts_dir and reverted_shas:
        _write_revert_result(
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


def preview_agents_revert(
    targets: Sequence[RevertTarget],
    repos: Sequence[RevertRepo] | str | None = None,
) -> BulkRevertPreview:
    """Discover per-repository commits to revert for marked agents.

    Marked agents must still share one primary workspace. Linked repositories
    are handled as independent per-repo revert transactions.
    """
    target_tuple = tuple(targets)
    workspace_dir = target_tuple[0].workspace_dir if target_tuple else ""

    def _fail(
        error: str,
        plans: tuple[RepoRevertPlan, ...] = (),
        matched: set[str] | None = None,
    ) -> BulkRevertPreview:
        matched_names = _ordered_matched_names(target_tuple, matched or set())
        skipped_names = tuple(
            t.agent_name for t in target_tuple if t.agent_name not in matched_names
        )
        return BulkRevertPreview(
            workspace_dir=workspace_dir,
            targets=target_tuple,
            commits=_flatten_revertable_commits(plans),
            repos=plans,
            matched_target_names=matched_names,
            skipped_target_names=skipped_names,
            error=error,
        )

    if not target_tuple:
        return _fail("No agents to revert")

    workspaces = {t.workspace_dir for t in target_tuple}
    if len(workspaces) > 1:
        return _fail("Marked agents span multiple workspaces; no changes were applied")

    if not workspace_dir:
        return _fail("No workspace directory for marked agents")

    repo_tuple = _coerce_revert_repos(repos)
    if not repo_tuple:
        repo_tuple = (RevertRepo("primary", workspace_dir, is_primary=True),)

    previewed = tuple(_preview_bulk_repo(repo, target_tuple) for repo in repo_tuple)
    plans = tuple(plan for plan, _matched in previewed)
    matched = set().union(*(repo_matched for _plan, repo_matched in previewed))
    commits = _flatten_revertable_commits(plans)
    if not commits:
        return _fail(
            _preview_empty_error(plans, "the marked agents"),
            plans,
            matched,
        )

    matched_names = _ordered_matched_names(target_tuple, matched)
    skipped_names = tuple(
        t.agent_name for t in target_tuple if t.agent_name not in matched_names
    )

    return BulkRevertPreview(
        workspace_dir=workspace_dir,
        targets=target_tuple,
        commits=commits,
        repos=plans,
        matched_target_names=matched_names,
        skipped_target_names=skipped_names,
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
            lambda workspace_dir, ordered: _build_bulk_revert_message(
                workspace_dir, matched_names, ordered
            ),
        )
        for plan in preview.repos
        if plan.commits
    )
    reverted_shas = _flatten_reverted_shas(outcomes)
    complete = _outcomes_complete(outcomes)
    pushed = any(outcome.pushed for outcome in outcomes)
    error = None if complete else _first_outcome_error(outcomes)
    agent_names = _target_names_with_reverted_commits(preview, outcomes)

    if reverted_shas:
        for target in preview.targets:
            if target.artifacts_dir and target.agent_name in agent_names:
                _write_revert_result(
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


def _coerce_revert_repos(
    repos: Sequence[RevertRepo] | str | None,
) -> tuple[RevertRepo, ...]:
    if repos is None:
        return ()
    if isinstance(repos, str):
        if not repos:
            return ()
        return (RevertRepo(label="primary", workspace_dir=repos, is_primary=True),)
    return tuple(repos)


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


def _primary_workspace_dir(repos: tuple[RevertRepo, ...]) -> str:
    for repo in repos:
        if repo.is_primary:
            return repo.workspace_dir
    return repos[0].workspace_dir if repos else ""


def _preview_agent_repo(
    repo: RevertRepo,
    agent_name: str,
    *,
    family_base: str | None,
) -> RepoRevertPlan:
    if not repo.workspace_dir:
        return _blocked_repo_plan(repo, (), "No workspace directory")
    if not is_git_worktree(repo.workspace_dir):
        return _blocked_repo_plan(
            repo,
            (),
            "Workspace is not a git worktree (revert is git-only)",
        )

    commits = tuple(
        _discover_agent_commits(
            repo.workspace_dir,
            agent_name,
            family_base=family_base,
        )
    )
    blocked = _repo_blocked_reason(repo.workspace_dir, commits)
    return RepoRevertPlan(
        repo_label=repo.label,
        workspace_dir=repo.workspace_dir,
        is_primary=repo.is_primary,
        commits=commits,
        blocked_reason=blocked,
    )


def _preview_bulk_repo(
    repo: RevertRepo,
    targets: tuple[RevertTarget, ...],
) -> tuple[RepoRevertPlan, set[str]]:
    if not repo.workspace_dir:
        return _blocked_repo_plan(repo, (), "No workspace directory"), set()
    if not is_git_worktree(repo.workspace_dir):
        return (
            _blocked_repo_plan(
                repo,
                (),
                "Workspace is not a git worktree (revert is git-only)",
            ),
            set(),
        )

    commits, matched = _discover_bulk_commits(repo.workspace_dir, targets)
    commit_tuple = tuple(commits)
    blocked = _repo_blocked_reason(repo.workspace_dir, commit_tuple)
    return (
        RepoRevertPlan(
            repo_label=repo.label,
            workspace_dir=repo.workspace_dir,
            is_primary=repo.is_primary,
            commits=commit_tuple,
            blocked_reason=blocked,
        ),
        matched,
    )


def _repo_blocked_reason(
    workspace_dir: str,
    commits: tuple[RevertCommit, ...],
) -> str | None:
    if not commits:
        return None

    clean = worktree_is_clean(workspace_dir)
    if clean is None:
        return "Could not read git status for workspace"
    if not clean:
        return "Workspace has uncommitted changes; commit or discard them first"

    missing = [
        commit.full_sha
        for commit in commits
        if not commit_exists(workspace_dir, commit.full_sha)
    ]
    if missing:
        short = ", ".join(sha[:9] for sha in missing)
        return f"Commit(s) no longer exist: {short}"
    return None


def _blocked_repo_plan(
    repo: RevertRepo,
    commits: tuple[RevertCommit, ...],
    reason: str,
) -> RepoRevertPlan:
    return RepoRevertPlan(
        repo_label=repo.label,
        workspace_dir=repo.workspace_dir,
        is_primary=repo.is_primary,
        commits=commits,
        blocked_reason=reason,
    )


def _flatten_revertable_commits(
    plans: tuple[RepoRevertPlan, ...],
) -> tuple[RevertCommit, ...]:
    return tuple(commit for plan in plans if plan.revertable for commit in plan.commits)


def _preview_empty_error(plans: tuple[RepoRevertPlan, ...], target: str) -> str:
    blocked_with_commits = [
        plan for plan in plans if plan.blocked_reason is not None and plan.commits
    ]
    if blocked_with_commits:
        plan = blocked_with_commits[0]
        return f"{plan.repo_label}: {plan.blocked_reason}"

    blocked_without_commits = [
        plan for plan in plans if plan.blocked_reason is not None
    ]
    if blocked_without_commits and not any(plan.commits for plan in plans):
        return blocked_without_commits[0].blocked_reason or "Repository is blocked"

    return f"No commits tagged for {target} were found"


def _execute_repo_plan(
    plan: RepoRevertPlan,
    message_builder: Callable[[str, tuple[str, ...]], str],
) -> RepoRevertOutcome:
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
    ok, detail = _apply_revert_transaction(plan.workspace_dir, ordered, message)
    if not ok:
        return RepoRevertOutcome(
            repo_label=plan.repo_label,
            workspace_dir=plan.workspace_dir,
            success=False,
            error=f"Revert failed and was rolled back: {detail}",
        )

    push = _push_revert_commit(plan.workspace_dir)
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


def _flatten_reverted_shas(
    outcomes: tuple[RepoRevertOutcome, ...],
) -> tuple[str, ...]:
    return tuple(sha for outcome in outcomes for sha in outcome.reverted_shas)


def _outcomes_complete(outcomes: tuple[RepoRevertOutcome, ...]) -> bool:
    revert_outcomes = tuple(
        outcome
        for outcome in outcomes
        if outcome.reverted_shas or outcome.error or outcome.skipped_reason
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
    successful = tuple(outcome for outcome in outcomes if outcome.success)
    failed = tuple(outcome for outcome in outcomes if not outcome.success)
    if not outcomes or reverted_count == 0 and not failed:
        return "No commits to revert"

    if not failed:
        repo_suffix = (
            "" if len(successful) <= 1 else f" across {len(successful)} repo(s)"
        )
        summary = f"Reverted {reverted_count} commit(s) for '{agent_name}'{repo_suffix}"
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
    successful = tuple(outcome for outcome in outcomes if outcome.success)
    failed = tuple(outcome for outcome in outcomes if not outcome.success)
    agent_count = len(matched_names)
    if not outcomes or reverted_count == 0 and not failed:
        return "No commits to revert"

    if not failed:
        repo_suffix = "" if len(successful) <= 1 else f" in {len(successful)} repo(s)"
        summary = (
            f"Reverted {reverted_count} commit(s) across {agent_count} "
            f"agent(s){repo_suffix}"
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


def _ordered_matched_names(
    targets: tuple[RevertTarget, ...],
    matched: set[str],
) -> tuple[str, ...]:
    return tuple(t.agent_name for t in targets if t.agent_name in matched)


def _target_names_with_reverted_commits(
    preview: BulkRevertPreview,
    outcomes: tuple[RepoRevertOutcome, ...],
) -> tuple[str, ...]:
    reverted_by_repo = {
        (outcome.repo_label, outcome.workspace_dir): set(outcome.reverted_shas)
        for outcome in outcomes
        if outcome.reverted_shas
    }
    if not reverted_by_repo:
        return ()

    matched: set[str] = set()
    for plan in preview.repos:
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
    return _ordered_matched_names(preview.targets, matched)


def _apply_revert_transaction(
    workspace_dir: str,
    ordered_shas: tuple[str, ...],
    message: str,
) -> tuple[bool, str | None]:
    """Revert *ordered_shas* (newest-first) as one commit, atomically.

    Captures ``HEAD`` first, applies ``git revert --no-commit`` for every SHA,
    then creates a single commit. On any failure the worktree is rolled back to
    the captured ``HEAD`` via :func:`_rollback_to`. Returns ``(success,
    error_detail)``; ``error_detail`` is ``None`` on success.
    """
    head_before = current_head(workspace_dir)

    revert = _run_git(
        workspace_dir, ["revert", "--no-commit", "--no-edit", *ordered_shas]
    )
    if revert.returncode != 0:
        detail = (revert.stderr or revert.stdout or "git revert failed").strip()
        _rollback_to(workspace_dir, head_before)
        return False, detail

    commit = _run_git(workspace_dir, ["commit", "--no-verify", "-m", message])
    if commit.returncode != 0:
        detail = (commit.stderr or commit.stdout or "git commit failed").strip()
        _rollback_to(workspace_dir, head_before)
        return False, detail

    return True, None


def _rollback_to(workspace_dir: str, head_before: str | None) -> None:
    """Best-effort restore the worktree to its pre-operation state.

    Aborts any in-progress revert sequence first, then if the worktree was
    dirtied or ``HEAD`` advanced past the captured commit, force-resets back to
    it. Because callers require a clean-worktree precondition, the hard reset
    only discards changes introduced by the failed revert attempt.
    """
    _run_git(workspace_dir, ["revert", "--abort"])
    if head_before is None:
        return
    head_now = current_head(workspace_dir)
    clean = worktree_is_clean(workspace_dir)
    if head_now != head_before or clean is not True:
        _run_git(workspace_dir, ["reset", "--hard", head_before])


def _build_revert_message(
    workspace_dir: str,
    agent_name: str,
    shas: tuple[str, ...],
) -> str:
    lines = [
        f"Revert {len(shas)} commit(s) from agent '{agent_name}'",
        "",
        "This reverts the following commits:",
    ]
    for sha in shas:
        subject = commit_subject(workspace_dir, sha)
        lines.append(f"- {sha[:9]} {subject}".rstrip())
    return "\n".join(lines)


def _build_bulk_revert_message(
    workspace_dir: str,
    agent_names: Sequence[str],
    shas: tuple[str, ...],
) -> str:
    names = ", ".join(agent_names)
    lines = [
        f"Revert {len(shas)} commit(s) from {len(agent_names)} agent(s)",
        "",
        f"Agents: {names}",
        "",
        "This reverts the following commits:",
    ]
    for sha in shas:
        subject = commit_subject(workspace_dir, sha)
        lines.append(f"- {sha[:9]} {subject}".rstrip())
    return "\n".join(lines)


def _push_revert_commit(workspace_dir: str) -> _PushOutcome:
    """Push the current branch to ``origin`` when both are available.

    Skips (``attempted=False``) when there is no ``origin`` remote or no
    current branch. Otherwise runs ``git push origin <branch>`` and reports
    success or the push failure detail so callers can surface it.
    """
    remote = _run_git(workspace_dir, ["remote", "get-url", "origin"])
    if remote.returncode != 0 or not remote.stdout.strip():
        return _PushOutcome(
            attempted=False, pushed=False, skipped_reason="no origin remote"
        )
    branch = _run_git(workspace_dir, ["symbolic-ref", "--short", "HEAD"])
    branch_name = branch.stdout.strip()
    if branch.returncode != 0 or not branch_name:
        return _PushOutcome(
            attempted=False,
            pushed=False,
            skipped_reason="detached HEAD or no current branch",
        )
    push = _run_git(workspace_dir, ["push", "origin", branch_name])
    if push.returncode == 0:
        return _PushOutcome(attempted=True, pushed=True)
    detail = (push.stderr or push.stdout or "git push failed").strip()
    return _PushOutcome(attempted=True, pushed=False, error=detail)


def _write_revert_result(
    artifacts_dir: str,
    agent_name: str,
    shas: tuple[str, ...],
    *,
    push: _PushOutcome | None = None,
    repo_outcomes: tuple[RepoRevertOutcome, ...] = (),
    complete: bool | None = None,
) -> None:
    try:
        pushed = (
            push.pushed if push is not None else any(o.pushed for o in repo_outcomes)
        )
        if complete is None:
            complete = True
        payload: dict[str, object] = {
            "agent_name": agent_name,
            "reverted_shas": list(shas),
            "pushed": pushed,
            "complete": complete,
            "reverted_at": datetime.now().isoformat(timespec="seconds"),
        }
        if repo_outcomes:
            payload["repos"] = [
                _repo_outcome_payload(outcome) for outcome in repo_outcomes
            ]
        if push is not None and push.error is not None:
            payload["push_error"] = push.error
        if push is not None and push.skipped_reason is not None:
            payload["push_skipped_reason"] = push.skipped_reason
        if push is None and len(repo_outcomes) == 1:
            outcome = repo_outcomes[0]
            if outcome.error and outcome.error.startswith("git push failed:"):
                payload["push_error"] = outcome.error.removeprefix("git push failed: ")
            if outcome.push_skipped_reason is not None:
                payload["push_skipped_reason"] = outcome.push_skipped_reason
        path = Path(artifacts_dir) / _REVERT_RESULT_FILENAME
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def _repo_outcome_payload(outcome: RepoRevertOutcome) -> dict[str, object]:
    payload: dict[str, object] = {
        "repo_label": outcome.repo_label,
        "workspace_dir": outcome.workspace_dir,
        "success": outcome.success,
        "reverted_shas": list(outcome.reverted_shas),
        "pushed": outcome.pushed,
    }
    if outcome.error is not None:
        payload["error"] = outcome.error
    if outcome.skipped_reason is not None:
        payload["skipped_reason"] = outcome.skipped_reason
    if outcome.push_skipped_reason is not None:
        payload["push_skipped_reason"] = outcome.push_skipped_reason
    return payload


__all__ = [
    "BulkRevertPreview",
    "BulkRevertResult",
    "RepoRevertOutcome",
    "RepoRevertPlan",
    "RevertCommit",
    "RevertPreview",
    "RevertRepo",
    "RevertResult",
    "RevertTarget",
    "agent_is_reverted",
    "execute_agent_revert",
    "execute_agents_revert",
    "preview_agent_revert",
    "preview_agents_revert",
    "resolve_revert_agent_name",
    "resolve_revert_family_base",
    "resolve_revert_repos",
    "resolve_revert_repos_for_agents",
    "resolve_revert_workspace_dir",
]
