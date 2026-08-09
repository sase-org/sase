"""Claimed-workspace orchestration for Agents-tab commit reverts.

The Agents-tab revert flow must not run git work in the directory the selected
agent originally ran in: that directory can be reclaimed by other agents and
accumulate unrelated changes, which would make a revert fail for reasons
unrelated to the commits being reverted.

Instead every revert operation (preview and execute, single and bulk) claims a
*fresh* short-lived workspace, prepares that checkout on the relevant Patch
branch or project default branch, runs the existing preview/execute logic there,
and releases the claim in all completion and failure paths.

Preview and execute claim *separate* workspaces so no claim is held while the
confirmation modal waits for user input. Execute re-uses the previewed commit
SHAs and only remaps repository paths to the newly claimed checkout, so it never
silently includes commits that appeared after the user confirmed.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, replace

from sase.ace.revert_agent_execute import (
    execute_agent_revert,
    execute_agents_revert,
)
from sase.ace.revert_agent_models import (
    BulkRevertIntent,
    BulkRevertPreview,
    BulkRevertResult,
    RepoRevertPlan,
    RevertIntent,
    RevertPreview,
    RevertRepo,
    RevertResult,
)
from sase.ace.revert_agent_preview import (
    preview_agent_revert,
    preview_agents_revert,
)
from sase.ace.revert_agent_resolution import external_repos_from_artifact_dirs
from sase.linked_repos import resolve_linked_repos_for_project
from sase.running_field import (
    WorkspaceClaimError,
    claim_next_axe_workspace,
    release_workspace,
)
from sase.vcs_provider import detect_vcs_family, get_vcs_provider
from sase.workspace_provider.utils import (
    ensure_workspace_checkout,
    parse_workspace_dir,
)

#: Distinct workflow label so revert claims are identifiable in the RUNNING
#: field and never collide with the workspace the agent originally ran in.
REVERT_WORKSPACE_WORKFLOW = "ace(revert-agent)"


class RevertWorkspaceError(RuntimeError):
    """Raised when a freshly claimed revert workspace cannot be prepared."""


@dataclass(frozen=True)
class _PreparedRevertWorkspace:
    """A claimed checkout prepared on the target branch for a revert."""

    workspace_num: int
    primary_dir: str
    #: Repositories prepared successfully (primary, linked, then external).
    repos: tuple[RevertRepo, ...]
    #: Per-repo plans for repositories that could not be prepared (e.g. a linked
    #: repo missing the branch). Surfaced as blocked rather than silently
    #: falling back to a stale checkout.
    prep_blocked: tuple[RepoRevertPlan, ...] = ()


# ---------------------------------------------------------------------------
# Single-agent intent entry points
# ---------------------------------------------------------------------------


def preview_agent_revert_intent(intent: RevertIntent) -> RevertPreview:
    """Claim a fresh workspace, prepare it, and preview a single-agent revert."""

    def _run(prepared: _PreparedRevertWorkspace) -> RevertPreview:
        preview = preview_agent_revert(
            prepared.repos,
            intent.agent_name,
            family_base=intent.family_base,
        )
        return _attach_prep_blocked(preview, prepared)

    try:
        return _run_in_claimed_workspace(intent, _run)
    except (WorkspaceClaimError, RevertWorkspaceError) as exc:
        return RevertPreview(
            agent_name=intent.agent_name,
            scope=intent.scope,
            workspace_dir="",
            error=str(exc),
        )


def execute_agent_revert_intent(
    preview: RevertPreview,
    intent: RevertIntent,
) -> RevertResult:
    """Claim a fresh workspace and execute a previewed single-agent revert."""

    def _run(prepared: _PreparedRevertWorkspace) -> RevertResult:
        remapped = replace(
            preview,
            repos=_remap_plans(preview.repos, prepared),
            workspace_dir=prepared.primary_dir,
        )
        return execute_agent_revert(remapped, artifacts_dir=intent.artifacts_dir)

    try:
        return _run_in_claimed_workspace(intent, _run)
    except (WorkspaceClaimError, RevertWorkspaceError) as exc:
        return RevertResult(False, f"Revert failed: {exc}", error=str(exc))


# ---------------------------------------------------------------------------
# Bulk (marked-agent) intent entry points
# ---------------------------------------------------------------------------


def preview_agents_revert_intent(intent: BulkRevertIntent) -> BulkRevertPreview:
    """Claim a fresh workspace, prepare it, and preview a bulk revert."""

    def _run(prepared: _PreparedRevertWorkspace) -> BulkRevertPreview:
        targets = tuple(
            replace(target, workspace_dir=prepared.primary_dir)
            for target in intent.targets
        )
        preview = preview_agents_revert(targets, prepared.repos)
        return _attach_prep_blocked(preview, prepared)

    try:
        return _run_in_claimed_workspace(intent, _run)
    except (WorkspaceClaimError, RevertWorkspaceError) as exc:
        return BulkRevertPreview(
            workspace_dir="",
            targets=intent.targets,
            error=str(exc),
        )


def execute_agents_revert_intent(
    preview: BulkRevertPreview,
    intent: BulkRevertIntent,
) -> BulkRevertResult:
    """Claim a fresh workspace and execute a previewed bulk revert."""

    def _run(prepared: _PreparedRevertWorkspace) -> BulkRevertResult:
        remapped = replace(
            preview,
            repos=_remap_plans(preview.repos, prepared),
            workspace_dir=prepared.primary_dir,
        )
        return execute_agents_revert(remapped)

    try:
        return _run_in_claimed_workspace(intent, _run)
    except (WorkspaceClaimError, RevertWorkspaceError) as exc:
        return BulkRevertResult(False, f"Bulk revert failed: {exc}", error=str(exc))


# ---------------------------------------------------------------------------
# Claim / prepare / release helper
# ---------------------------------------------------------------------------


def _run_in_claimed_workspace[T](
    intent: RevertIntent | BulkRevertIntent,
    run: Callable[[_PreparedRevertWorkspace], T],
) -> T:
    """Claim a workspace, prepare it, run *run*, and always release the claim.

    The claim happens before the ``try`` so a failed claim never triggers a
    release of a workspace we do not own; everything after a successful claim
    releases in ``finally``, including preparation failures.
    """
    workspace_num = claim_next_axe_workspace(
        intent.project_file,
        REVERT_WORKSPACE_WORKFLOW,
        os.getpid(),
        cl_name=intent.cl_name,
    )
    try:
        prepared = _prepare_revert_workspace(intent, workspace_num)
        return run(prepared)
    finally:
        release_workspace(
            intent.project_file,
            workspace_num,
            REVERT_WORKSPACE_WORKFLOW,
            intent.cl_name,
        )


def _prepare_revert_workspace(
    intent: RevertIntent | BulkRevertIntent,
    workspace_num: int,
) -> _PreparedRevertWorkspace:
    """Materialize and prepare the claimed checkout for git work.

    Raises:
        RevertWorkspaceError: When the project has no git WORKSPACE_DIR, the
            primary checkout cannot be materialized, or the target branch cannot
            be checked out in the primary checkout.
    """
    primary_dir = parse_workspace_dir(intent.project_file)
    if not primary_dir:
        raise RevertWorkspaceError(
            "No WORKSPACE_DIR configured for project; cannot prepare a revert workspace"
        )
    if detect_vcs_family(primary_dir) != "git":
        raise RevertWorkspaceError(
            "Workspace is not a git checkout (revert is git-only)"
        )

    try:
        claimed_primary = ensure_workspace_checkout(primary_dir, workspace_num)
    except RuntimeError as exc:
        raise RevertWorkspaceError(
            f"Failed to materialize revert workspace: {exc}"
        ) from exc

    ok, error = _prepare_branch(claimed_primary, intent)
    if not ok:
        raise RevertWorkspaceError(
            f"Could not check out branch '{intent.cl_name}' in revert "
            f"workspace: {error or 'unknown error'}"
        )

    repos: list[RevertRepo] = [
        RevertRepo(label="primary", workspace_dir=claimed_primary, is_primary=True)
    ]
    prep_blocked: list[RepoRevertPlan] = []

    for name, linked_dir in _resolve_linked_checkouts(
        intent, claimed_primary, workspace_num
    ):
        ok, error = _prepare_branch(linked_dir, intent)
        if not ok:
            prep_blocked.append(
                RepoRevertPlan(
                    repo_label=name,
                    workspace_dir=linked_dir,
                    is_primary=False,
                    blocked_reason=(
                        f"Could not check out branch '{intent.cl_name}' in linked "
                        f"repo: {error or 'unknown error'}"
                    ),
                )
            )
            continue
        repos.append(RevertRepo(label=name, workspace_dir=linked_dir, is_primary=False))

    seen_repo_dirs = {
        os.path.normcase(os.path.abspath(os.path.expanduser(repo.workspace_dir)))
        for repo in repos
    }
    external_repos = (
        *intent.external_repos,
        *external_repos_from_artifact_dirs(intent.external_artifact_dirs),
    )
    for external in external_repos:
        external_dir = os.path.normpath(os.path.expanduser(external.workspace_dir))
        dedupe_key = os.path.normcase(os.path.abspath(external_dir))
        if dedupe_key in seen_repo_dirs:
            continue
        seen_repo_dirs.add(dedupe_key)
        if not os.path.isdir(external_dir):
            prep_blocked.append(
                RepoRevertPlan(
                    repo_label=external.label,
                    workspace_dir=external_dir,
                    is_primary=False,
                    blocked_reason="Opened external repository is no longer available",
                    repo_kind="external",
                    source_agent_names=external.source_agent_names,
                )
            )
            continue
        # External repos are deliberately reused in place: they are ephemeral
        # workspace-local clones with no Patch branch contract. Preview
        # inspects local changes and execution discards them without network I/O.
        repos.append(
            RevertRepo(
                label=external.label,
                workspace_dir=external_dir,
                repo_kind="external",
                source_agent_names=external.source_agent_names,
            )
        )

    return _PreparedRevertWorkspace(
        workspace_num=workspace_num,
        primary_dir=claimed_primary,
        repos=tuple(repos),
        prep_blocked=tuple(prep_blocked),
    )


def _prepare_branch(
    workspace_dir: str,
    intent: RevertIntent | BulkRevertIntent,
) -> tuple[bool, str | None]:
    """Clean stale state and check out the revert branch in *workspace_dir*."""
    provider = get_vcs_provider(workspace_dir)
    provider.stash_and_clean(f"{intent.cl_name}-revert", workspace_dir)
    if intent.is_project_scoped:
        revision = provider.get_default_parent_revision(workspace_dir)
        checkout_ok, checkout_error = provider.checkout(revision, workspace_dir)
        if not checkout_ok:
            return checkout_ok, checkout_error
        try:
            # A claimed workspace may be reused with a stale default branch.
            # Sync is best-effort so local-only repositories still prepare.
            provider.sync_workspace(workspace_dir)
        except NotImplementedError:
            pass
        return True, None

    revision = provider.resolve_revision(
        intent.cl_name, intent.project_basename, workspace_dir
    )
    return provider.checkout(revision, workspace_dir)


def _resolve_linked_checkouts(
    intent: RevertIntent | BulkRevertIntent,
    primary_dir: str,
    workspace_num: int,
) -> list[tuple[str, str]]:
    """Resolve and materialize linked repos for the claimed workspace.

    Only linked repos the agent run actually touched (``linked_repo_names``) are
    materialized. Returns
    ``(name, workspace_dir)`` pairs for the materialized checkouts.
    """
    if not intent.linked_repo_names:
        return []
    wanted = set(intent.linked_repo_names)
    resolution = resolve_linked_repos_for_project(
        project_file=intent.project_file,
        workspace_dir=primary_dir,
        workspace_num=workspace_num,
        materialize=True,
    )
    return [
        (repo.name, repo.workspace_dir)
        for repo in resolution.repos
        if repo.workspace_dir != repo.primary_dir and repo.name in wanted
    ]


def _attach_prep_blocked[T: (RevertPreview, BulkRevertPreview)](
    preview: T, prepared: _PreparedRevertWorkspace
) -> T:
    """Append preparation-blocked repo plans to a preview for display."""
    if not prepared.prep_blocked:
        return preview
    return replace(preview, repos=(*preview.repos, *prepared.prep_blocked))


def _remap_plans(
    plans: tuple[RepoRevertPlan, ...],
    prepared: _PreparedRevertWorkspace,
) -> tuple[RepoRevertPlan, ...]:
    """Remap previewed repo plans onto the freshly prepared checkout paths.

    Each previewed plan is matched to a prepared repository by label so the
    execute transaction runs in the newly claimed workspace, never the (now
    released) checkout the preview ran in. A label with no prepared repository
    is marked blocked rather than reverting against a stale path.
    """
    by_label = {(repo.label, repo.repo_kind): repo for repo in prepared.repos}
    blocked_by_label = {
        (plan.repo_label, plan.repo_kind): plan for plan in prepared.prep_blocked
    }
    remapped: list[RepoRevertPlan] = []
    for plan in plans:
        key = (plan.repo_label, plan.repo_kind)
        prepared_repo = by_label.get(key)
        if prepared_repo is not None:
            remapped.append(
                replace(
                    plan,
                    workspace_dir=prepared_repo.workspace_dir,
                    is_primary=prepared_repo.is_primary,
                    repo_kind=prepared_repo.repo_kind,
                    source_agent_names=prepared_repo.source_agent_names,
                )
            )
            continue
        blocked = blocked_by_label.get(key)
        reason = (
            blocked.blocked_reason
            if blocked is not None
            else "Workspace could not be prepared for this repository"
        )
        remapped.append(replace(plan, blocked_reason=reason))
    return tuple(remapped)


__all__ = [
    "REVERT_WORKSPACE_WORKFLOW",
    "RevertWorkspaceError",
    "execute_agent_revert_intent",
    "execute_agents_revert_intent",
    "preview_agent_revert_intent",
    "preview_agents_revert_intent",
]
