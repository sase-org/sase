"""Suffix strip/append logic for status transitions."""

import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from sase.vcs_provider import get_vcs_provider

from .siblings import SiblingRevertResult, revert_sibling_draft_changespecs

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


def _is_github_project(project_file: str) -> bool:
    """Return True if *project_file* belongs to a GitHub-hosted project."""
    try:
        from sase.workspace_provider import detect_workflow_type

        return detect_workflow_type(project_file) == "gh"
    except (ValueError, Exception):
        return False


def _push_branch_rename(
    workspace_dir: str,
    new_branch: str,
    old_resolved: str,
) -> None:
    """Push a renamed branch to origin and delete the old remote branch.

    After a local ``git branch -m``, the remote still has the old name.
    Since workspaces are independent clones, the rename is invisible to
    other workspaces until we sync with origin.

    Args:
        workspace_dir: Path to the workspace directory.
        new_branch: The new branch name (already renamed locally).
        old_resolved: The resolved name returned by ``resolve_revision``
            (may include ``origin/`` prefix).
    """
    old_remote_branch = old_resolved.removeprefix("origin/")

    # Push the newly renamed branch
    push_out = subprocess.run(
        ["git", "push", "origin", new_branch],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if push_out.returncode != 0:
        logger.warning(
            f"Failed to push renamed branch {new_branch}: {push_out.stderr.strip()}"
        )

    # Delete the old branch from origin
    if old_remote_branch != new_branch:
        del_out = subprocess.run(
            ["git", "push", "origin", "--delete", old_remote_branch],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if del_out.returncode != 0:
            logger.warning(
                f"Failed to delete old remote branch {old_remote_branch}: "
                f"{del_out.stderr.strip()}"
            )


def handle_suffix_strip(
    project_file: str,
    suffixed_name: str,
    base_name: str,
    console: "Console | None" = None,
) -> list[SiblingRevertResult]:
    """Handle stripping __<N> suffix when transitioning to Ready.

    Args:
        project_file: Path to the project file.
        suffixed_name: The current name with suffix (e.g., "foo_bar__1").
        base_name: The base name without suffix (e.g., "foo_bar").
        console: Optional Rich console for output.

    Returns:
        List of SiblingRevertResult for reverted siblings.
    """
    from sase.ace.revert import update_changespec_name_atomic
    from sase.core.changespec import changespec_name_to_branch
    from sase.running_field import (
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
        update_running_field_cl_name,
    )

    from .field_updates import update_parent_references_atomic

    # Update NAME field
    update_changespec_name_atomic(project_file, suffixed_name, base_name)

    # Rename the CL in git to match the new name
    project_basename = Path(project_file).stem
    try:
        # Use a non-primary workspace (>=100) to avoid disrupting the main workspace
        workspace_num = get_first_available_axe_workspace(project_file)
        workspace_dir, _ = get_workspace_directory_for_num(
            workspace_num, project_basename
        )

        provider = get_vcs_provider(workspace_dir)

        # First checkout the CL we want to rename
        resolved = provider.resolve_revision(
            suffixed_name, project_basename, workspace_dir
        )
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            logger.warning(f"Failed to checkout CL {suffixed_name}: {checkout_err}")
        else:
            # Rename to the canonical branch form (prefix stripped, hyphens)
            new_branch = changespec_name_to_branch(base_name, project_basename)
            rename_ok, rename_err = provider.rename_branch(new_branch, workspace_dir)
            if not rename_ok:
                logger.warning(f"Failed to rename CL: {rename_err}")
            elif _is_github_project(project_file):
                logger.info(
                    "Skipping remote branch delete for GitHub project "
                    "(would close the PR on the old branch)"
                )
            else:
                _push_branch_rename(workspace_dir, new_branch, resolved)
    except RuntimeError as e:
        logger.warning(f"Could not get workspace directory: {e}")

    # Update PARENT references in other ChangeSpecs
    update_parent_references_atomic(project_file, suffixed_name, base_name)

    # Update RUNNING field entries
    update_running_field_cl_name(project_file, suffixed_name, base_name)

    # Auto-revert sibling WIP/Draft ChangeSpecs with the same basename
    return revert_sibling_draft_changespecs(
        project_file, base_name, suffixed_name, console
    )


def handle_suffix_append(
    project_file: str,
    base_name: str,
    suffixed_name: str,
) -> None:
    """Handle appending __<N> suffix when transitioning from Ready to Draft.

    Args:
        project_file: Path to the project file.
        base_name: The base name without suffix (e.g., "foo_bar").
        suffixed_name: The new name with suffix (e.g., "foo_bar__1").
    """
    from sase.ace.revert import update_changespec_name_atomic
    from sase.core.changespec import changespec_name_to_branch_with_suffix
    from sase.running_field import (
        get_first_available_axe_workspace,
        get_workspace_directory_for_num,
        update_running_field_cl_name,
    )

    from .field_updates import update_parent_references_atomic

    # Update NAME field
    update_changespec_name_atomic(project_file, base_name, suffixed_name)

    # Rename the CL in git to match the new name
    project_basename = Path(project_file).stem
    try:
        # Use a non-primary workspace (>=100) to avoid disrupting the main workspace
        workspace_num = get_first_available_axe_workspace(project_file)
        workspace_dir, _ = get_workspace_directory_for_num(
            workspace_num, project_basename
        )

        provider = get_vcs_provider(workspace_dir)

        # First checkout the CL we want to rename
        resolved = provider.resolve_revision(base_name, project_basename, workspace_dir)
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            logger.warning(f"Failed to checkout CL {base_name}: {checkout_err}")
        else:
            # Rename to the canonical branch form (prefix stripped, hyphens, with suffix)
            new_branch = changespec_name_to_branch_with_suffix(
                suffixed_name, project_basename
            )
            rename_ok, rename_err = provider.rename_branch(new_branch, workspace_dir)
            if not rename_ok:
                logger.warning(f"Failed to rename CL: {rename_err}")
            elif _is_github_project(project_file):
                logger.info(
                    "Skipping remote branch delete for GitHub project "
                    "(would close the PR on the old branch)"
                )
            else:
                _push_branch_rename(workspace_dir, new_branch, resolved)
    except RuntimeError as e:
        logger.warning(f"Could not get workspace directory: {e}")

    # Update PARENT references in other ChangeSpecs
    update_parent_references_atomic(project_file, base_name, suffixed_name)

    # Update RUNNING field entries
    update_running_field_cl_name(project_file, base_name, suffixed_name)
