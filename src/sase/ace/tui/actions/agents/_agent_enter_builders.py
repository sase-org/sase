"""Per-source Enter-target builders."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sase.project_display_names import humanize_cl_name

from ._agent_enter_badges import (
    gate_badge,
    gate_badge_style,
    notification_age_seconds,
    notification_gate_detail,
    row_age_seconds,
)
from ._agent_enter_labels import (
    gate_target_label,
    notification_badge_for_action,
    notification_gate_kind,
    notification_pending_status,
)
from ._agent_enter_models import AgentEnterTarget, PatchSummary, identity_of

if TYPE_CHECKING:
    from ...models import Agent
    from sase.notifications import Notification


def gate_row_target(row: Agent, *, linked: Notification | None) -> AgentEnterTarget:
    age = row_age_seconds(row)
    pending_status = getattr(row, "gate_start_status", None)
    row_notification_id = getattr(row, "gate_notification_id", None)
    row_bundle_path = getattr(row, "gate_bundle_path", None)
    notification_id = row_notification_id or (linked.id if linked is not None else None)
    if row_bundle_path:
        bundle_path: str | None = str(row_bundle_path)
    elif linked is not None:
        linked_bundle = linked.action_data.get("bundle_path")
        bundle_path = str(linked_bundle) if linked_bundle else None
    else:
        bundle_path = None
    return AgentEnterTarget(
        kind="gate",
        source="gate_row",
        key=f"gate:{getattr(row, 'gate_id', None)}",
        label=gate_target_label(
            kind=getattr(row, "gate_kind", None),
            pending_status=pending_status if isinstance(pending_status, str) else None,
            fallback_label=getattr(row, "gate_label", None),
        ),
        detail=notification_gate_detail(linked)
        if linked is not None
        else getattr(row, "gate_reason", None),
        badge=gate_badge(
            pending_status if isinstance(pending_status, str) else None, age
        ),
        badge_style=gate_badge_style(row),
        age_seconds=age,
        notification_id=notification_id,
        bundle_path=bundle_path,
        gate_id=getattr(row, "gate_id", None),
        row_identity=identity_of(row),
    )


def notification_gate_target(
    notification: Notification, *, scope_agent: Agent
) -> AgentEnterTarget:
    kind = notification_gate_kind(notification)
    bundle_path = notification.action_data.get("bundle_path")
    return AgentEnterTarget(
        kind="gate",
        source="notification",
        key=f"gate:{notification.id}",
        label=gate_target_label(
            kind=kind,
            pending_status=notification_pending_status(notification),
            fallback_label=notification.action_data.get("gate_label"),
        ),
        detail=notification_gate_detail(notification),
        badge=gate_badge(
            notification_pending_status(notification)
            or notification_badge_for_action(notification.action),
            notification_age_seconds(notification),
        ),
        badge_style=None,
        age_seconds=notification_age_seconds(notification),
        notification_id=notification.id,
        bundle_path=str(bundle_path) if bundle_path else None,
        gate_id=None,
        row_identity=identity_of(scope_agent),
    )


def question_marker_target(agent: Agent) -> AgentEnterTarget:
    return AgentEnterTarget(
        kind="gate",
        source="question_marker",
        key=f"question-marker:{getattr(agent, 'cl_name', '')}:{getattr(agent, 'raw_suffix', '')}",
        label="Answer question",
        detail=None,
        badge="QUESTION",
        badge_style=None,
        age_seconds=None,
        row_identity=identity_of(agent),
    )


def workflow_hitl_target(agent: Agent) -> AgentEnterTarget:
    step_name = getattr(agent, "step_name", None)
    workflow = getattr(agent, "workflow", None) or getattr(
        agent, "parent_workflow", None
    )
    detail = (
        str(step_name).strip()
        if step_name
        else (str(workflow).strip() if workflow else None)
    )
    return AgentEnterTarget(
        kind="gate",
        source="workflow_hitl",
        key=f"hitl:workflow:{workflow}:{getattr(agent, 'raw_suffix', '')}",
        label="Respond to checkpoint",
        detail=detail,
        badge="HITL",
        badge_style=None,
        age_seconds=None,
        row_identity=identity_of(agent),
    )


def remote_attention_target(agent: Agent) -> AgentEnterTarget:
    attention = getattr(agent, "fleet_attention", None)
    detail: str | None = None
    if isinstance(attention, dict):
        title = attention.get("title")
        if isinstance(title, str) and title.strip():
            detail = title.strip()
    return AgentEnterTarget(
        kind="gate",
        source="remote_attention",
        key=f"remote:{getattr(agent, 'cl_name', '')}:{getattr(agent, 'raw_suffix', '')}",
        label="Answer remote request",
        detail=detail,
        badge=None,
        badge_style=None,
        age_seconds=None,
        row_identity=identity_of(agent),
    )


def patch_target(
    *,
    patch_name: str,
    project_file: str | None,
    summary: PatchSummary | None,
    scope_agent: Agent,
) -> AgentEnterTarget:
    from sase.ace.display_helpers import get_status_color

    status = summary.status if summary is not None else None
    pr_label = summary.pr_label if summary is not None else None
    humanized = humanize_cl_name(patch_name)
    detail = f"{humanized} · {pr_label}" if pr_label else humanized
    style: str | None = None
    if status:
        try:
            style = get_status_color(status)
        except Exception:
            style = None
    return AgentEnterTarget(
        kind="patch",
        source="patch",
        key=f"patch:{patch_name}",
        label="Go to Patch",
        detail=detail,
        badge=status,
        badge_style=style,
        age_seconds=None,
        patch_name=patch_name,
        project_file=project_file,
        row_identity=identity_of(scope_agent),
    )


__all__ = [
    "gate_row_target",
    "notification_gate_target",
    "patch_target",
    "question_marker_target",
    "remote_attention_target",
    "workflow_hitl_target",
]
