"""Archive operations for Patches."""

import os
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape as escape_markup

# Add parent directory to path for status_state_machine import
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from sase.core.paths import sase_subdir
from sase.running_field import (
    WorkspaceClaimError,
    claim_next_axe_workspace_dir,
    release_workspace,
)
from sase.status_state_machine import transition_patch_status
from sase.vcs_provider import get_vcs_provider
from sase.project_display_names import humanize_cl_name

from .patch import (
    Patch,
    find_all_patches,
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
transition_changespec_status = transition_patch_status  # legacy compatibility alias


def archive_patch(
    patch: Patch, console: Console | None = None
) -> tuple[bool, str | None]:
    """Archive a Patch by archiving its revision and updating its status.

    This function:
    1. Validates that the Patch has a valid PR set
    2. Validates that all children are Archived or Reverted
    3. Claims a workspace from the unified pool (#10+)
    4. Checks out the Patch branch
    5. Saves the diff to `~/.sase/archived/<new_name>.diff`
    6. Runs `sase_hg_archive <name>` to archive the revision
    7. Renames the Patch by appending `__<N>` suffix
    8. Updates STATUS to "Archived"
    9. Releases the claimed workspace

    Args:
        patch: The Patch to archive
        console: Optional Rich Console for output

    Returns:
        Tuple of (success, error_message)
    """
    # Validate PR is set
    if patch.pr_url is None:
        return (False, "Patch does not have a valid PR set")

    # Kill any running processes before archiving
    log_fn = (
        (lambda msg: console.print(f"[cyan]{escape_markup(msg)}[/cyan]"))
        if console
        else None
    )
    kill_and_persist_all_running_processes(
        patch,
        patch.file_path,
        patch.name,
        "Killed hook running on archived Patch.",
        log_fn=log_fn,
    )

    # Get all patches to check for children and name conflicts
    all_patches = find_all_patches()

    # Validate no non-terminal children (different from revert!)
    if has_active_children(
        patch, all_patches, terminal_statuses=("Archived", "Reverted")
    ):
        return (
            False,
            "Cannot archive: other Patches have this one as their parent "
            "and are not Archived or Reverted",
        )

    # Get project basename for workspace operations
    from sase.ace.patch.project_spec_path import project_spec_basename

    project_basename = project_spec_basename(patch.file_path)

    workflow_name = f"archive-{patch.name}"
    try:
        workspace_num, workspace_dir, _ = claim_next_axe_workspace_dir(
            patch.file_path,
            workflow_name,
            os.getpid(),
            project_basename,
            cl_name=patch.name,
        )
    except WorkspaceClaimError as exc:
        return (False, f"Failed to claim workspace: {exc}")

    if console:
        console.print(f"[cyan]Claiming workspace #{workspace_num}[/cyan]")

    try:
        # Checkout the Patch branch
        if console:
            console.print(
                f"[cyan]Checking out {humanize_cl_name(patch.name)}...[/cyan]"
            )

        provider = get_vcs_provider(workspace_dir)
        # Revision resolution is an identity boundary; keep the canonical name.
        resolved = provider.resolve_revision(
            patch.name, project_basename, workspace_dir
        )
        success, error = provider.checkout(resolved, workspace_dir)
        if not success:
            return (False, f"Failed to checkout Patch branch: {error}")

        if console:
            console.print(f"[green]Checked out: {humanize_cl_name(patch.name)}[/green]")

        # Calculate new name with suffix
        new_name = calculate_lifecycle_new_name(patch, all_patches)

        if console:
            console.print(
                f"[cyan]Renaming Patch to: {humanize_cl_name(new_name)}[/cyan]"
            )

        # Save diff to file
        success, error = save_diff_to_file(patch, new_name, workspace_dir, "archived")
        if not success:
            return (False, f"Failed to save diff: {error}")

        if console:
            # Paths remain canonical/copyable even though nearby prose is projected.
            diff_path = sase_subdir("archived") / f"{new_name}.diff"
            console.print(f"[green]Saved diff to: {diff_path}[/green]")

        # Abandon remote change (close PR, drop legacy change, etc.)
        success, error = provider.abandon_change(patch.pr_url, resolved, workspace_dir)
        if not success:
            return (False, f"Failed to abandon remote change: {error}")

        if console:
            console.print(f"[green]Abandoned remote change: {patch.pr_url}[/green]")

        # Run sase_hg_archive
        success, error = provider.archive(resolved, workspace_dir)
        if not success:
            return (False, f"Failed to archive revision: {error}")

        # Clean up branch alias (if any)
        from sase.core.branch_map import remove_branch_alias

        remove_branch_alias(project_basename, patch.name)

        if console:
            console.print(
                f"[green]Archived revision: {humanize_cl_name(patch.name)}[/green]"
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
                    f"{humanize_cl_name(patch.name)} -> "
                    f"{humanize_cl_name(new_name)}[/green]"
                )

        # Update STATUS to Archived
        success, _, error, _ = transition_patch_status(
            patch.file_path,
            new_name,  # Use the new name after rename
            "Archived",
            validate=False,
        )
        if not success:
            return (False, f"Failed to update status: {error}")

        if console:
            console.print("[green]Status updated to Archived[/green]")

        return (True, None)

    finally:
        # Always release the workspace
        release_workspace(
            patch.file_path,
            workspace_num,
            workflow_name,
            patch.name,
        )
        if console:
            console.print(f"[cyan]Released workspace #{workspace_num}[/cyan]")


archive_changespec = archive_patch  # legacy compatibility alias
