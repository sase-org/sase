"""Tier-aware plan gate operations, option ids, and presentation metadata."""

from __future__ import annotations

from pathlib import Path
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


_PLAN_AUTO_VALID_ARGUMENTS = frozenset({None, "", "plan", "tale", "epic", "epic_plan"})
_TALE_COVERED_ARGUMENTS = frozenset({None, "", "plan", "tale"})
_EPIC_COVERED_ARGUMENTS = frozenset({None, "", "epic", "epic_plan"})


def is_valid_plan_auto_argument(argument: str | None) -> bool:
    """Return whether *argument* is a known ``%auto`` plan argument."""
    return argument in _PLAN_AUTO_VALID_ARGUMENTS


def plan_auto_covers_tier(tier: PlanGateTier, argument: str | None) -> bool:
    """Return whether an auto argument covers a plan tier.

    ``:tale``/``:plan`` cover tale plans only and ``:epic``/``:epic_plan``
    cover epic plans only; bare ``%auto`` (``None``/``""``) covers both. Any
    other value is invalid rather than uncovered: use
    :func:`validate_plan_auto_argument` to reject it.
    """
    covered = _EPIC_COVERED_ARGUMENTS if tier == "epic" else _TALE_COVERED_ARGUMENTS
    return argument in covered


def effective_plan_auto_argument(
    action: str | None, argument: str | None
) -> str | None:
    """Return the argument that decides tier coverage for an auto state.

    The live meta stores the raw ``%auto`` argument separately from the
    plan action. When the argument is absent but the action names a tier
    (``tale``/``epic``), the action carries the tier, so it stands in.
    """
    if argument is None and action in {"tale", "epic"}:
        return action
    return argument


def recorded_auto_covers_plan(
    action: str | None, argument: str | None, plan_path: str | Path | None
) -> bool:
    """Return whether recorded auto state covers the plan at *plan_path*.

    *action* is the stored ``auto_approve_plan_action`` and *argument* the
    stored raw ``auto_approve_argument``. An unreadable or missing tier
    counts as covered, so callers keep the established auto-hides-pending
    behavior wherever no cross-tier decision is possible.
    """
    normalized_action = (
        action.strip().lower() if isinstance(action, str) and action.strip() else None
    )
    normalized_argument = (
        argument.strip().lower()
        if isinstance(argument, str) and argument.strip()
        else None
    )
    from sase.sdd.plan_tiers import cached_plan_tier

    tier = cached_plan_tier(plan_path)
    if tier not in {"tale", "epic"}:
        return True
    return plan_auto_covers_tier(
        tier,  # type: ignore[arg-type]
        effective_plan_auto_argument(normalized_action, normalized_argument),
    )


def validate_plan_auto_argument(tier: PlanGateTier, argument: str | None) -> None:
    """Reject unknown plan auto arguments before handoff.

    A known argument from the other tier is valid here but simply does not
    cover this tier: callers treat that as manual via
    :func:`plan_auto_covers_tier` instead of exiting.
    """
    if argument not in _PLAN_AUTO_VALID_ARGUMENTS:
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
