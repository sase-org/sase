"""HITL notification modal handling."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from ._notification_modal_responses import write_workflow_action_response

if TYPE_CHECKING:
    from sase.notifications import Notification


def handle_hitl(app: object, notification: Notification) -> bool:
    """Show the HITL modal for the workflow step in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            artifacts_dir and workflow_name.

    Returns:
        True if the HITL modal was pushed (response handled asynchronously).
    """
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

        if result.action == "edit":
            edited_output = app._edit_hitl_output(request_data.get("output", {}))  # type: ignore[attr-defined]
            if edited_output is not None:
                result = HITLResult(action="edit", edited_output=edited_output)
            else:
                return

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
            write_workflow_action_response(
                response_path,
                response_data,
                action_kind="hitl",
                notification_id=notification.id,
                default=str,
            )
            app.notify(f"Sent {result.action} response")  # type: ignore[attr-defined]
        except Exception as e:
            app.notify(f"Error writing response: {e}", severity="error")  # type: ignore[attr-defined]

    app.push_screen(WorkflowHITLModal(input_data), on_dismiss)  # type: ignore[attr-defined]
    return True
