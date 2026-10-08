"""Rust binding wrappers for the Plan Decisions feature.

Each wrapper owns one of the seven ``plan_decisions_*`` core bindings.
The public entry point remains ``sase.sdd.plan_decisions``.
"""

from __future__ import annotations

from typing import Any

from sase.sdd._plan_decisions_shared import PlanDecisionError, require_binding


def payload_binding(
    validated_dict: dict[str, Any], host_facts: dict[str, Any]
) -> list[dict[str, Any]]:
    """Freeze a validated plan into the ordered review vector."""
    return list(require_binding("plan_decisions_payload")(validated_dict, host_facts))


def digest_binding(definitions: list[dict[str, Any]]) -> str:
    """Digest frozen definitions for the edit freeze."""
    result = require_binding("plan_decisions_digest")(definitions)
    return str(result)


def resolve_binding(
    definitions: list[dict[str, Any]],
    submitted: dict[str, Any],
    caller: str,
) -> dict[str, Any]:
    """Strictly resolve one accepted answer vector."""
    result = require_binding("plan_decisions_resolve")(definitions, submitted, caller)
    if not isinstance(result, dict):
        raise PlanDecisionError(
            "decision-resolve-failed", "resolver returned no result"
        )
    return dict(result)


def sheet_binding(
    definitions: list[dict[str, Any]],
    values: dict[str, Any],
    review_revision: int = 0,
) -> dict[str, Any]:
    """Build the Decision Sheet wire from frozen definitions and answers."""
    result = require_binding("plan_decision_sheet")(
        definitions, values, int(review_revision)
    )
    if not isinstance(result, dict):
        raise PlanDecisionError(
            "decision-sheet-failed", "sheet builder returned no result"
        )
    return dict(result)


def summary_binding(sheet: dict[str, Any], verdict: str, form: str) -> str:
    """Render the shared summary sentence for a Decision Sheet."""
    return str(require_binding("plan_decision_summary")(sheet, verdict, form))


def prompt_block_binding(
    sheet: dict[str, Any],
    decided_by: str,
    decided_via: str | None,
    audience: str,
    inherited: dict[str, Any] | None = None,
) -> str:
    """Render the host-written implementer block for an accepted sheet."""
    return str(
        require_binding("plan_decisions_prompt_block")(
            sheet, decided_by, decided_via, audience, inherited
        )
    )


__all__ = [
    "digest_binding",
    "payload_binding",
    "prompt_block_binding",
    "resolve_binding",
    "sheet_binding",
    "summary_binding",
]
