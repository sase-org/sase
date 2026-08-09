"""Archive operations for ChangeSpecs."""

import os
import sys
from pathlib import Path

from rich.console import Console
from rich.markup import escape as escape_markup

# Add parent directory to path for status_state_machine import
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from sase.core.paths import sase_subdir
from sase.running_field import (
    claim_workspace,
    get_first_available_axe_workspace,
    get_workspace_directory_for_num,
    release_workspace,
)
from sase.status_state_machine import transition_changespec_status
from sase.vcs_provider import get_vcs_provider
from sase.project_display_names import humanize_cl_name

from .changespec import (
    ChangeSpec,
    find_all_changespecs,
)
from .hooks.processes import kill_and_persist_all_running_processes
from .operations import (
    calculate_lifecycle_new_name,
    has_active_children,
    rename_changespec_with_references,
    save_diff_to_file,
)


def archive_patch(
    changespec: ChangeSpec, console: Console | None = None
) -> tuple[bool, str | None]:
    """Archive a ChangeSpec by archiving its revision and updating its status.

    This function:
    1. Validates that the ChangeSpec has a valid PR set
    2. Validates that all children are Archived or Reverted
    3. Claims a workspace from the unified pool (#10+)
    4. Checks out the ChangeSpec branch
    5. Saves the diff to `~/.sase/archived/<new_name>.diff`
    6. Runs `sase_hg_archive <name>` to archive the revision
    7. Renames the ChangeSpec by appending `__<N>` suffix
    8. Updates STATUS to "Archived"
    9. Releases the claimed workspace

    Args:
        changespec: The ChangeSpec to archive
        console: Optional Rich Console for output

    Returns:
        Tuple of (success, error_message)
    """
    # Validate PR is set
    if changespec.pr_url is None:
        return (False, "ChangeSpec does not have a valid PR set")

    # Kill any running processes before archiving
    log_fn = (
        (lambda msg: console.print(f"[cyan]{escape_markup(msg)}[/cyan]"))
        if console
        else None
    )
    kill_and_persist_all_running_processes(
        changespec,
        changespec.file_path,
        changespec.name,
        "Killed hook running on archived ChangeSpec.",
        log_fn=log_fn,
    )

    # Get all changespecs to check for children and name conflicts
    all_changespecs = find_all_changespecs()

    # Validate no non-terminal children (different from revert!)
    if has_active_children(
        changespec, all_changespecs, terminal_statuses=("Archived", "Reverted")
    ):
        return (
            False,
            "Cannot archive: other ChangeSpecs have this one as their parent "
            "and are not Archived or Reverted",
        )

    # Get project basename for workspace operations
    from sase.ace.changespec.project_spec_path import project_spec_basename

    project_basename = project_spec_basename(changespec.file_path)

    # Claim a workspace from the unified pool (#10+) for the archive operation
    workspace_num = get_first_available_axe_workspace(changespec.file_path)
    workflow_name = f"archive-{changespec.name}"
    pid = os.getpid()

    try:
        workspace_dir, _ = get_workspace_directory_for_num(
            workspace_num, project_basename
        )
    except RuntimeError as e:
        return (False, f"Failed to get workspace directory: {e}")

    if console:
        console.print(f"[cyan]Claiming workspace #{workspace_num}[/cyan]")

    claim_result = claim_workspace(
        changespec.file_path, workspace_num, workflow_name, pid, changespec.name
    )
    if not claim_result.success:
        return (
            False,
            f"Failed to claim workspace #{workspace_num}: "
            f"{claim_result.error or 'unknown reason'}",
        )

    try:
        # Checkout the ChangeSpec branch
        if console:
            console.print(
                f"[cyan]Checking out {humanize_cl_name(changespec.name)}...[/cyan]"
            )

        provider = get_vcs_provider(workspace_dir)
        # Revision resolution is an identity boundary; keep the canonical name.
        resolved = provider.resolve_revision(
            changespec.name, project_basename, workspace_dir
        )
        success, error = provider.checkout(resolved, workspace_dir)
        if not success:
            return (False, f"Failed to checkout ChangeSpec branch: {error}")

        if console:
            console.print(
                f"[green]Checked out: {humanize_cl_name(changespec.name)}[/green]"
            )

        # Calculate new name with suffix
        new_name = calculate_lifecycle_new_name(changespec, all_changespecs)

        if console:
            console.print(
                f"[cyan]Renaming ChangeSpec to: {humanize_cl_name(new_name)}[/cyan]"
            )

        # Save diff to file
        success, error = save_diff_to_file(
            changespec, new_name, workspace_dir, "archived"
        )
        if not success:
            return (False, f"Failed to save diff: {error}")

        if console:
            # Paths remain canonical/copyable even though nearby prose is projected.
            diff_path = sase_subdir("archived") / f"{new_name}.diff"
            console.print(f"[green]Saved diff to: {diff_path}[/green]")

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

        # Run sase_hg_archive
        success, error = provider.archive(resolved, workspace_dir)
        if not success:
            return (False, f"Failed to archive revision: {error}")

        # Clean up branch alias (if any)
        from sase.core.branch_map import remove_branch_alias

        remove_branch_alias(project_basename, changespec.name)

        if console:
            console.print(
                f"[green]Archived revision: {humanize_cl_name(changespec.name)}[/green]"
            )

        # Rename the ChangeSpec (skip if name is unchanged, e.g., WIP with existing suffix)
        if new_name != changespec.name:
            try:
                rename_changespec_with_references(
                    changespec.file_path, changespec.name, new_name
                )
            except Exception as e:
                return (False, f"Failed to rename ChangeSpec: {e}")

            if console:
                console.print(
                    "[green]Renamed ChangeSpec: "
                    f"{humanize_cl_name(changespec.name)} -> "
                    f"{humanize_cl_name(new_name)}[/green]"
                )

        # Update STATUS to Archived
        success, _, error, _ = transition_changespec_status(
            changespec.file_path,
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
            changespec.file_path,
            workspace_num,
            workflow_name,
            changespec.name,
        )
        if console:
            console.print(f"[cyan]Released workspace #{workspace_num}[/cyan]")


archive_changespec = archive_patch
