"""Notification action handlers for the ace TUI app.

Dispatches notification actions: JumpToChangeSpec, Tmux, HITL.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.notifications import Notification


def handle_jump_to_changespec(app: object, notification: Notification) -> bool:
    """Jump to the changespec referenced in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing changespec_name.

    Returns:
        True if the changespec was found and selected.
    """
    changespec_name = notification.action_data.get("changespec_name")
    if not changespec_name:
        app.notify("No changespec_name in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    app.current_tab = "changespecs"  # type: ignore[attr-defined]

    changespecs = app.changespecs  # type: ignore[attr-defined]
    for idx, cs in enumerate(changespecs):
        if cs.name == changespec_name:
            app.current_idx = idx  # type: ignore[attr-defined]
            return True

    app.notify(f"ChangeSpec '{changespec_name}' not found", severity="warning")  # type: ignore[attr-defined]
    return False


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


def handle_hitl(app: object, notification: Notification) -> bool:
    """Show the HITL modal for the workflow step in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            artifacts_dir and workflow_name.

    Returns:
        True if the HITL modal was pushed (response handled asynchronously).
    """
    import json
    from pathlib import Path

    from sase.xprompt import HITLResult

    from ...modals import WorkflowHITLInput, WorkflowHITLModal

    artifacts_dir = notification.action_data.get("artifacts_dir")
    workflow_name = notification.action_data.get("workflow_name", "unknown")
    if not artifacts_dir:
        app.notify("No artifacts_dir in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    artifacts_path = Path(artifacts_dir)
    request_path = artifacts_path / "hitl_request.json"

    if not request_path.exists():
        app.notify("No HITL request found", severity="warning")  # type: ignore[attr-defined]
        return False

    try:
        with open(request_path, encoding="utf-8") as f:
            request_data = json.load(f)
    except Exception as e:
        app.notify(f"Error reading HITL request: {e}", severity="error")  # type: ignore[attr-defined]
        return False

    input_data = WorkflowHITLInput(
        step_name=request_data.get("step_name", "unknown"),
        step_type=request_data.get("step_type", "agent"),
        output=request_data.get("output", {}),
        workflow_name=workflow_name,
        has_output=request_data.get("has_output", False),
        output_types=request_data.get("output_types") or {},
    )

    def on_dismiss(result: object) -> None:
        if result is None:
            return
        if not isinstance(result, HITLResult):
            return

        # Handle edit action
        if result.action == "edit":
            edited_output = app._edit_hitl_output(request_data.get("output", {}))  # type: ignore[attr-defined]
            if edited_output is not None:
                result = HITLResult(action="edit", edited_output=edited_output)
            else:
                return

        # Write response file
        response_path = artifacts_path / "hitl_response.json"
        response_data: dict[str, object] = {
            "action": result.action,
            "approved": result.approved,
        }
        if result.edited_output is not None:
            response_data["edited_output"] = result.edited_output
        if result.feedback is not None:
            response_data["feedback"] = result.feedback

        try:
            with open(response_path, "w", encoding="utf-8") as f:
                json.dump(response_data, f, indent=2, default=str)
            app.notify(f"Sent {result.action} response")  # type: ignore[attr-defined]
        except Exception as e:
            app.notify(f"Error writing response: {e}", severity="error")  # type: ignore[attr-defined]

    app.push_screen(WorkflowHITLModal(input_data), on_dismiss)  # type: ignore[attr-defined]
    return True


def handle_plan_approval(app: object, notification: Notification) -> bool:
    """Show the plan approval modal for a Claude Code plan.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            response_dir and session_id.

    Returns:
        True if the plan approval modal was pushed.
    """
    import json
    from pathlib import Path

    from ...modals import PlanApprovalModal, PlanApprovalResult

    response_dir = notification.action_data.get("response_dir")
    if not response_dir:
        app.notify("No response_dir in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    response_path = Path(response_dir)
    request_path = response_path / "plan_request.json"

    if not request_path.exists():
        app.notify("Plan approval request expired or not found", severity="warning")  # type: ignore[attr-defined]
        return False

    # Get plan file path from notification files
    if not notification.files:
        app.notify("No plan file in notification", severity="warning")  # type: ignore[attr-defined]
        return False

    plan_file = notification.files[0]

    def on_dismiss(result: object) -> None:
        if result is None:
            return
        if not isinstance(result, PlanApprovalResult):
            return

        # Write response file
        plan_response_path = response_path / "plan_response.json"
        response_data: dict[str, object] = {
            "action": result.action,
        }
        if result.feedback is not None:
            response_data["feedback"] = result.feedback

        try:
            with open(plan_response_path, "w", encoding="utf-8") as f:
                json.dump(response_data, f, indent=2)
            app.notify(f"Sent plan {result.action} response")  # type: ignore[attr-defined]
        except Exception as e:
            app.notify(f"Error writing response: {e}", severity="error")  # type: ignore[attr-defined]

    app.push_screen(PlanApprovalModal(plan_file), on_dismiss)  # type: ignore[attr-defined]
    return True
