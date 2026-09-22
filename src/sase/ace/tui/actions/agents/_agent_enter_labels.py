"""Gate-kind labels for Enter targets and the chooser."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.notification_gates.registry import adapter_for_action

if TYPE_CHECKING:
    from sase.notifications import Notification

#: Gate-kind labels for Enter targets and the chooser. The footer lowercases
#: the label, so entries are stored in display case here.
_GATE_KIND_LABELS: dict[str, str] = {
    "plan": "Review plan",
    "epic_plan": "Review epic plan",
    "question": "Answer question",
    "sudo": "Review sudo request",
    "launch": "Approve agent launch",
    "hitl": "Respond to checkpoint",
    "task_triage": "Triage task",
    "bead_snooze": "Review snoozed bead",
    "flag_triage": "Triage flag",
    "bead_stale_cleanup": "Clean up stale beads",
    "plugins_required": "Install required plugins",
}

#: Notification action to gate kind, for notification-only targets.
_NOTIFICATION_ACTION_KINDS: dict[str, str] = {
    "PlanApproval": "plan",
    "EpicApproval": "epic_plan",
    "UserQuestion": "question",
    "SudoRequest": "sudo",
    "LaunchApproval": "launch",
    "HITL": "hitl",
    "TaskTriage": "task_triage",
    "BeadSnooze": "bead_snooze",
    "FlagTriage": "flag_triage",
    "BeadStaleCleanup": "bead_stale_cleanup",
    "PluginsRequired": "plugins_required",
    "CustomGate": "custom",
}


def gate_target_label(
    *,
    kind: str | None,
    pending_status: str | None = None,
    fallback_label: str | None = None,
) -> str:
    """Return the display label for one gate target.

    Table-driven over the gate kind. A ``plan`` gate whose pending status is
    ``TALE`` reads as a tale-plan review. Custom and unknown kinds fall back
    to the row's ``gate_label``, else ``Open gate``.
    """
    normalized_kind = (kind or "").strip()
    normalized_status = (pending_status or "").strip().upper()
    if normalized_kind == "plan" and normalized_status == "TALE":
        return "Review tale plan"
    label = _GATE_KIND_LABELS.get(normalized_kind)
    if label is not None:
        return label
    cleaned = (fallback_label or "").strip()
    return cleaned if cleaned else "Open gate"


def notification_gate_kind(notification: Notification) -> str | None:
    """Return the gate kind for a gate-action notification, if known."""
    adapter = adapter_for_action(notification.action)
    if adapter is not None:
        return adapter.kind
    if notification.action is not None:
        return _NOTIFICATION_ACTION_KINDS.get(notification.action)
    return None


def notification_pending_status(notification: Notification) -> str | None:
    """Return the pending status carried by a notification, if any."""
    for key in ("pending_status", "gate_start_status", "status"):
        value = notification.action_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def notification_badge_for_action(action: str | None) -> str | None:
    if not action:
        return None
    return {
        "PlanApproval": "PLAN",
        "EpicApproval": "EPIC",
        "UserQuestion": "QUESTION",
        "SudoRequest": "SUDO",
        "LaunchApproval": "LAUNCH",
        "HITL": "HITL",
    }.get(action, "GATE")


__all__ = [
    "gate_target_label",
    "notification_badge_for_action",
    "notification_gate_kind",
    "notification_pending_status",
]
