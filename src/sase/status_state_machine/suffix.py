"""Suffix strip/append logic for status transitions."""

import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from sase.git_lock_retry import run_with_git_lock_retry
from sase.vcs_provider import get_vcs_provider

from .siblings import SiblingRevertResult, revert_sibling_draft_patches

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


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
    push_out, _outcome = run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", "push", "origin", new_branch],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=False,
        ),
        cwd=workspace_dir,
    )
    if push_out.returncode != 0:
        logger.warning(
            f"Failed to push renamed branch {new_branch}: {push_out.stderr.strip()}"
        )

    # Delete the old branch from origin
    if old_remote_branch != new_branch:
        del_out, _outcome = run_with_git_lock_retry(
            lambda: subprocess.run(
                ["git", "push", "origin", "--delete", old_remote_branch],
                cwd=workspace_dir,
                capture_output=True,
                text=True,
                check=False,
            ),
            cwd=workspace_dir,
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
    from sase.ace.revert import update_patch_name_atomic
    from sase.core.branch_map import remove_branch_alias, write_branch_alias
    from sase.running_field import (
        claim_next_axe_workspace_dir,
        release_workspace,
        update_running_field_cl_name,
    )

    from .field_updates import update_parent_references_atomic

    # Update NAME field
    update_patch_name_atomic(project_file, suffixed_name, base_name)

    # Rename the Patch branch in git to match the new name
    project_basename = Path(project_file).stem
    workspace_num: int | None = None
    try:
        workspace_num, workspace_dir, _ = claim_next_axe_workspace_dir(
            project_file,
            "suffix-strip",
            os.getpid(),
            project_basename,
            cl_name=base_name,
        )

        provider = get_vcs_provider(workspace_dir)

        # First checkout the branch we want to rename
        resolved = provider.resolve_revision(
            suffixed_name, project_basename, workspace_dir
        )
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            logger.warning(f"Failed to checkout branch {suffixed_name}: {checkout_err}")
        elif not provider.can_rename_branch(workspace_dir):
            # Branch is immutable (e.g. GitHub PR) — persist alias instead
            # of renaming.  The old branch stays on the remote; resolution
            # will find it via branch_map.
            old_branch = resolved.removeprefix("origin/")
            write_branch_alias(project_basename, base_name, old_branch)
            logger.info(f"Branch immutable — wrote alias {base_name} -> {old_branch}")
        else:
            new_branch = provider.derive_branch_name(base_name, project_basename)
            rename_ok, rename_err = provider.rename_branch(new_branch, workspace_dir)
            if not rename_ok:
                logger.warning(f"Failed to rename branch: {rename_err}")
            else:
                _push_branch_rename(workspace_dir, new_branch, resolved)
                # Clean up any stale alias from a previous immutable cycle
                remove_branch_alias(project_basename, base_name)
    except RuntimeError as e:
        logger.warning(f"Could not get workspace directory: {e}")
    finally:
        if workspace_num is not None:
            release_workspace(project_file, workspace_num, "suffix-strip", base_name)

    # Update PARENT references in other Patches
    update_parent_references_atomic(project_file, suffixed_name, base_name)

    # Update RUNNING field entries
    update_running_field_cl_name(project_file, suffixed_name, base_name)

    # Auto-revert sibling WIP/Draft Patches with the same basename
    return revert_sibling_draft_patches(project_file, base_name, suffixed_name, console)


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
    from sase.ace.revert import update_patch_name_atomic
    from sase.core.branch_map import (
        read_branch_map,
        remove_branch_alias,
        write_branch_alias,
    )
    from sase.running_field import (
        claim_next_axe_workspace_dir,
        release_workspace,
        update_running_field_cl_name,
    )

    from .field_updates import update_parent_references_atomic

    # Update NAME field
    update_patch_name_atomic(project_file, base_name, suffixed_name)

    # Rename the Patch branch in git to match the new name
    project_basename = Path(project_file).stem
    workspace_num: int | None = None
    try:
        workspace_num, workspace_dir, _ = claim_next_axe_workspace_dir(
            project_file,
            "suffix-append",
            os.getpid(),
            project_basename,
            cl_name=suffixed_name,
        )

        provider = get_vcs_provider(workspace_dir)

        # First checkout the branch we want to rename
        resolved = provider.resolve_revision(base_name, project_basename, workspace_dir)
        checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
        if not checkout_ok:
            logger.warning(f"Failed to checkout branch {base_name}: {checkout_err}")
        elif not provider.can_rename_branch(workspace_dir):
            # Branch is immutable — update the alias mapping.
            # The actual branch on the remote doesn't change; we just
            # re-key the mapping from base_name -> suffixed_name.
            branch_map = read_branch_map(project_basename)
            actual_branch = branch_map.get(base_name)
            if actual_branch:
                remove_branch_alias(project_basename, base_name)
                write_branch_alias(project_basename, suffixed_name, actual_branch)
                logger.info(
                    f"Branch immutable — re-keyed alias {suffixed_name} -> "
                    f"{actual_branch}"
                )
            else:
                # No existing alias — the resolved branch is the actual one
                old_branch = resolved.removeprefix("origin/")
                write_branch_alias(project_basename, suffixed_name, old_branch)
                logger.info(
                    f"Branch immutable — wrote alias {suffixed_name} -> {old_branch}"
                )
        else:
            new_branch = provider.derive_branch_name_with_suffix(
                suffixed_name, project_basename
            )
            rename_ok, rename_err = provider.rename_branch(new_branch, workspace_dir)
            if not rename_ok:
                logger.warning(f"Failed to rename branch: {rename_err}")
            else:
                _push_branch_rename(workspace_dir, new_branch, resolved)
                # Clean up any stale alias
                remove_branch_alias(project_basename, suffixed_name)
    except RuntimeError as e:
        logger.warning(f"Could not get workspace directory: {e}")
    finally:
        if workspace_num is not None:
            release_workspace(
                project_file, workspace_num, "suffix-append", suffixed_name
            )

    # Update PARENT references in other Patches
    update_parent_references_atomic(project_file, base_name, suffixed_name)

    # Update RUNNING field entries
    update_running_field_cl_name(project_file, base_name, suffixed_name)
