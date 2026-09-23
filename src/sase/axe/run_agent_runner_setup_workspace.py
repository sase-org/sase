"""Workspace preparation for ``run_agent_runner``.

Occupancy guarding, non-home workspace preparation, workspace entry, and the
SDD base-SHA capture used to bound finalize-time scans.
"""

import os
import subprocess
import sys
from pathlib import Path

from sase.axe.runner_workspace import (
    WorkspacePreparationError,
    prepare_launch_workspace_repos,
    prepare_workspace,
    prepare_workspace_with_reclone,
)

__all__ = [
    "capture_sdd_base_sha",
    "enter_agent_workspace",
    "guard_workspace_not_occupied",
    "prepare_workspace_if_needed",
]


def guard_workspace_not_occupied(
    *,
    checkout_dir: str,
    project_file: str,
    workspace_num: int,
    project_name: str,
    workflow_name: str,
    artifacts_timestamp: str | None,
) -> None:
    """Refuse to destructively prepare *checkout_dir* if another live agent
    holds it.

    Raises ``WorkspaceOccupiedError`` (a ``RuntimeError``) on conflict,
    which flows into the runner's normal failure/done-marker path like any
    other setup exception.
    """
    from sase.core.occupancy_guard import (
        OccupancyCaller,
        WorkspaceOccupiedError,
        ensure_workspace_not_occupied,
    )

    try:
        ensure_workspace_not_occupied(
            checkout_dir,
            project_file=project_file,
            caller=OccupancyCaller(
                pid=os.getpid(),
                workspace_num=workspace_num,
                project=project_name,
                workflow=workflow_name,
                artifacts_timestamp=artifacts_timestamp,
            ),
        )
    except WorkspaceOccupiedError:
        raise


def prepare_workspace_if_needed(
    *,
    workspace_dir: str,
    workspace_num: int,
    cl_name: str,
    update_target: str,
    project_name: str,
    is_home_mode: bool,
    retry_handoff: object | None,
    project_file: str = "",
    workflow_name: str = "",
    artifacts_timestamp: str | None = None,
) -> frozenset[str]:
    """Prepare a non-home workspace unless this runner must preserve it."""
    if not update_target or is_home_mode:
        return frozenset()

    if retry_handoff is not None:
        print(
            "=== Skipping workspace prep (retry-spawn child) — "
            "parent's in-progress edits preserved ==="
        )
        print()
        return frozenset()

    guard_workspace_not_occupied(
        checkout_dir=workspace_dir,
        project_file=project_file,
        workspace_num=workspace_num,
        project_name=project_name,
        workflow_name=workflow_name,
        artifacts_timestamp=artifacts_timestamp,
    )

    def _reenter_recreated_workspace() -> None:
        # The checkout was moved aside and re-materialized: the process cwd
        # still points at the trashed directory, so chdir back in, re-apply
        # cwd-derived environment, and re-check the occupancy claim before
        # the second preparation pass touches the new checkout.
        enter_agent_workspace(workspace_dir, workspace_num)
        guard_workspace_not_occupied(
            checkout_dir=workspace_dir,
            project_file=project_file,
            workspace_num=workspace_num,
            project_name=project_name,
            workflow_name=workflow_name,
            artifacts_timestamp=artifacts_timestamp,
        )

    print("=== Preparing Workspace ===")
    try:
        prepare_workspace_with_reclone(
            prepare_workspace,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
            cl_name=cl_name,
            update_target=update_target,
            project_basename=project_name,
            backup_suffix="ace",
            project_file=project_file,
            after_recreate=_reenter_recreated_workspace,
        )
    except WorkspacePreparationError as exc:
        print(f"Workspace preparation failed: {exc.reason}", file=sys.stderr)
        raise RuntimeError(
            f"Failed to prepare workspace {workspace_dir}: {exc.reason}"
        ) from exc
    fresh_sidecars = prepare_launch_workspace_repos(workspace_dir, workspace_num)
    print("===========================")
    print()
    return fresh_sidecars


def enter_agent_workspace(workspace_dir: str, workspace_num: int = 1) -> None:
    """Chdir into the agent workspace and install per-clone ignore entries."""
    os.chdir(workspace_dir)
    os.environ["SASE_ACTIVE_PROJECT_DIR"] = workspace_dir
    from sase.sdd.env import set_sdd_dir_env

    set_sdd_dir_env(
        os.environ,
        workspace_dir=workspace_dir,
        workspace_num=workspace_num,
    )

    # Keep runtime state and host-scoped linked clones untracked in this clone.
    # ``.git/info/exclude`` is git's per-clone ignore file honored by
    # ``git clean`` even before the tracked project .gitignore is initialized.
    from sase.workspace_provider.git_exclude import ensure_git_info_exclude_entry

    ensure_git_info_exclude_entry(workspace_dir, ".sase/")
    ensure_git_info_exclude_entry(workspace_dir, "/sase/repos/")


def capture_sdd_base_sha(workspace_dir: str, workspace_num: int) -> str | None:
    """Return the sidecar SDD repo HEAD to bound finalize-time scans."""
    try:
        from sase.sdd.store import resolve_sdd_store

        store = resolve_sdd_store(workspace_dir, workspace_num)
    except Exception:
        return None

    if store.is_in_tree:
        return None

    repo_root = Path(store.repo_root).expanduser()
    if not (repo_root / ".git").exists():
        return None

    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    sha = result.stdout.strip()
    return sha or None
