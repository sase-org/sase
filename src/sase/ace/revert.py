"""Revert operations for Patches."""

import os
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape as escape_markup

# Add parent directory to path for status_state_machine import
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from sase.core.patch import get_workspace_directory_for_patch
from sase.core.paths import sase_subdir
from sase.status_state_machine import (
    reset_patch_pr_url,
    transition_patch_status,
)
from sase.vcs_provider import get_vcs_provider
from sase.project_display_names import humanize_cl_name

from .patch import (
    Patch,
    patch_lock,
    find_all_patches,
    write_patch_atomic,
)
from .hooks.processes import kill_and_persist_all_running_processes
from .operations import (
    calculate_lifecycle_new_name,
    has_active_children,
    rename_patch_with_references,
    save_diff_to_file,
)

find_all_changespecs = find_all_patches  # legacy compatibility alias
rename_changespec_with_references = (
    rename_patch_with_references  # legacy compatibility alias
)
reset_changespec_pr_url = reset_patch_pr_url  # legacy compatibility alias
transition_changespec_status = transition_patch_status  # legacy compatibility alias


def has_children(patch: Patch, all_patches: list[Patch]) -> bool:
    """Check if any non-reverted Patch has this one as a parent.

    Args:
        patch: The Patch to check for children
        all_patches: All Patches to search through

    Returns:
        True if any non-reverted Patch has this one as parent, False otherwise
    """
    return has_active_children(patch, all_patches)


def update_patch_name_atomic(project_file: str, old_name: str, new_name: str) -> None:
    """Update the NAME field of a specific Patch in the project file.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file
        old_name: Current NAME value of the Patch
        new_name: New NAME value
    """
    with patch_lock(project_file):
        with open(project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = []
        for line in lines:
            if line.startswith("NAME:"):
                current_name = line.split(":", 1)[1].strip()
                if current_name == old_name:
                    updated_lines.append(f"NAME: {new_name}\n")
                    continue
            updated_lines.append(line)

        write_patch_atomic(
            project_file,
            "".join(updated_lines),
            f"Rename Patch {old_name} to {new_name}",
        )


def revert_patch(
    patch: Patch, console: Console | None = None
) -> tuple[bool, str | None]:
    """Revert a Patch by pruning its revision and updating its status.

    This function:
    1. Validates that the Patch has a valid PR set
    2. Validates that the Patch has no children
    3. Renames the Patch by appending `__<N>` suffix
    4. Saves the diff to `~/.sase/reverted/<new_name>.diff`
    5. Runs `sase_hg_prune <name>` to remove the revision
    6. Updates STATUS to "Reverted" and removes the PR field

    Args:
        patch: The Patch to revert
        console: Optional Rich Console for output

    Returns:
        Tuple of (success, error_message)
    """
    # Kill any running processes before reverting
    log_fn = (
        (lambda msg: console.print(f"[cyan]{escape_markup(msg)}[/cyan]"))
        if console
        else None
    )
    kill_and_persist_all_running_processes(
        patch,
        patch.file_path,
        patch.name,
        "Killed hook running on reverted Patch.",
        log_fn=log_fn,
    )

    # Get all patches to check for children and name conflicts
    all_patches = find_all_changespecs()  # legacy compatibility alias

    # Validate no children
    if has_children(patch, all_patches):
        return (
            False,
            "Cannot revert: other Patches have this one as their parent",
        )

    # Calculate new name with suffix
    new_name = calculate_lifecycle_new_name(patch, all_patches)

    if console:
        console.print(f"[cyan]Renaming Patch to: {humanize_cl_name(new_name)}[/cyan]")

    # PR-dependent operations: save diff, prune VCS revision, reset PR URL.
    if patch.pr_url is not None:
        # Get workspace directory
        workspace_dir = get_workspace_directory_for_patch(patch)
        if not workspace_dir:
            return (False, "Could not determine workspace directory")

        if not os.path.isdir(workspace_dir):
            return (False, f"Workspace directory does not exist: {workspace_dir}")

        # Save diff to file
        success, error = save_diff_to_file(patch, new_name, workspace_dir, "reverted")
        if not success:
            return (False, f"Failed to save diff: {error}")

        if console:
            # This is a copyable storage path, so its canonical stem is intentional.
            diff_path = sase_subdir("reverted") / f"{new_name}.diff"
            console.print(f"[green]Saved diff to: {diff_path}[/green]")

        # Run sase_hg_prune
        provider = get_vcs_provider(workspace_dir)
        # Provider revision matching must retain canonical Patch identity.
        resolved = provider.resolve_revision(
            patch.name, patch.project_basename, workspace_dir
        )

        # Abandon remote change (close PR, drop legacy change, etc.)
        success, error = provider.abandon_change(patch.pr_url, resolved, workspace_dir)
        if not success:
            return (False, f"Failed to abandon remote change: {error}")

        if console:
            console.print(f"[green]Abandoned remote change: {patch.pr_url}[/green]")

        success, error = provider.prune(resolved, workspace_dir)
        if not success:
            return (False, f"Failed to prune revision: {error}")

        # Clean up branch alias (if any)
        from sase.core.branch_map import remove_branch_alias

        remove_branch_alias(patch.project_basename, patch.name)

        if console:
            console.print(
                f"[green]Pruned revision: {humanize_cl_name(patch.name)}[/green]"
            )

    # Rename the Patch (skip if name is unchanged, e.g., WIP with existing suffix)
    if new_name != patch.name:
        try:
            rename_changespec_with_references(  # legacy compatibility alias
                patch.file_path, patch.name, new_name
            )
        except Exception as e:
            return (False, f"Failed to rename Patch: {e}")

        if console:
            console.print(
                "[green]Renamed Patch: "
                f"{humanize_cl_name(patch.name)} → "
                f"{humanize_cl_name(new_name)}[/green]"
            )

    # Update STATUS to Reverted
    success, _, error, _ = transition_changespec_status(  # legacy compatibility alias
        patch.file_path,
        new_name,  # Use the new name after rename
        "Reverted",
        validate=False,
    )
    if not success:
        return (False, f"Failed to update status: {error}")

    # Remove PR field (only if there was a PR to reset).
    if patch.pr_url is not None:
        reset_changespec_pr_url(patch.file_path, new_name)  # legacy compat alias

    if console:
        console.print("[green]Status updated to Reverted, PR removed[/green]")

    return (True, None)


update_changespec_name_atomic = update_patch_name_atomic  # legacy compatibility alias
revert_changespec = revert_patch  # legacy compatibility alias
