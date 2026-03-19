"""Handler for the mail tool action."""

import os
import sys
from typing import TYPE_CHECKING

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from rich.console import Console
from rich.markup import escape as _esc

from ..changespec import ChangeSpec
from ..mail_ops import MailPrepResult, execute_mail, prepare_mail
from ..operations import update_to_changespec

if TYPE_CHECKING:
    from ..tui._workflow_context import WorkflowContext


def handle_mail_prepare(
    self: "WorkflowContext",
    changespec: ChangeSpec,
    workspace_dir: str,
) -> MailPrepResult | None:
    """Interactive part: checkout + prepare_mail (y/n prompt). Runs in suspend().

    Args:
        self: The WorkflowContext instance (provides console for terminal output)
        changespec: Current ChangeSpec
        workspace_dir: The workspace directory to use

    Returns:
        MailPrepResult if checkout succeeded and prepare completed,
        None if checkout failed or prepare was aborted.
    """
    # Update to the changespec branch
    success, error_msg = update_to_changespec(
        changespec,
        self.console,
        revision=changespec.name,
        workspace_dir=workspace_dir,
    )
    if not success:
        self.console.print(f"[red]Error: {_esc(str(error_msg))}[/red]")
        return None

    # Run prepare_mail (interactive y/n prompt)
    return prepare_mail(changespec, workspace_dir, self.console)


def mail_execute_task(
    changespec: ChangeSpec,
    workspace_dir: str,
    workspace_num: int,
) -> tuple[bool, str]:
    """Non-interactive: execute_mail + status transition. Runs as background task.

    Releases workspace in finally block.

    Args:
        changespec: The ChangeSpec to mail
        workspace_dir: The workspace directory
        workspace_num: Workspace number for release

    Returns:
        Tuple of (success, message).
    """
    from sase.running_field import release_workspace
    from sase.status_state_machine import transition_changespec_status

    console = Console()

    try:
        # Execute the mail command
        success = execute_mail(changespec, workspace_dir, console)
        if not success:
            return (False, f"Mail failed for {changespec.name}")

        # Update status to "Mailed"
        status_success, old_status, status_error, _ = transition_changespec_status(
            changespec.file_path,
            changespec.name,
            "Mailed",
            validate=True,
        )
        if status_success:
            return (
                True,
                f"Mailed {changespec.name}: {old_status or 'Ready'} → Mailed",
            )
        else:
            # Mailing succeeded but status update failed
            return (
                True,
                f"Mailed {changespec.name} "
                f"(status update failed: {status_error or 'Unknown'})",
            )

    finally:
        # Always release the workspace
        release_workspace(
            changespec.file_path,
            workspace_num,
            "mail",
            changespec.name,
        )
