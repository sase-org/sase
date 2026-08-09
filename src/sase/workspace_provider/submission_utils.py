"""Shared submission utilities (VCS-agnostic).

Provides :func:`finalize_submission` which renames a Patch with a
timestamp suffix and transitions its status to Submitted.  Used by both
the bare-git and GitHub workspace plugins.
"""

from rich.console import Console
from rich.markup import escape as escape_markup

from sase.ace.operations import rename_patch_with_references
from sase.core.time import generate_timestamp
from sase.status_state_machine import transition_patch_status


def finalize_submission(
    patch_file: str,
    changespec_name: str,
    console: Console | None,
) -> tuple[bool, str | None]:
    """Rename Patch with timestamp and transition to Submitted."""
    from sase.ace.patch.project_spec_path import project_spec_basename
    from sase.core.branch_map import remove_branch_alias

    project_basename = project_spec_basename(patch_file)
    remove_branch_alias(project_basename, changespec_name)

    timestamp = generate_timestamp()
    new_name = f"{changespec_name}__{timestamp}"

    if console:
        console.print(f"[cyan]Renaming Patch to: {escape_markup(new_name)}[/cyan]")

    try:
        rename_patch_with_references(patch_file, changespec_name, new_name)
    except Exception as e:
        return (False, f"Failed to rename Patch: {e}")

    if console:
        console.print(
            f"[green]Renamed ChangeSpec: {escape_markup(changespec_name)} -> {escape_markup(new_name)}[/green]"
        )

    # Transition status to Submitted
    success, _, error, _ = transition_patch_status(
        patch_file,
        new_name,
        "Submitted",
        validate=False,
    )
    if not success:
        return (False, f"Failed to update status: {error}")

    if console:
        console.print("[green]Status updated to Submitted[/green]")

    return (True, None)
