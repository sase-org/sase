"""Shared submission utilities (VCS-agnostic).

Provides :func:`finalize_submission` which renames a ChangeSpec with a
timestamp suffix and transitions its status to Submitted.  Used by both
the bare-git and GitHub workspace plugins.
"""

from rich.console import Console
from rich.markup import escape as escape_markup

from sase.ace.operations import rename_changespec_with_references
from sase.core.time import generate_timestamp
from sase.status_state_machine import transition_changespec_status


def finalize_submission(
    changespec_file: str,
    changespec_name: str,
    console: Console | None,
) -> tuple[bool, str | None]:
    """Rename ChangeSpec with timestamp and transition to Submitted."""
    import os

    from sase.core.branch_map import remove_branch_alias

    project_basename = os.path.basename(changespec_file).replace(".gp", "")
    remove_branch_alias(project_basename, changespec_name)

    timestamp = generate_timestamp()
    new_name = f"{changespec_name}__{timestamp}"

    if console:
        console.print(f"[cyan]Renaming ChangeSpec to: {escape_markup(new_name)}[/cyan]")

    try:
        rename_changespec_with_references(changespec_file, changespec_name, new_name)
    except Exception as e:
        return (False, f"Failed to rename ChangeSpec: {e}")

    if console:
        console.print(
            f"[green]Renamed ChangeSpec: {escape_markup(changespec_name)} -> {escape_markup(new_name)}[/green]"
        )

    # Transition status to Submitted
    success, _, error, _ = transition_changespec_status(
        changespec_file,
        new_name,
        "Submitted",
        validate=False,
    )
    if not success:
        return (False, f"Failed to update status: {error}")

    if console:
        console.print("[green]Status updated to Submitted[/green]")

    return (True, None)
