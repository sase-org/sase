"""Shared pending plan-approval resolution for the plan CLI commands.

``sase plan approve`` and ``sase plan reject`` resolve the same pending
PlanApproval notifications (by id, unique prefix, or the lone visible
proposal) and apply the same availability checks, so the selector model
lives here once and both handlers call it. Filtering goes through
``visible_pending_plan_notifications`` so orphaned pending plan
notifications are not acted on by default.
"""

from __future__ import annotations

from pathlib import Path

from sase.main.plan_candidates import visible_pending_plan_notifications
from sase.notifications.models import Notification
from sase.notifications.pending_actions import action_state_for_notification
from sase.notifications.store import load_notifications
from sase.plan_approval_actions import (
    PLAN_APPROVAL_ACTIONS,
    PlanApprovalActionContext,
    PlanApprovalActionError,
)


def resolve_pending_plan(selector: str | None) -> Notification:
    """Resolve the pending PlanApproval notification a selector refers to.

    With no selector, exactly one visible pending proposal must exist. With
    a selector, it must uniquely match a pending proposal by id or prefix.
    """
    return (
        _resolve_single_pending_plan()
        if selector is None
        else _resolve_plan_selector(selector)
    )


def _resolve_single_pending_plan() -> Notification:
    """Return the sole visible pending plan, or raise when not exactly one."""
    pending = _available_plan_notifications()
    if not pending:
        raise PlanApprovalActionError(
            "missing_selector",
            "selector",
            "no pending plan proposals; pass a selector after running `sase plan list`",
        )
    if len(pending) > 1:
        raise PlanApprovalActionError(
            "missing_selector",
            "selector",
            "multiple pending plan proposals; pass an ID prefix from `sase plan list`",
        )
    return pending[0]


def _resolve_plan_selector(selector: str) -> Notification:
    """Resolve a notification id or unique prefix to a pending plan."""
    matches = _matching_selector_notifications(
        selector,
        _available_plan_notifications(),
    )
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise PlanApprovalActionError(
            "ambiguous_prefix", selector, "action prefix is ambiguous"
        )

    unavailable_matches = [
        notification
        for notification in _matching_selector_notifications(
            selector,
            [
                notification
                for notification in load_notifications(include_dismissed=False)
                if notification.action in PLAN_APPROVAL_ACTIONS
            ],
        )
        if action_state_for_notification(notification) != "available"
    ]
    if len(unavailable_matches) == 1:
        return unavailable_matches[0]
    if len(unavailable_matches) > 1:
        raise PlanApprovalActionError(
            "ambiguous_prefix", selector, "action prefix is ambiguous"
        )

    raise PlanApprovalActionError(
        "not_found", selector, "pending plan approval not found"
    )


def _matching_selector_notifications(
    selector: str, notifications: list[Notification]
) -> list[Notification]:
    return [
        notification
        for notification in notifications
        if notification.id == selector or notification.id.startswith(selector)
    ]


def _available_plan_notifications() -> list[Notification]:
    """Return pending plan approvals backed by a live Agents-tab row."""
    return visible_pending_plan_notifications()


def ensure_plan_notification_available(notification: Notification) -> None:
    """Raise when *notification* is not an available plan approval action."""
    if notification.action not in PLAN_APPROVAL_ACTIONS:
        raise PlanApprovalActionError(
            "unsupported_action",
            notification.action or "non_action",
            "notification is not a plan approval",
        )

    state = action_state_for_notification(notification)
    if state == "available":
        return
    if state == "already_handled":
        raise PlanApprovalActionError(
            "conflict_already_handled", notification.id, "action already handled"
        )
    if state == "stale":
        raise PlanApprovalActionError("gone_stale", notification.id, "action is stale")
    raise PlanApprovalActionError(
        "invalid_request", notification.id, f"action is {state}"
    )


def plan_context_from_notification(
    notification: Notification,
) -> PlanApprovalActionContext:
    """Build the host-side action context for a resolved notification."""
    return PlanApprovalActionContext(
        id=notification.id,
        host_files=tuple(str(Path(path).expanduser()) for path in notification.files),
        host_action_data=dict(notification.action_data),
    )
