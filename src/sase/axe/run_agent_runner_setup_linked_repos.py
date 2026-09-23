"""Linked-repo workspace preparation for ``run_agent_runner``.

Materializes and prepares host-scoped linked-repo workspaces for a launch,
including the hidden-sidecar filter, the last-resort clone re-creation path,
and the post-claim linked-repo refresh.
"""

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.axe.run_agent_runner_setup_meta import write_agent_meta
from sase.axe.run_agent_runner_setup_workspace import guard_workspace_not_occupied
from sase.axe.runner_workspace import (
    WorkspacePreparationError,
    prepare_workspace,
)

if TYPE_CHECKING:
    from sase.linked_repos import LinkedRepoResolution

__all__ = [
    "prepare_linked_repo_workspaces_if_needed",
    "refresh_linked_repos_for_workspace",
]


def _without_hidden_sidecars(
    resolution: "LinkedRepoResolution",
) -> "LinkedRepoResolution":
    """Defensively remove hidden sidecars from launch-facing metadata."""

    from sase._linked_repo_config import HIDDEN_SIDECAR_ROLES
    from sase.linked_repos import LinkedRepoResolution

    def is_hidden(repo: Any) -> bool:
        if repo.kind != "sidecar":
            return False
        if repo.name in HIDDEN_SIDECAR_ROLES:
            return True
        return bool(
            repo.slug == repo.name
            and any(repo.name.endswith(f"--{role}") for role in HIDDEN_SIDECAR_ROLES)
        )

    visible = tuple(repo for repo in resolution.repos if not is_hidden(repo))
    if visible == resolution.repos:
        return resolution
    return LinkedRepoResolution(visible, resolution.warnings)


def _raise_linked_repo_prep_error(
    name: str, workspace_dir: str, exc: Exception
) -> None:
    """Report a linked-repo preparation failure as a launch setup error."""
    reason = (
        exc.reason
        if isinstance(exc, WorkspacePreparationError)
        else str(exc) or "unknown error"
    )
    print(
        f"Linked repo {name!r} workspace preparation failed: {reason}",
        file=sys.stderr,
    )
    raise RuntimeError(
        f"Failed to prepare linked repo {name!r} workspace: {workspace_dir}: {reason}"
    ) from exc


def _recreate_linked_repo_clone(repo: Any, *, expected_remote_url: str | None) -> str:
    """Rescue a retained linked-repo clone, move it aside, materialize fresh.

    Only the failed clone is replaced; the parent workspace checkout is
    untouched. Returns the re-materialized workspace directory.
    """
    from sase._linked_repo_workspaces import move_aside_for_background_delete
    from sase.workspace_provider.rescue import rescue_git_repo

    workspace_dir = str(repo.workspace_dir)
    rescue_git_repo(
        workspace_dir,
        workspace_dir=workspace_dir,
        workspace_num=repo.workspace_num,
        label=f"linked-{repo.name}",
        reason=(
            "last-resort linked-repo re-creation: rescuing retained clone "
            f"for {repo.name!r}"
        ),
        include_worktree=True,
    )
    try:
        move_aside_for_background_delete(workspace_dir, tag="sase-reclone-trash")
    except OSError as exc:
        raise RuntimeError(
            "could not move linked repo workspace aside for re-creation: "
            f"{workspace_dir}: {exc}"
        ) from exc
    from sase.linked_repos import materialize_linked_repo_workspace

    try:
        return materialize_linked_repo_workspace(
            primary_dir=repo.primary_dir,
            workspace_dir=workspace_dir,
            workspace_num=repo.workspace_num,
            expected_remote_url=expected_remote_url,
        )
    except RuntimeError as exc:
        raise RuntimeError(
            f"Failed to re-create linked repo {repo.name!r} workspace: "
            f"{workspace_dir}: {exc}"
        ) from exc


