"""Simple notification action handlers.

Dispatches jump-to-agent, jump-to-patch, view-error-report, tmux, and
Launch settings actions.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

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
    from ._notification_navigation import (
        enter_agents_tab,
        jump_to_loaded_agent,
        resolve_loaded_agent,
    )

    cl_name = notification.action_data.get("cl_name")
    if not cl_name:
        app.notify("No cl_name in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    enter_agents_tab(app)

    agent_type = notification.action_data.get("agent_type")
    raw_suffix = notification.action_data.get("raw_suffix")

    def _matches(agent: object) -> bool:
        if getattr(agent, "cl_name", None) != cl_name:
            return False
        if (
            agent_type
            and getattr(getattr(agent, "agent_type", None), "value", None) != agent_type
        ):
            return False
        if raw_suffix and getattr(agent, "raw_suffix", None) != raw_suffix:
            return False
        return True

    target = resolve_loaded_agent(app, _matches)
    if target is None:
        message = f"Agent '{humanize_cl_name(str(cl_name))}' not found"
        app.notify(message, severity="warning")  # type: ignore[attr-defined]
        return False
    return jump_to_loaded_agent(app, target)


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
    if not isinstance(error_report, str) or not error_report.strip():
        # Fall back to first attached file
        if notification.files:
            error_report = str(notification.files[0])
        else:
            app.notify(_missing_error_report_message(notification), severity="warning")  # type: ignore[attr-defined]
            return False

    expanded = os.path.expanduser(error_report)
    if not os.path.exists(expanded):
        app.notify(_missing_error_report_message(notification), severity="warning")  # type: ignore[attr-defined]
        return False

    editor = os.environ.get("EDITOR") or "nvim"
    editor_args = build_editor_args(editor, [expanded])

    with app.suspend():  # type: ignore[attr-defined]
        subprocess.run(editor_args, check=False)

    return True


def _missing_error_report_message(notification: Notification) -> str:
    if notification.action != "GateExecutionFailed":
        return "No error report available"
    data = notification.action_data
    message = data.get("message") or data.get("code") or "gate execution failed"
    commands = [
        data.get("resume_command"),
        data.get("restart_command"),
        data.get("cancel_command"),
    ]
    usable = [command for command in commands if command]
    if not usable:
        return f"Gate execution failed: {message}. No error report is available."
    return (
        f"Gate execution failed: {message}. No error report is available. "
        f"Recovery: {'; '.join(usable)}"
    )


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


OPEN_TOOL_RUN_ACTION = "OpenToolRun"
"""Notification action that opens a settled ToolRun (epic sase-1bt, sase-189)."""


def _tool_run_node_matches(run: dict[str, object]) -> Callable[[Any], bool]:
    """Build a row predicate matching the run's owning node (§3.3, owner first)."""

    owner_kind = str(run.get("owner_kind") or "")
    owner_id = str(run.get("owner_id") or "")
    agent_name = str(run.get("agent") or "")

    def _matches(agent: object) -> bool:
        if getattr(agent, "fleet_origin_alias", None):
            return False
        if owner_kind == "monitor" and owner_id:
            return bool(
                getattr(agent, "is_monitor", False)
                and getattr(agent, "monitor_id", None) == owner_id
            )
        if owner_kind == "proc" and owner_id:
            return bool(
                getattr(agent, "is_named_proc", False)
                and getattr(agent, "proc_id", None) == owner_id
            )
        if not agent_name:
            return False
        return getattr(agent, "agent_name", None) == agent_name

    return _matches


def _resolve_visible_tool_run_node(app: object, run_id: str) -> object | None:
    """Return the visible local row owning *run_id*, or None (best-effort)."""

    try:
        from sase.core.tool_run import tool_run_show

        from ._notification_navigation import resolve_loaded_agent
    except Exception:
        return None
    try:
        envelope = tool_run_show(run_id)
    except Exception:
        return None
    run = envelope.get("run")
    if not isinstance(run, dict):
        return None
    try:
        return resolve_loaded_agent(app, _tool_run_node_matches(run))
    except Exception:
        return None


def _show_tools_deck_best_effort(app: object) -> None:
    """Show the Tools deck in the focused panel without ever raising."""

    try:
        from sase.ace.tui.widgets.decks.spec import active_deck_cycle
    except Exception:
        return
    try:
        cycle = active_deck_cycle()
        index = next(
            i
            for i, deck in enumerate(cycle)
            if str(getattr(deck, "value", deck)) == "tools"
        )
    except Exception:
        return
    show = getattr(app, "action_show_deck_at", None)
    if not callable(show):
        return
    try:
        show(index)
    except Exception:
        return


def handle_open_tool_run(app: object, notification: Notification) -> bool:
    """Open the settled ToolRun referenced by an OpenToolRun notification.

    When the run owns a visible local node, that node is selected and its
    Tools deck is shown; otherwise the Admin Center Tools pane opens focused
    on the run. Never raises: every lookup is best-effort.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing run_id.

    Returns:
        True if a handler ran.
    """
    from ._notification_navigation import jump_to_loaded_agent

    run_id = str((notification.action_data or {}).get("run_id") or "").strip()
    if not run_id:
        app.notify("No tool run in notification", severity="warning")  # type: ignore[attr-defined]
        return False
    try:
        target = _resolve_visible_tool_run_node(app, run_id)
    except Exception:
        target = None
    if target is not None:
        try:
            jumped = bool(jump_to_loaded_agent(app, target))
        except Exception:
            return False
        _show_tools_deck_best_effort(app)
        return jumped
    opener = getattr(app, "_open_config_center", None)
    if callable(opener):
        try:
            opener("tools", tool_run_focus_target=run_id)
            return True
        except Exception:
            pass
    legacy = getattr(app, "action_open_tool_runs_panel", None)
    if callable(legacy):
        try:
            legacy()
            return True
        except Exception:
            pass
    app.notify("Tools pane is unavailable", severity="warning")  # type: ignore[attr-defined]
    return False


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
