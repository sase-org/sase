"""Core Patch operations for updating, extracting, and validating."""

import os
import sys
from pathlib import Path

from rich.console import Console

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from sase.core.patch import (
    get_next_suffix_number,
    has_suffix,
)
from sase.core.paths import sase_subdir
from sase.running_field import (
    get_first_available_workspace,
    get_workspace_directory_for_num,
    update_running_field_cl_name,
)
from sase.running_field import (
    get_workspace_directory as get_workspace_dir_from_project,
)
from sase.status_state_machine import update_parent_references_atomic

from .patch import Patch
from .hooks import has_failing_hooks_for_fix


def get_workspace_directory(patch: Patch) -> tuple[str, str | None]:
    """Determine which workspace directory to use for a Patch.

    Uses the RUNNING field in the ProjectSpec file to track which workspaces
    are currently in use. Finds the first available (unclaimed) workspace.

    Args:
        patch: The Patch to determine workspace for

    Returns:
        Tuple of (workspace_directory, workspace_suffix)
        - workspace_directory: Full path to workspace directory
        - workspace_suffix: Suffix like "fig_3" or None for main workspace
    """
    # Find first available workspace using RUNNING field
    workspace_num = get_first_available_workspace(patch.file_path)

    return get_workspace_directory_for_num(workspace_num, patch.project_basename)


def _has_failing_hooks_for_fix(patch: Patch) -> bool:
    """Check if a Patch has any hooks eligible for fix-hook workflow.

    This excludes hooks that already have a fix-hook agent running (timestamp suffix)
    or hooks that the user has marked to skip (! suffix).

    Args:
        patch: The Patch to check

    Returns:
        True if any hooks are eligible for fix-hook workflow
    """
    return has_failing_hooks_for_fix(patch.hooks)


def get_available_workflows(patch: Patch) -> list[str]:
    """Get all available workflows for this Patch.

    Returns a list of workflow names that are applicable for this Patch based on:
    - Any HOOKS have FAILED status - Runs fix-hook workflow
    - COMMENTS has [reviewer] entry without suffix - Runs crs workflow

    Args:
        patch: The Patch object to check

    Returns:
        List of workflow names (e.g., ["fix-hook", "crs"])
    """
    workflows = []

    # Add fix-hook workflow if there are any failing hooks eligible for fix
    if _has_failing_hooks_for_fix(patch):
        workflows.append("fix-hook")

    # Add crs workflow if there's a [critique] comment entry without suffix
    if patch.comments:
        for entry in patch.comments:
            if entry.reviewer == "critique" and entry.suffix is None:
                workflows.append("crs")
                break

    return workflows


def update_to_patch(
    patch: Patch,
    console: Console | None = None,
    revision: str | None = None,
    workspace_dir: str | None = None,
) -> tuple[bool, str | None]:
    """Update working directory to the specified Patch.

    This function:
    1. Changes to workspace directory (uses sase_hg_get_workspace to determine path)
    2. Runs sase_hg_update <revision>

    Args:
        patch: The Patch object to update to
        console: Optional Rich Console object for error output
        revision: Specific revision to update to. If None, uses parent or p4head.
                  Common values: patch.name (for diff), patch.parent (for workflow)
        workspace_dir: Optional workspace directory to use. If None, uses main workspace.

    Returns:
        Tuple of (success, error_message)
    """
    # Determine target directory
    if workspace_dir:
        target_dir = workspace_dir
    else:
        try:
            target_dir = get_workspace_dir_from_project(patch.project_basename)
        except RuntimeError as e:
            return (False, str(e))

    # Verify directory exists
    if not os.path.exists(target_dir):
        return (False, f"Target directory does not exist: {target_dir}")
    if not os.path.isdir(target_dir):
        return (False, f"Target path is not a directory: {target_dir}")

    # Run checkout via VCS provider
    from sase.vcs_provider import get_vcs_provider

    provider = get_vcs_provider(target_dir)

    # Determine which revision to update to
    if revision is not None:
        update_target = revision
    else:
        # Default: Use PARENT field if set, otherwise use VCS default
        update_target = (
            patch.parent
            if patch.parent
            else provider.get_default_parent_revision(target_dir)
        )

    update_target = provider.resolve_revision(
        update_target, patch.project_basename, target_dir
    )

    return provider.checkout(update_target, target_dir)


