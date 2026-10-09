"""Structured selector resolution shared by plan approve and reject."""

from __future__ import annotations

from sase.main._plan_approve_shared import rendered_error
from sase.main.plan_pending import (
    PendingPlan,
    PendingPlanAmbiguity,
    PendingPlanMiss,
    pending_plans,
    resolve_pending_plan_selector,
)
from sase.main.plan_pending_diagnosis import miss_error_code
from sase.main.plan_pending_render import (
    render_ambiguity,
    render_miss,
)

__all__ = ["resolve_plan_for_cli"]


def resolve_plan_for_cli(selector: str | None) -> PendingPlan:
    """Resolve PLAN through the structured selector, rendering misses."""
    outcome = resolve_pending_plan_selector(selector)
    if isinstance(outcome, PendingPlanAmbiguity):
        render_ambiguity(outcome, pending_plans())
        raise rendered_error(
            "ambiguous_prefix", outcome.selector, "action prefix is ambiguous"
        )
    if isinstance(outcome, PendingPlanMiss):
        render_miss(outcome, pending_plans())
        code = (
            "missing_selector" if outcome.selector is None else miss_error_code(outcome)
        )
        raise rendered_error(code, outcome.selector or "selector", outcome.header)
    return outcome.plan
