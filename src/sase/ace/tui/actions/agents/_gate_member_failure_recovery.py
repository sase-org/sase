"""Open shared gate-failure recovery from a gate member row.

Use-site helper: imported lazily from
:mod:`sase.ace.tui.actions.agents._agent_enter_action` so the recovery
wiring stays out of the TUI startup closure. Reuses
:func:`handle_gate_execution_failed` so a dismissed ``GateExecutionFailed``
notification does not block recovery: the member's persisted
``gate_execution_failure`` builds an equivalent action payload.
"""

from __future__ import annotations

from typing import Any


def open_gate_member_failure_recovery(app: Any, agent: Any) -> bool:
    """Open the shared failure recovery modal for *agent*. Return True if opened."""
    failure = getattr(agent, "gate_execution_failure", None)
    if not isinstance(failure, dict):
        return False
    try:
        from sase.notifications.models import Notification

        from ._notification_gate_recovery import handle_gate_execution_failed

        action_data = {
            str(key): str(value)
            for key, value in failure.items()
            if key
            in {
                "bundle_path",
                "request_id",
                "request_kind",
                "gate_ref",
                "gate_turn_ref",
                "gate_notification_id",
                "failed_notification_id",
                "acceptance_id",
                "attempt_id",
                "outcome_id",
                "stage",
                "code",
                "message",
                "error_record",
                "error_report_path",
                "recovery_actions",
                "resume_command",
                "restart_command",
                "cancel_command",
            }
            and isinstance(value, str)
        }
        bundle_path = getattr(agent, "gate_bundle_path", "") or ""
        if bundle_path and not action_data.get("bundle_path"):
            action_data["bundle_path"] = str(bundle_path)
        notification = Notification(
            id=f"gate-member-failure:{getattr(agent, 'gate_id', '')}",
            timestamp="",
            sender="gate",
            action="GateExecutionFailed",
            action_data=action_data,
        )
        return bool(handle_gate_execution_failed(app, notification))
    except Exception:
        return False


__all__ = ["open_gate_member_failure_recovery"]
