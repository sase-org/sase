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

#: Optional epic-approve capacity. Same nonnegative integer domain as
#: ``%queue(capacity=N)`` / ``validate_queue_capacity``.
PLAN_GATE_CAPACITY_SCHEMA: dict[str, object] = {
    "type": "integer",
    "minimum": 0,
    "maximum": 4_294_967_295,
}


def plan_gate_optional_text(value: object) -> str | None:
    """Return *value* stripped, or ``None`` if it is blank or not a string."""
    return value.strip() or None if isinstance(value, str) else None


def plan_gate_optional_capacity(value: object) -> int | None:
    """Return a validated capacity threshold, or ``None`` when omitted.

    JSON ``0`` is an explicit drain threshold. Booleans and other invalid
    numeric input are rejected without coercion.
    """
    if value is None:
        return None
    from sase.xprompt.queue_directive import validate_queue_capacity

    return validate_queue_capacity(value)
