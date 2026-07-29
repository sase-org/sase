"""Simple notification action handlers.

Dispatches jump-to-agent, jump-to-changespec, view-error-report, and tmux actions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.memory.review_tui import MemoryReviewTuiApp
from sase.project_display_names import humanize_cl_name

if TYPE_CHECKING:
    from sase.notifications import Notification


def handle_jump_to_agent(app: object, notification: Notification) -> bool:
    """Jump to the agent referenced in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing cl_name,
            and optionally agent_type and raw_suffix for precise matching.

    Returns:
        True if the agent was found and selected.
    """
    cl_name = notification.action_data.get("cl_name")
    if not cl_name:
        app.notify("No cl_name in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    app.current_tab = "agents"  # type: ignore[attr-defined]

    agent_type = notification.action_data.get("agent_type")
    raw_suffix = notification.action_data.get("raw_suffix")

    agents = app._agents  # type: ignore[attr-defined]
    for idx, agent in enumerate(agents):
        if agent.cl_name != cl_name:
            continue
        if agent_type and agent.agent_type.value != agent_type:
            continue
        if raw_suffix and agent.raw_suffix != raw_suffix:
            continue
        app.current_idx = idx  # type: ignore[attr-defined]
        return True

    message = f"Agent '{humanize_cl_name(str(cl_name))}' not found"
    app.notify(message, severity="warning")  # type: ignore[attr-defined]
    return False


def handle_view_error_report(app: object, notification: Notification) -> bool:
    """Open the error report file in $EDITOR for detailed error investigation.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            error_report_path.

    Returns:
        True if the error report was opened successfully.
    """
    import os
    import subprocess

    from sase.ace.hints import build_editor_args

    error_report = notification.action_data.get("error_report_path")
    if not error_report:
        # Fall back to first attached file
        if notification.files:
            error_report = notification.files[0]
        else:
            app.notify("No error report available", severity="warning")  # type: ignore[attr-defined]
            return False

    expanded = os.path.expanduser(error_report)
    if not os.path.exists(expanded):
        app.notify("Error report file not found", severity="warning")  # type: ignore[attr-defined]
        return False

    editor = os.environ.get("EDITOR") or "nvim"
    editor_args = build_editor_args(editor, [expanded])

    with app.suspend():  # type: ignore[attr-defined]
        subprocess.run(editor_args, check=False)

    return True


def handle_view_report(app: object, notification: Notification) -> bool:
    """Load and open a structured notification report."""
    from sase.ace.tui.modals.report_modal import ReportModal
    from sase.notifications import load_notification_report

    report = load_notification_report(notification)
    if report is None or report.document is None:
        reason = (
            report.error
            if report is not None and report.error
            else "report could not be loaded"
        )
        app.notify(f"Unable to open report: {reason}", severity="warning")  # type: ignore[attr-defined]
        return False

    app.push_screen(ReportModal(report))  # type: ignore[attr-defined]
    return True


def handle_memory_review(app: object, notification: Notification) -> bool:
    """Open the memory proposal review TUI for the notification proposal."""
    proposal_id = notification.action_data.get("proposal_id")
    if not proposal_id:
        app.notify("No proposal_id in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    with app.suspend():  # type: ignore[attr-defined]
        MemoryReviewTuiApp(initial_proposal_id=proposal_id).run()

    return True


def handle_jump_to_changespec(app: object, notification: Notification) -> bool:
    """Jump to the changespec referenced in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing changespec_name.

    Returns:
        True if the changespec was found and selected.
    """
    from ._notification_navigation import navigate_to_changespec_tab

    changespec_name = notification.action_data.get("changespec_name")
    if not changespec_name:
        app.notify("No changespec_name in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    project_file = notification.action_data.get("project_file", "")
    return navigate_to_changespec_tab(app, changespec_name, project_file)


def handle_jump_to_mentor_review(app: object, notification: Notification) -> bool:
    """Jump to the changespec and open Mentor Review iff comments exist.

    Navigates to the ChangeSpecs tab, selects the target ChangeSpec, then — if the
    referenced entry has reviewable mentors — pushes the Mentor Review modal.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            ``changespec_name``, ``project_file``, and ``entry_id``.

    Returns:
        True if navigation succeeded (modal push is best-effort).
    """
    from ...actions.agent_workflow._mentor_review import has_reviewable_mentors
    from ._notification_navigation import navigate_to_changespec_tab

    changespec_name = notification.action_data.get("changespec_name")
    if not changespec_name:
        app.notify("No changespec_name in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    project_file = notification.action_data.get("project_file", "")
    entry_id = notification.action_data.get("entry_id")

    if not navigate_to_changespec_tab(app, changespec_name, project_file):
        return False

    if not entry_id:
        return True

    # Look up the freshly-selected ChangeSpec and the matching MentorEntry.
    changespecs = app.changespecs  # type: ignore[attr-defined]
    current_idx = app.current_idx  # type: ignore[attr-defined]
    if current_idx is None or current_idx < 0 or current_idx >= len(changespecs):
        return True

    changespec = changespecs[current_idx]
    if not changespec.mentors:
        return True

    target_entry = None
    for entry in changespec.mentors:
        if entry.entry_id == entry_id:
            target_entry = entry
            break

    if target_entry is None:
        return True

    if not has_reviewable_mentors(target_entry):
        return True

    app._open_mentor_review_for_entry(changespec, target_entry)  # type: ignore[attr-defined]
    return True


def handle_tmux(app: object, notification: Notification) -> bool:
    """Open a tmux session for the workspace directory in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing workspace_dir.

    Returns:
        True if the tmux session was opened successfully.
    """
    import subprocess
    from pathlib import Path

    workspace_dir = notification.action_data.get("workspace_dir")
    if not workspace_dir:
        app.notify("No workspace_dir in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    session_name = Path(workspace_dir).name

    with app.suspend():  # type: ignore[attr-defined]
        try:
            subprocess.run(["tm", session_name], check=False)
        except FileNotFoundError:
            app.notify("tm command not found", severity="error")  # type: ignore[attr-defined]
            return False

    app.notify(f"Opened tmux for {session_name}")  # type: ignore[attr-defined]
    return True
