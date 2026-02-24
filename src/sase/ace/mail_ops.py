"""Mail operations for the work subcommand."""

import os
import sys
from dataclasses import dataclass

from rich.console import Console
from rich.markup import escape as _esc

sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from sase.status_state_machine import (
    remove_ready_to_mail_suffix,
    transition_changespec_status,
)
from sase.vcs_provider import get_vcs_provider

from .changespec import ChangeSpec


@dataclass
class MailPrepResult:
    """Result of mail preparation (before actual mailing).

    Attributes:
        should_mail: True if the user confirmed they want to mail the CL.
    """

    should_mail: bool


def get_cl_description(
    revision: str,
    target_dir: str,
    console: Console,
    project_basename: str = "",
) -> tuple[bool, str | None]:
    """Get the CL description for a specific revision using cl_desc command.

    Args:
        revision: The revision/branch name to get the description for
        target_dir: Directory to run cl_desc in
        console: Rich console for output
        project_basename: Project basename for resolving ChangeSpec names to git refs

    Returns:
        Tuple of (success, description or None)
    """
    provider = get_vcs_provider(target_dir)
    if project_basename:
        revision = provider.resolve_revision(revision, project_basename, target_dir)
    success, result = provider.get_description(revision, target_dir)
    if not success:
        console.print(f"[red]{_esc(str(result))}[/red]")
        return False, None
    return True, result


def prepare_mail(
    changespec: ChangeSpec, target_dir: str, console: Console
) -> MailPrepResult | None:
    """Prepare for mailing a CL / pushing a PR.

    Delegates to workspace provider plugins via the ``ws_prepare_mail``
    hook. Each plugin implements VCS-specific logic (git: display branch
    info and confirm push; hg: reviewer prompts, startblock, reword).

    Args:
        changespec: The ChangeSpec to prepare for mailing
        target_dir: The workspace directory for the CL
        console: Rich console for output

    Returns:
        MailPrepResult if successful (with should_mail indicating user's choice),
        None if the operation was aborted or failed.
    """
    from sase.workspace_provider import prepare_mail as ws_prepare_mail

    result = ws_prepare_mail(
        changespec_name=changespec.name,
        changespec_parent=changespec.parent,
        project_basename=changespec.project_basename,
        project_file=changespec.file_path,
        target_dir=target_dir,
        console=console,
    )
    return result  # type: ignore[return-value]


def execute_mail(changespec: ChangeSpec, target_dir: str, console: Console) -> bool:
    """Execute the mail / push+PR command.

    This does NOT update the project file - the caller is responsible for
    updating the status appropriately.

    Args:
        changespec: The ChangeSpec to mail
        target_dir: The workspace directory for the CL
        console: Rich console for output

    Returns:
        True if mailing succeeded, False otherwise
    """
    console.print(f"[cyan]Sending change for review: {_esc(changespec.name)}[/cyan]")
    provider = get_vcs_provider(target_dir)
    resolved = provider.resolve_revision(
        changespec.name, changespec.project_basename, target_dir
    )
    success, error = provider.mail(resolved, target_dir)
    if not success:
        console.print(f"[red]{_esc(str(error))}[/red]")
        return False

    # If ChangeSpec has no CL URL yet (git, PR just created), update it
    if changespec.cl is None:
        url_ok, change_url = provider.get_change_url(target_dir)
        if url_ok and change_url:
            from sase.status_state_machine import update_changespec_cl_atomic

            update_changespec_cl_atomic(
                changespec.file_path, changespec.name, change_url
            )
            console.print(f"[green]PR created: {change_url}[/green]")

    console.print("[green]Change sent for review successfully![/green]")
    return True


def handle_mail(changespec: ChangeSpec, target_dir: str, console: Console) -> bool:
    """Handle mailing a CL with startblock configuration.

    This is the main entry point for the "m" (mail) action. It performs
    mail prep, executes the mail command, and updates the project file.

    Args:
        changespec: The ChangeSpec to mail
        target_dir: The workspace directory for the CL
        console: Rich console for output

    Returns:
        True if mailing succeeded, False otherwise
    """
    # Run mail prep
    prep_result = prepare_mail(changespec, target_dir, console)
    if prep_result is None:
        return False

    if not prep_result.should_mail:
        return False

    # Execute the mail command
    success = execute_mail(changespec, target_dir, console)
    if not success:
        return False

    # Remove READY TO MAIL suffix if present before transitioning
    remove_ready_to_mail_suffix(changespec.file_path, changespec.name)

    # Update status to "Mailed"
    console.print("[cyan]Updating status to 'Mailed'...[/cyan]")
    status_success, old_status, status_error, _ = transition_changespec_status(
        changespec.file_path,
        changespec.name,
        "Mailed",
        validate=True,
    )
    if status_success:
        console.print(
            f"[green]Status updated: {old_status if old_status else 'Ready'} → Mailed[/green]"
        )
        return True
    else:
        console.print(
            f"[yellow]Warning: CL was mailed but status update failed: "
            f"{status_error if status_error else 'Unknown error'}[/yellow]"
        )
        return True  # Still return True since mailing succeeded
