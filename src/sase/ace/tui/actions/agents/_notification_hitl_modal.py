"""HITL notification modal handling."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ._notification_modal_responses import write_workflow_action_response

if TYPE_CHECKING:
    from sase.notifications import Notification
    from sase.xprompt import HITLResult

    from ...modals import WorkflowHITLInput


@dataclass(frozen=True)
class _NeutralHitlModalData:
    input_data: WorkflowHITLInput
    choice_ids: tuple[str, ...]


def handle_hitl(app: object, notification: Notification) -> bool:
    """Show the HITL modal for the workflow step in the notification.

    Args:
        app: The AceApp instance.
        notification: The notification with action_data containing
            artifacts_dir and workflow_name.

    Returns:
        True if the HITL modal was pushed (response handled asynchronously).
    """
    if (
        notification.action_data.get("bundle_path")
        and notification.action_data.get("request_id")
        and notification.action_data.get("request_kind") == "hitl"
    ):
        return _handle_neutral_hitl(app, notification)

    return _handle_legacy_hitl(app, notification)


def _handle_legacy_hitl(app: object, notification: Notification) -> bool:
    """Keep the direct response writer for pre-gate workflow bundles only."""
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


def _handle_neutral_hitl(app: object, notification: Notification) -> bool:
    """Load neutral HITL data off-pump and resolve it through the executor."""
    from ...util.pump_tasks import spawn_pump_free_task

    async def load_and_open() -> None:
        try:
            data = await asyncio.to_thread(_load_neutral_hitl_data, notification)
        except Exception as exc:
            app.notify(f"Could not open HITL gate: {exc}", severity="error")  # type: ignore[attr-defined]
            return

        from sase.xprompt import HITLResult

        from ...modals import WorkflowHITLModal

        def on_dismiss(result: object) -> None:
            if not isinstance(result, HITLResult):
                return
            resolved = result
            if result.action == "edit":
                edited = app._edit_hitl_output(data.input_data.output)  # type: ignore[attr-defined]
                if edited is None:
                    return
                resolved = HITLResult(action="edit", edited_output=edited)
            choice_id = _neutral_hitl_choice_id(resolved, data.choice_ids)
            if choice_id is None:
                app.notify(  # type: ignore[attr-defined]
                    f"HITL action '{resolved.action}' is not offered by this gate",
                    severity="error",
                )
                return
            from ._notification_gate_execution import (
                GateSubmission,
                submit_gate_execution_task,
            )

            response_input: dict[str, object] = {
                "action": resolved.action,
                "approved": resolved.approved,
            }
            if resolved.edited_output is not None:
                response_input["edited_output"] = resolved.edited_output
            submit_gate_execution_task(
                app,
                notification,
                GateSubmission(
                    choice_id=choice_id,
                    feedback=resolved.feedback,
                    input_data=response_input,
                ),
            )

        app.push_screen(WorkflowHITLModal(data.input_data), on_dismiss)  # type: ignore[attr-defined]

    task = spawn_pump_free_task(
        app,
        load_and_open(),
        name=f"neutral-hitl-open:{notification.id}",
        registry_attr="_neutral_hitl_open_tasks",
    )
    if task is None:
        app.notify("HITL gate loading is unavailable", severity="error")  # type: ignore[attr-defined]
        return False
    return True


def _load_neutral_hitl_data(notification: Notification) -> _NeutralHitlModalData:
    from sase.notification_gates.hashing import load_and_verify_bundle
    from sase.notification_gates.models import GateChoice, GateError
    from sase.notification_gates.paths import resolve_notification_bundle

    from ...modals import WorkflowHITLInput

    bundle = resolve_notification_bundle(notification)
    if bundle is None or bundle.legacy or bundle.kind != "hitl":
        raise GateError(
            "missing_gate", notification.id, "notification has no neutral HITL gate"
        )
    envelope, _adapter = load_and_verify_bundle(bundle.root)
    raw_choices = envelope.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        raise GateError("invalid_request", "choices", "HITL gate has no choices")
    choices = tuple(
        GateChoice.from_mapping(raw, index) for index, raw in enumerate(raw_choices)
    )
    raw_payload = envelope.get("payload")
    payload = raw_payload if isinstance(raw_payload, dict) else {}
    output = payload.get("output", payload)
    if not isinstance(output, dict):
        output = {"value": output}
    raw_output_types = payload.get("output_types")
    output_types = (
        {str(key): str(value) for key, value in raw_output_types.items()}
        if isinstance(raw_output_types, dict)
        else {}
    )
    input_data = WorkflowHITLInput(
        step_name=str(
            payload.get("step_name")
            or payload.get("title")
            or envelope.get("request_id")
            or "unknown"
        ),
        step_type=str(payload.get("step_type") or "agent"),
        output=output,
        workflow_name=str(payload.get("workflow_name") or notification.sender),
        has_output=bool(payload.get("has_output", bool(output))),
        output_types=output_types,
    )
    return _NeutralHitlModalData(input_data, tuple(choice.id for choice in choices))


def _neutral_hitl_choice_id(
    result: HITLResult, choice_ids: tuple[str, ...]
) -> str | None:
    candidates = [result.action]
    if result.action == "accept":
        candidates.extend(("approve", "approved", "yes"))
    elif result.action == "reject":
        candidates.extend(("deny", "denied", "no"))
    for candidate in candidates:
        if candidate in choice_ids:
            return candidate
    if result.approved and len(choice_ids) == 1:
        return choice_ids[0]
    return None
