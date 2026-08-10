"""Restore operations for reverted Patches."""

import os
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape as _esc

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from sase.core.patch import (
    get_workspace_directory_for_patch,
    strip_reverted_suffix,
)
from sase.core.paths import sase_subdir
from sase.core.shell import run_workspace_command
from sase.running_field import (
    update_running_field_cl_name,
)
from sase.vcs_provider import get_vcs_provider
from sase.project_display_names import humanize_cl_name

from .patch import Patch, find_all_patches
from .revert import update_patch_name_atomic

find_all_changespecs = find_all_patches  # legacy compatibility alias
update_changespec_name_atomic = update_patch_name_atomic  # legacy compatibility alias


def list_reverted_patches() -> list[Patch]:
    """Find all Patches with "Reverted" status.

    Returns:
        List of Patches that have status "Reverted"
    """
    all_patches = find_all_patches()
    return [cs for cs in all_patches if cs.status == "Reverted"]


def _clear_hook_status_lines_for_last_history(
    patch: Patch, base_name: str, console: Console | None = None
) -> tuple[bool, str | None]:
    """Clear hook status lines for the last COMMITS entry so hooks will rerun.

    This removes the status line for the last COMMITS entry from every hook,
    allowing sase axe to rerun all hooks after a restore.

    Args:
        patch: The Patch being restored
        base_name: The base name (after stripping __<N> suffix)
        console: Optional Rich Console for output

    Returns:
        Tuple of (success, error_message)
    """
    from .patch import HookEntry
    from .hooks import get_last_history_entry_id, update_patch_hooks_field

    # Skip if no hooks
    if not patch.hooks:
        return (True, None)

    # Get the last COMMITS entry ID
    last_history_entry_id = get_last_history_entry_id(patch)
    if last_history_entry_id is None:
        # No history entries, nothing to clear
        return (True, None)

    # Build updated hooks list with status lines for last COMMITS entry removed
    updated_hooks: list[HookEntry] = []
    hooks_cleared = 0

    for hook in patch.hooks:
        if hook.status_lines:
            # Keep all status lines except the one for the last COMMITS entry
            remaining_status_lines = [
                sl for sl in hook.status_lines if sl.stitch_num != last_history_entry_id
            ]
            if len(remaining_status_lines) < len(hook.status_lines):
                hooks_cleared += 1
            updated_hooks.append(
                HookEntry(
                    command=hook.command,
                    status_lines=(
                        remaining_status_lines if remaining_status_lines else None
                    ),
                )
            )
        else:
            updated_hooks.append(hook)

    # Update the project file with the cleared hooks
    # Use base_name since the Patch may have been renamed
    success = update_patch_hooks_field(
        patch.file_path,
        base_name,
        updated_hooks,
    )

    if not success:
        return (False, "Failed to clear hook status lines")

    if console and hooks_cleared > 0:
        console.print(
            f"[green]Cleared status for {hooks_cleared} hook(s) - "
            f"will be rerun by sase axe[/green]"
        )

    return (True, None)


def restore_patch(
    patch: Patch, console: Console | None = None
) -> tuple[bool, str | None]:
    """Restore a reverted or archived Patch by re-applying its diff and creating a new PR.

    This function:
    1. Validates that the Patch has "Reverted" or "Archived" status
    2. Renames the Patch to remove the __<N> suffix
    3. Checks out the parent revision
    4. Applies the stashed diff via the VCS provider
    5. Runs sase stitch create with the base name (which will find the renamed Patch)

    Args:
        patch: The Patch to restore
        console: Optional Rich Console for output

    Returns:
        Tuple of (success, error_message)
    """
    # Validate status is "Reverted" or "Archived"
    if patch.status not in ("Reverted", "Archived"):
        return (
            False,
            f"Patch status is '{patch.status}', not 'Reverted' or 'Archived'",
        )

    # Get workspace directory
    workspace_dir = get_workspace_directory_for_patch(patch)
    if not workspace_dir:
        return (False, "Could not determine workspace directory")

    if not os.path.isdir(workspace_dir):
        return (False, f"Workspace directory does not exist: {workspace_dir}")

    # Extract base name (without __<N> suffix)
    base_name = strip_reverted_suffix(patch.name)
    if console:
        console.print(f"[cyan]Base name: {_esc(humanize_cl_name(base_name))}[/cyan]")

    # Rename the Patch to remove the __<N> suffix
    # This allows sase stitch create to find it and use its description
    if base_name != patch.name:
        try:
            update_patch_name_atomic(patch.file_path, patch.name, base_name)
            if console:
                console.print(
                    "[green]Renamed Patch: "
                    f"{_esc(humanize_cl_name(patch.name))} → "
                    f"{_esc(humanize_cl_name(base_name))}[/green]"
                )
            # Also update any RUNNING field entries that reference the old name
            update_running_field_cl_name(patch.file_path, patch.name, base_name)
        except Exception as e:
            return (False, f"Failed to rename Patch: {e}")

    # Clear hook status lines for the last COMMITS entry so hooks will rerun
    success, error = _clear_hook_status_lines_for_last_history(
        patch, base_name, console
    )
    if not success:
        return (False, error)

    # Determine update target
    provider = get_vcs_provider(workspace_dir)
    update_target = (
        patch.parent
        if patch.parent
        else provider.get_default_parent_revision(workspace_dir)
    )
    # Checkout and command arguments below are canonical execution values.
    update_target = provider.resolve_revision(
        update_target, patch.project_basename, workspace_dir
    )
    if console:
        console.print(f"[cyan]Updating to: {update_target}[/cyan]")
    success, error = provider.checkout(update_target, workspace_dir)
    if not success:
        return (False, error)

    if console:
        console.print(f"[green]Updated to: {update_target}[/green]")

    # Check for diff file in reverted or archived directory
    diff_file = sase_subdir("reverted") / f"{patch.name}.diff"
    if not diff_file.exists():
        # Try archived directory
        diff_file = sase_subdir("archived") / f"{patch.name}.diff"
    if not diff_file.exists():
        return (False, "Diff file not found in reverted or archived directory")

    if console:
        console.print(f"[cyan]Importing diff: {diff_file}[/cyan]")

    # Apply patch
    success, error = provider.apply_patch(str(diff_file), workspace_dir)
    if not success:
        return (False, error)

    if console:
        console.print("[green]Diff imported successfully[/green]")

    # Run sase stitch create - it will find the renamed Patch and use its description
    if console:
        # Keep the exact command argument visible and copyable.
        console.print(f"[cyan]Running sase stitch create {base_name}...[/cyan]")

    success, error = run_workspace_command(
        ["sase", "stitch", "create", base_name], workspace_dir, capture_output=False
    )
    if not success:
        return (False, error)

    if console:
        console.print("[green]Patch restored successfully[/green]")

    return (True, None)


list_reverted_changespecs = list_reverted_patches  # legacy compatibility alias
restore_changespec = restore_patch  # legacy compatibility alias
