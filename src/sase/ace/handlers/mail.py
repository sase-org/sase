"""Handler for the mail tool action."""

import os
import sys
from typing import TYPE_CHECKING

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from rich.console import Console
from rich.markup import escape as _esc

from ..patch import Patch
from ..mail_ops import MailPrepResult, execute_mail, prepare_mail
from ..operations import update_to_patch
from sase.project_display_names import humanize_cl_name

if TYPE_CHECKING:
    from ..tui._workflow_context import WorkflowContext


def handle_mail_prepare(
    self: "WorkflowContext",
    patch: Patch,
    workspace_dir: str,
) -> MailPrepResult | None:
    """Interactive part: checkout + prepare_mail (y/n prompt). Runs in suspend().

    Args:
        self: The WorkflowContext instance (provides console for terminal output)
        patch: Current Patch
        workspace_dir: The workspace directory to use

    Returns:
        MailPrepResult if checkout succeeded and prepare completed,
        None if checkout failed or prepare was aborted.
    """
    # Update to the patch branch
    success, error_msg = update_to_patch(
        patch,
        self.console,
        revision=patch.name,
        workspace_dir=workspace_dir,
    )
    if not success:
        self.console.print(f"[red]Error: {_esc(str(error_msg))}[/red]")
        return None

    # Run prepare_mail (interactive y/n prompt)
    return prepare_mail(patch, workspace_dir, self.console)


def mail_execute_task(
    patch: Patch,
    workspace_dir: str,
    workspace_num: int,
    *,
    release: bool = True,
) -> tuple[bool, str]:
    """Non-interactive: execute_mail + status transition. Runs as a proc.

    Releases workspace in finally block unless settlement owns that release.

    Args:
        patch: The Patch to mail
        workspace_dir: The workspace directory
        workspace_num: Workspace number for release
        release: When False, leave the claim for durable proc settlement.

    Returns:
        Tuple of (success, message).
    """
    from sase.running_field import release_workspace
    from sase.status_state_machine import (
        transition_patch_status,
    )

    console = Console()
    display_name = humanize_cl_name(patch.name)

    try:
        # Execute the mail command
        success = execute_mail(patch, workspace_dir, console)
        if not success:
            return (False, f"Mail failed for {display_name}")

        # Update status to "Mailed"
        status_success, old_status, status_error, _ = transition_patch_status(
            patch.file_path,
            patch.name,
            "Mailed",
            validate=True,
        )
        if status_success:
            return (
                True,
                f"Mailed {display_name}: {old_status or 'Ready'} → Mailed",
            )
        else:
            # Mailing succeeded but status update failed
            return (
                True,
                f"Mailed {display_name} "
                f"(status update failed: {status_error or 'Unknown'})",
            )

    finally:
        if release:
            release_workspace(
                patch.file_path,
                workspace_num,
                "mail",
                patch.name,
            )