def prepare_linked_repo_workspaces_if_needed(
    *,
    resolution: "LinkedRepoResolution",
    cl_name: str,
    fresh_sidecar_paths: frozenset[str] = frozenset(),
    primary_workspace_dir: str = "",
    workspace_num: int = 0,
    project_name: str = "",
    project_file: str = "",
    workflow_name: str = "",
    artifacts_timestamp: str | None = None,
) -> None:
    """Materialize and prepare host-scoped linked repo workspaces for a launch."""
    resolution = _without_hidden_sidecars(resolution)
    repos = [
        repo
        for repo in resolution.repos
        if repo.auto_clone
        and repo.workspace_dir
        and repo.workspace_dir != repo.primary_dir
    ]
    if not repos:
        return

    from sase.vcs_provider import VCS_DEFAULT_REVISION

    print("=== Preparing Linked Repo Workspaces ===")
    for repo in repos:
        name = repo.name
        normalized_workspace = str(Path(repo.workspace_dir).expanduser().resolve())
        if repo.kind == "sidecar" and normalized_workspace in fresh_sidecar_paths:
            print(f"Using freshly cloned sidecar {name}: {repo.workspace_dir}")
            continue

        from sase.linked_repos import materialize_linked_repo_workspace

        sidecar_was_missing = repo.kind == "sidecar" and not os.path.lexists(
            repo.workspace_dir
        )
        try:
            workspace_dir = materialize_linked_repo_workspace(
                primary_dir=repo.primary_dir,
                workspace_dir=repo.workspace_dir,
                workspace_num=repo.workspace_num,
                expected_remote_url=(
                    repo.remote_url if repo.kind == "sidecar" else None
                ),
            )
        except RuntimeError as exc:
            raise RuntimeError(
                f"Failed to materialize linked repo {name!r} workspace: "
                f"{repo.workspace_dir}: {exc}"
            ) from exc
        if sidecar_was_missing:
            print(f"Using freshly cloned sidecar {name}: {workspace_dir}")
            continue
        # Linked-repo checkouts share their parent workspace's claim and
        # occupant record — there is no separate per-repo claim to check.
        if not primary_workspace_dir.strip():
            raise ValueError(
                "primary_workspace_dir is required before preparing retained "
                f"linked repo {name!r}"
            )
        guard_workspace_not_occupied(
            checkout_dir=primary_workspace_dir,
            project_file=project_file,
            workspace_num=workspace_num,
            project_name=project_name,
            workflow_name=workflow_name,
            artifacts_timestamp=artifacts_timestamp,
        )
        print(f"Preparing linked repo {name}: {workspace_dir}")
        try:
            prepare_workspace(
                workspace_dir,
                cl_name,
                VCS_DEFAULT_REVISION,
                backup_suffix=f"linked-{name}",
                self_heal=repo.workspace_num > 1,
                workspace_num=repo.workspace_num,
            )
        except WorkspacePreparationError as exc:
            if not exc.reclone_eligible or repo.workspace_num <= 1:
                _raise_linked_repo_prep_error(name, workspace_dir, exc)
            print(
                f"Linked repo {name!r} workspace could not be repaired in "
                f"place ({exc.reason}); re-creating it from its primary..."
            )
            workspace_dir = _recreate_linked_repo_clone(
                repo,
                expected_remote_url=(
                    repo.remote_url if repo.kind == "sidecar" else None
                ),
            )
            guard_workspace_not_occupied(
                checkout_dir=primary_workspace_dir,
                project_file=project_file,
                workspace_num=workspace_num,
                project_name=project_name,
                workflow_name=workflow_name,
                artifacts_timestamp=artifacts_timestamp,
            )
            try:
                prepare_workspace(
                    workspace_dir,
                    cl_name,
                    VCS_DEFAULT_REVISION,
                    backup_suffix=f"linked-{name}",
                    self_heal=repo.workspace_num > 1,
                    workspace_num=repo.workspace_num,
                )
            except WorkspacePreparationError as retry_exc:
                _raise_linked_repo_prep_error(name, workspace_dir, retry_exc)
    from sase.linked_repos import apply_linked_repo_env

    apply_linked_repo_env(os.environ, resolution)
    print("========================================")
    print()


def refresh_linked_repos_for_workspace(
    *,
    project_file: str,
    workspace_dir: str,
    workspace_num: int,
    artifacts_dir: str,
    agent_meta: dict[str, Any],
) -> "LinkedRepoResolution":
    """Refresh linked-repo env/meta after a workspace claim changes."""
    from sase.linked_repos import (
        apply_linked_repo_env,
        resolve_linked_repos_for_project,
    )

    resolution = resolve_linked_repos_for_project(
        project_file=project_file,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
        materialize=False,
    )
    resolution = _without_hidden_sidecars(resolution)
    apply_linked_repo_env(os.environ, resolution)
    agent_meta["workspace_dir"] = workspace_dir
    if resolution.repos:
        # Canonical key plus the deprecated alias for existing readers.
        agent_meta["linked_repos"] = resolution.to_jsonable()
        agent_meta["sibling_repos"] = resolution.to_jsonable()
    write_agent_meta(artifacts_dir, agent_meta)
    return resolution
