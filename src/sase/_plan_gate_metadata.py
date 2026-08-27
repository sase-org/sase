"""Tier-aware plan gate operations, option ids, and presentation metadata."""

from __future__ import annotations

from typing import Any

from sase.notification_gates.models import GateError

from ._plan_gate_shared import (
    PLAN_APPROVE_OPTION_ID,
    PLAN_COMMIT_OPTION_ID,
    PLAN_EDIT_OPERATION_ID,
    PLAN_FEEDBACK_OPTION_ID,
    PLAN_REJECT_OPTION_ID,
    PLAN_RESOURCE_PATH,
    PlanGateTier,
)


def plan_gate_edit_operation(tier: PlanGateTier) -> dict[str, Any]:
    """Return the declared edit action registered for a plan tier.

    Both tiers declare it, and both point at ``edit_target: "origin"``: the
    durable file under ``~/.sase/plans/`` that ``sase plan propose`` wrote, not
    the bundle copy that approval overwrites it from.
    """
    return {
        "id": PLAN_EDIT_OPERATION_ID,
        "kind": "edit_file",
        "target": PLAN_RESOURCE_PATH,
        "edit_target": "origin",
        "label": "Edit epic plan" if tier == "epic" else "Edit plan",
        "icon": "✏️",
        "key": "e",
        "description": "Accepted only when `sase plan validate` passes.",
    }


def plan_gate_query(tier: PlanGateTier) -> str:
    """Return the exact option query registered for a plan tier."""
    if tier == "epic":
        return "approve OR reject OR feedback"
    return "(approve AND commit) OR reject OR feedback"


def plan_gate_option_ids(tier: PlanGateTier) -> tuple[str, ...]:
    """Return the query-ordered option ids registered for a plan tier."""
    if tier == "epic":
        return (
            PLAN_APPROVE_OPTION_ID,
            PLAN_REJECT_OPTION_ID,
            PLAN_FEEDBACK_OPTION_ID,
        )
    return (
        PLAN_APPROVE_OPTION_ID,
        PLAN_COMMIT_OPTION_ID,
        PLAN_REJECT_OPTION_ID,
        PLAN_FEEDBACK_OPTION_ID,
    )


def validate_plan_auto_argument(tier: PlanGateTier, argument: str | None) -> None:
    """Reject unknown or tier-changing plan auto aliases before handoff."""
    allowed = (
        {None, "", "epic", "epic_plan"}
        if tier == "epic"
        else {None, "", "plan", "tale"}
    )
    if argument not in allowed:
        raise GateError(
            "invalid_auto_argument",
            "auto.argument",
            f"%auto:{argument} conflicts with the authored {tier} plan tier",
        )


def plan_gate_option_label(option_id: str, *, tier: PlanGateTier) -> str:
    """Return the tier-aware presentation label for a plan-gate option."""
    if option_id == PLAN_APPROVE_OPTION_ID:
        return "Epic" if tier == "epic" else "Launch coder agent"
    return {
        PLAN_COMMIT_OPTION_ID: "Commit plan file to the plans sidecar",
        PLAN_REJECT_OPTION_ID: "Reject",
        PLAN_FEEDBACK_OPTION_ID: "Send Feedback",
    }[option_id]


def plan_gate_option_icon(option_id: str, *, tier: PlanGateTier) -> str:
    """Return the tier-aware presentation icon for a plan-gate option."""
    if option_id == PLAN_APPROVE_OPTION_ID:
        return "✅" if tier == "epic" else "🚀"
    return {
        PLAN_COMMIT_OPTION_ID: "💾",
        PLAN_REJECT_OPTION_ID: "❌",
        PLAN_FEEDBACK_OPTION_ID: "💬",
    }[option_id]
