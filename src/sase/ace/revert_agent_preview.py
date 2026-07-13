"""Preview planning for Agents-tab commit reverts."""

from __future__ import annotations

from collections.abc import Sequence

from sase.ace.revert_agent_discovery import (
    discover_agent_commits as _discover_agent_commits,
    discover_bulk_commits as _discover_bulk_commits,
)
from sase.ace.revert_agent_git import (
    commit_exists,
    is_git_worktree,
    worktree_is_clean,
)
from sase.ace.revert_agent_models import (
    BulkRevertPreview,
    RepoRevertPlan,
    RevertCommit,
    RevertPreview,
    RevertRepo,
    RevertTarget,
)


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
    if not any(plan.revertable for plan in plans):
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
    if not any(plan.revertable for plan in plans):
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

    if repo.repo_kind == "external":
        return _preview_external_repo(repo)

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
        repo_kind=repo.repo_kind,
        source_agent_names=repo.source_agent_names,
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

    if repo.repo_kind == "external":
        plan = _preview_external_repo(repo)
        matched = set(repo.source_agent_names) if plan.revertable else set()
        return plan, matched

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
            repo_kind=repo.repo_kind,
            source_agent_names=repo.source_agent_names,
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


def _preview_external_repo(repo: RevertRepo) -> RepoRevertPlan:
    """Preview in-place cleanup for one workspace-local external clone."""
    clean = worktree_is_clean(repo.workspace_dir)
    blocked = "Could not read git status for workspace" if clean is None else None
    return RepoRevertPlan(
        repo_label=repo.label,
        workspace_dir=repo.workspace_dir,
        is_primary=False,
        blocked_reason=blocked,
        repo_kind="external",
        discard_local_changes=clean is False,
        source_agent_names=repo.source_agent_names,
    )


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
        repo_kind=repo.repo_kind,
        source_agent_names=repo.source_agent_names,
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


def ordered_matched_names(
    targets: tuple[RevertTarget, ...],
    matched: set[str],
) -> tuple[str, ...]:
    return tuple(t.agent_name for t in targets if t.agent_name in matched)


_ordered_matched_names = ordered_matched_names


__all__ = [
    "_blocked_repo_plan",
    "_coerce_revert_repos",
    "_flatten_revertable_commits",
    "_preview_agent_repo",
    "_preview_bulk_repo",
    "_preview_empty_error",
    "_primary_workspace_dir",
    "_preview_external_repo",
    "_repo_blocked_reason",
    "ordered_matched_names",
    "preview_agent_revert",
    "preview_agents_revert",
]