update_to_changespec = update_to_patch  # legacy compatibility alias


def has_active_children(
    patch: Patch,
    all_patches: list[Patch],
    terminal_statuses: tuple[str, ...] = ("Reverted",),
) -> bool:
    """Check if any Patch has this one as a parent and is not in a terminal status.

    Args:
        patch: The Patch to check for children.
        all_patches: All Patches to search through.
        terminal_statuses: Statuses considered terminal (children with these
            statuses are ignored). Defaults to ("Reverted",) for revert.
            Archive uses ("Archived", "Reverted").

    Returns:
        True if any Patch has this one as parent and is not terminal.
    """
    for cs in all_patches:
        if cs.parent == patch.name and cs.status not in terminal_statuses:
            return True
    return False


def calculate_lifecycle_new_name(
    patch: Patch,
    all_patches: list[Patch],
) -> str:
    """Calculate the new name for a lifecycle operation (archive/revert).

    Appends a `_<N>` suffix, skipping if the Patch is WIP and already
    has a suffix.

    Args:
        patch: The Patch being renamed.
        all_patches: All Patches (used to find next available suffix).

    Returns:
        The new name (may be unchanged if WIP with existing suffix).
    """
    if patch.status in ("WIP", "Draft") and has_suffix(patch.name):
        return patch.name
    existing_names = {cs.name for cs in all_patches}
    suffix = get_next_suffix_number(patch.name, existing_names)
    return f"{patch.name}_{suffix}"


def rename_patch_with_references(
    project_file: str,
    old_name: str,
    new_name: str,
) -> None:
    """Rename a Patch and update all references (RUNNING, PARENT fields).

    Args:
        project_file: Path to the project file.
        old_name: Current name of the Patch.
        new_name: New name for the Patch.

    Raises:
        Exception: If any of the rename operations fail.
    """
    # Lazy import to avoid circular dependency
    from .revert import update_patch_name_atomic

    update_patch_name_atomic(project_file, old_name, new_name)
    update_running_field_cl_name(project_file, old_name, new_name)
    update_parent_references_atomic(project_file, old_name, new_name)


rename_changespec_with_references = (
    rename_patch_with_references  # legacy compatibility alias
)


def save_diff_to_file(
    patch: Patch, new_name: str, workspace_dir: str, subdir: str
) -> tuple[bool, str | None]:
    """Save the diff of a Patch to a subdirectory under ~/.sase/.

    Runs `hg diff -c <name>` in the workspace directory and saves
    the output to `~/.sase/<subdir>/<new_name>.diff`.

    Args:
        patch: The Patch to save diff for.
        new_name: The new name (with suffix) for the diff file.
        workspace_dir: The workspace directory to run hg diff in.
        subdir: The subdirectory under ~/.sase/ (e.g., "reverted" or "archived").

    Returns:
        Tuple of (success, error_message).
    """
    target_dir = sase_subdir(subdir)
    target_dir.mkdir(parents=True, exist_ok=True)

    diff_file = target_dir / f"{new_name}.diff"

    try:
        from sase.vcs_provider import get_vcs_provider

        provider = get_vcs_provider(workspace_dir)
        resolved = provider.resolve_revision(
            patch.name, patch.project_basename, workspace_dir
        )
        success, diff_text = provider.diff_revision(resolved, workspace_dir)

        if not success:
            return (False, f"hg diff failed: {diff_text}")

        with open(diff_file, "w", encoding="utf-8") as f:
            content = diff_text if diff_text else ""
            f.write(content)
            if content and not content.endswith("\n"):
                f.write("\n")

        return (True, None)
    except Exception as e:
        return (False, f"Error saving diff: {e}")
