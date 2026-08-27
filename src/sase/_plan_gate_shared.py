"""Constants, the tier type, and small helpers shared by the plan gate modules."""

from __future__ import annotations

from typing import Literal

from sase.notification_gates.models import GateGroup

PLAN_EDIT_OPERATION_ID = "edit_plan"
PLAN_RESOURCE_PATH = "plan.md"
PLAN_CONTINUATION_MODE = "agent_plan"
PLAN_APPROVE_OPTION_ID = "approve"
PLAN_COMMIT_OPTION_ID = "commit"
PLAN_REJECT_OPTION_ID = "reject"
PLAN_FEEDBACK_OPTION_ID = "feedback"

TALE_PLAN_SUBMIT_GROUP = GateGroup(
    options=(PLAN_APPROVE_OPTION_ID, PLAN_COMMIT_OPTION_ID),
    label="Tale",
    icon="✅",
)

PlanGateTier = Literal["tale", "epic"]


def plan_gate_optional_text(value: object) -> str | None:
    """Return *value* stripped, or ``None`` if it is blank or not a string."""
    return value.strip() or None if isinstance(value, str) else None
