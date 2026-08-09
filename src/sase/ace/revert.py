"""Revert operations for ChangeSpecs."""

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
    ChangeSpec,
    changespec_lock,
    find_all_patches,
    write_changespec_atomic,
)
from .hooks.processes import kill_and_persist_all_running_processes
from .operations import (
    calculate_lifecycle_new_name,
    has_active_children,
    rename_changespec_with_references as rename_patch_with_references,
    save_diff_to_file,
)


def has_children(changespec: ChangeSpec, all_changespecs: list[ChangeSpec]) -> bool:
    """Check if any non-reverted ChangeSpec has this one as a parent.

    Args:
        changespec: The ChangeSpec to check for children
        all_changespecs: All ChangeSpecs to search through

    Returns:
        True if any non-reverted ChangeSpec has this one as parent, False otherwise
    """
    return has_active_children(changespec, all_changespecs)


def update_changespec_name_atomic(
    project_file: str, old_name: str, new_name: str
) -> None:
    """Update the NAME field of a specific ChangeSpec in the project file.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file
        old_name: Current NAME value of the ChangeSpec
        new_name: New NAME value
    """
    with changespec_lock(project_file):
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

        write_changespec_atomic(
            project_file,
            "".join(updated_lines),
            f"Rename ChangeSpec {old_name} to {new_name}",
        )


def revert_patch(
    changespec: ChangeSpec, console: Console | None = None
) -> tuple[bool, str | None]:
    """Revert a ChangeSpec by pruning its revision and updating its status.

    This function:
    1. Validates that the ChangeSpec has a valid PR set
    2. Validates that the ChangeSpec has no children
    3. Renames the ChangeSpec by appending `__<N>` suffix
    4. Saves the diff to `~/.sase/reverted/<new_name>.diff`
    5. Runs `sase_hg_prune <name>` to remove the revision
    6. Updates STATUS to "Reverted" and removes the PR field

    Args:
        changespec: The ChangeSpec to revert
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
        changespec,
        changespec.file_path,
        changespec.name,
        "Killed hook running on reverted ChangeSpec.",
        log_fn=log_fn,
    )

    # Get all changespecs to check for children and name conflicts
    all_changespecs = find_all_patches()

    # Validate no children
    if has_children(changespec, all_changespecs):
        return (
            False,
            "Cannot revert: other Patches have this one as their parent",
        )

    # Calculate new name with suffix
    new_name = calculate_lifecycle_new_name(changespec, all_changespecs)

    if console:
        console.print(
            f"[cyan]Renaming ChangeSpec to: {humanize_cl_name(new_name)}[/cyan]"
        )

    # PR-dependent operations: save diff, prune VCS revision, reset PR URL.
    if changespec.pr_url is not None:
        # Get workspace directory
        workspace_dir = get_workspace_directory_for_patch(changespec)
        if not workspace_dir:
            return (False, "Could not determine workspace directory")

        if not os.path.isdir(workspace_dir):
            return (False, f"Workspace directory does not exist: {workspace_dir}")

        # Save diff to file
        success, error = save_diff_to_file(
            changespec, new_name, workspace_dir, "reverted"
        )
        if not success:
            return (False, f"Failed to save diff: {error}")

        if console:
            # This is a copyable storage path, so its canonical stem is intentional.
            diff_path = sase_subdir("reverted") / f"{new_name}.diff"
            console.print(f"[green]Saved diff to: {diff_path}[/green]")

        # Run sase_hg_prune
        provider = get_vcs_provider(workspace_dir)
        # Provider revision matching must retain canonical ChangeSpec identity.
        resolved = provider.resolve_revision(
            changespec.name, changespec.project_basename, workspace_dir
        )

        # Abandon remote change (close PR, drop legacy change, etc.)
        success, error = provider.abandon_change(
            changespec.pr_url, resolved, workspace_dir
        )
        if not success:
            return (False, f"Failed to abandon remote change: {error}")

        if console:
            console.print(
                f"[green]Abandoned remote change: {changespec.pr_url}[/green]"
            )

        success, error = provider.prune(resolved, workspace_dir)
        if not success:
            return (False, f"Failed to prune revision: {error}")

        # Clean up branch alias (if any)
        from sase.core.branch_map import remove_branch_alias

        remove_branch_alias(changespec.project_basename, changespec.name)

        if console:
            console.print(
                f"[green]Pruned revision: {humanize_cl_name(changespec.name)}[/green]"
            )

    # Rename the ChangeSpec (skip if name is unchanged, e.g., WIP with existing suffix)
    if new_name != changespec.name:
        try:
            rename_patch_with_references(
                changespec.file_path, changespec.name, new_name
            )
        except Exception as e:
            return (False, f"Failed to rename ChangeSpec: {e}")

        if console:
            console.print(
                "[green]Renamed ChangeSpec: "
                f"{humanize_cl_name(changespec.name)} → "
                f"{humanize_cl_name(new_name)}[/green]"
            )

    # Update STATUS to Reverted
    success, _, error, _ = transition_patch_status(
        changespec.file_path,
        new_name,  # Use the new name after rename
        "Reverted",
        validate=False,
    )
    if not success:
        return (False, f"Failed to update status: {error}")

    # Remove PR field (only if there was a PR to reset).
    if changespec.pr_url is not None:
        reset_patch_pr_url(changespec.file_path, new_name)

    if console:
        console.print("[green]Status updated to Reverted, PR removed[/green]")

    return (True, None)


update_patch_name_atomic = update_changespec_name_atomic
revert_changespec = revert_patch  # legacy API alias
