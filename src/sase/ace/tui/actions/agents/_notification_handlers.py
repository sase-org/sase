"""Simple notification action handlers.

Dispatches jump-to-agent, jump-to-patch, view-error-report, tmux, and
Launch settings actions.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

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


def handle_open_launch_control(app: object, notification: Notification) -> bool:
    """Open Launch settings from a usage-limit notification.

    Args:
        app: The AceApp instance.
        notification: The notification that requested Launch settings.

    Returns:
        True if Launch settings were opened.
    """
    del notification
    opener = getattr(app, "action_open_models_panel", None)
    if not callable(opener):
        opener = getattr(app, "_open_models_panel", None)
    if not callable(opener):
        app.notify("Launch settings are unavailable", severity="warning")  # type: ignore[attr-defined]
        return False
    opener()
    return True


def handle_jump_to_patch(app: object, notification: Notification) -> bool:
    """Jump to the patch referenced in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing patch_name.

    Returns:
        True if the patch was found and selected.
    """
    from ._notification_navigation import navigate_to_patch_tab

    patch_name = notification.action_data.get("patch_name")
    if not patch_name:
        app.notify("No patch_name in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    project_file = notification.action_data.get("project_file", "")
    return navigate_to_patch_tab(app, patch_name, project_file)


def handle_jump_to_mentor_review(app: object, notification: Notification) -> bool:
    """Jump to the patch and open Mentor Review iff comments exist.

    Navigates to the Patches tab, selects the target Patch, then — if the
    referenced entry has reviewable mentors — pushes the Mentor Review modal.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            ``patch_name``, ``project_file``, and ``entry_id``.

    Returns:
        True if navigation succeeded (modal push is best-effort).
    """
    from ...actions.agent_workflow._mentor_review import has_reviewable_mentors
    from . import _notification_navigation

    patch_name = notification.action_data.get("patch_name")
    legacy_payload = False
    if not patch_name:
        patch_name = notification.action_data.get(  # legacy compatibility alias
            "changespec_name"
        )
        legacy_payload = bool(patch_name)
    if not patch_name:
        app.notify("No patch_name in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    project_file = notification.action_data.get("project_file", "")
    entry_id = notification.action_data.get("entry_id")

    navigate = (
        _notification_navigation.navigate_to_changespec_tab  # legacy compatibility alias
        if legacy_payload
        else _notification_navigation.navigate_to_patch_tab
    )
    if not navigate(app, patch_name, project_file):
        return False

    if not entry_id:
        return True

    # Look up the freshly-selected Patch and the matching MentorEntry.
    patches = getattr(
        app,
        "patches",
        getattr(app, "changespecs", []),  # legacy compatibility alias
    )
    current_idx = app.current_idx  # type: ignore[attr-defined]
    if current_idx is None or current_idx < 0 or current_idx >= len(patches):
        return True

    patch = patches[current_idx]
    if not patch.mentors:
        return True

    target_entry = None
    for entry in patch.mentors:
        if entry.entry_id == entry_id:
            target_entry = entry
            break

    if target_entry is None:
        return True

    if not has_reviewable_mentors(target_entry):
        return True

    app._open_mentor_review_for_entry(patch, target_entry)  # type: ignore[attr-defined]
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
