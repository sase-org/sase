"""Handler functions for the work subcommand."""

from .edit_hooks import handle_edit_hooks
from .mail import handle_mail_prepare, mail_execute_task
from .reword import add_tag_task, handle_reword
from .show_diff import handle_show_diff
from .workflow_handlers import (
    handle_run_crs_workflow,
    handle_run_fix_hook_workflow,
    handle_run_workflow,
)

__all__ = [
    # Workflow handlers
    "handle_run_workflow",
    "handle_run_fix_hook_workflow",
    "handle_run_crs_workflow",
    # Tool handlers
    "add_tag_task",
    "handle_show_diff",
    "handle_edit_hooks",
    "mail_execute_task",
    "handle_mail_prepare",
    "handle_reword",
]
