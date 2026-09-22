"""Shared dispatcher for notification actions.

The per-action routing chain used to live inside
``AgentNotificationModalMixin._show_notification_modal._on_dismiss``. It is
extracted here so the Agents-tab Enter flow (phase ``resolve`` of the
``agents_enter_act_on_agent`` epic) can open a gate notification without
going through the NotificationModal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sase.notification_gates.registry import (
    PRIVILEGED_GATE_ACTIONS,
    adapter_for_action,
)

if TYPE_CHECKING:
    from sase.notifications import Notification


def open_notification_action(app: Any, notification: Notification) -> bool:
    """Run the handler for *notification*'s action.

    Mirrors the routing that ``_show_notification_modal``'s dismiss callback
    performed: the privileged pending-actions pre-read, then the per-action
    ``if/elif`` chain with ``SudoRequest`` ahead of the generic-form custom
    gate branch.

    Args:
        app: The AceApp instance (or a test double exposing the handler
            surface and ``notify``).
        notification: The resolved notification to dispatch (already
            re-read from detail by modal callers).

    Returns:
        True when a handler ran (including the unsupported-action toast),
        False when there was no action to dispatch.
    """
    from sase.notification_gates.failure_notifications import (
        GATE_EXECUTION_FAILED_ACTION,
    )

    from ._notification_actions import (
        REMOTE_ATTENTION_NOTIFICATION_ACTION,
        handle_custom_gate,
        handle_gate_execution_failed,
        handle_hitl,
        handle_jump_to_agent,
        handle_jump_to_patch,
        handle_jump_to_mentor_review,
        handle_launch_approval,
        handle_open_launch_control,
        handle_plan_approval,
        handle_remote_attention_notification,
        handle_sudo_request,
        handle_tmux,
        handle_user_question,
        handle_view_error_report,
        handle_view_report,
    )

    if notification.action in PRIVILEGED_GATE_ACTIONS:
        reader = getattr(app, "_read_notification_pending_actions_from_provider", None)
        if callable(reader):
            reader()

    gate_adapter = adapter_for_action(notification.action)

    if notification.action == "JumpToPatch":
        handle_jump_to_patch(app, notification)
    elif notification.action == "JumpToMentorReview":
        handle_jump_to_mentor_review(app, notification)
    elif notification.action == "JumpToAgent":
        handle_jump_to_agent(app, notification)
    elif notification.action == "Tmux":
        handle_tmux(app, notification)
    elif notification.action == "HITL":
        handle_hitl(app, notification)
    elif notification.action in {"PlanApproval", "EpicApproval"}:
        handle_plan_approval(app, notification)
    elif notification.action == "UserQuestion":
        handle_user_question(app, notification)
    elif notification.action == "LaunchApproval":
        handle_launch_approval(app, notification)
    elif notification.action == REMOTE_ATTENTION_NOTIFICATION_ACTION:
        handle_remote_attention_notification(app, notification)
    elif notification.action == "SudoRequest":
        handle_sudo_request(app, notification)
    elif gate_adapter is not None and gate_adapter.generic_form:
        handle_custom_gate(app, notification)
    elif notification.action == "ViewErrorReport":
        handle_view_error_report(app, notification)
    elif notification.action == GATE_EXECUTION_FAILED_ACTION:
        handle_gate_execution_failed(app, notification)
    elif notification.action == "ViewReport":
        handle_view_report(app, notification)
    elif notification.action == "OpenLaunchControl":
        handle_open_launch_control(app, notification)
    elif notification.action and notification.action.strip():
        app.notify(
            f"Unsupported notification action: {notification.action}",
            severity="warning",
        )
    else:
        return False
    return True


__all__ = ["open_notification_action"]
