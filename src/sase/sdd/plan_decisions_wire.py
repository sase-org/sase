"""Wire-dict helpers for the Plan Decisions feature.

Pure converters between validated plans, definition vectors, and input
schemas. The public entry point remains ``sase.sdd.plan_decisions``.
"""

from __future__ import annotations

from typing import Any

from sase.sdd._plan_decisions_shared import DECISION_SCHEMA_PREFIX


def validated_to_wire_dict(validation_plan: Any) -> dict[str, Any]:
    """Convert a rehydrated ``_ValidatedPlan`` to the Rust wire dict."""
    phases = [
        {
            "id": phase.id,
            "title": phase.title,
            "depends_on": list(phase.depends_on),
            "description": phase.description,
            "size": phase.size,
            "model": phase.model,
        }
        for phase in getattr(validation_plan, "phases", ())
    ]
    decisions = []
    for decision in getattr(validation_plan, "decisions", ()):
        memory = getattr(decision, "memory", None)
        decisions.append(
            {
                "id": decision.id,
                "kind": decision.kind,
                "ask": decision.ask,
                **({"why": decision.why} if decision.why is not None else {}),
                "choices": [
                    {"key": choice.key, "label": choice.label}
                    for choice in getattr(decision, "choices", ())
                ],
                "default": decision.default,
                **(
                    {"memory": {"selectors": list(memory)}}
                    if memory is not None
                    else {}
                ),
                **(
                    {"requested": decision.requested}
                    if decision.requested is not None
                    else {}
                ),
                **(
                    {"answer": decision.answer}
                    if getattr(decision, "answer", None) is not None
                    else {}
                ),
            }
        )
    callouts = [
        {
            "id": callout.id,
            **({"key": callout.key} if callout.key is not None else {}),
            "branch": callout.branch,
            "start_line": callout.start_line,
            "end_line": callout.end_line,
        }
        for callout in getattr(validation_plan, "decision_callouts", ())
    ]
    payload: dict[str, Any] = {
        "tier": getattr(validation_plan, "tier", "tale"),
        "goal": getattr(validation_plan, "goal", ""),
        "size": getattr(validation_plan, "size", None),
        "model": getattr(validation_plan, "model", None),
        "title": getattr(validation_plan, "title", ""),
        "phases": phases,
        "patch": getattr(validation_plan, "patch", None),
        "bug_id": getattr(validation_plan, "bug_id", None),
        "parent_bead": getattr(validation_plan, "parent_bead", None),
        "bead": getattr(validation_plan, "bead", None),
        "proposed_by": getattr(validation_plan, "proposed_by", None),
        "parent": getattr(validation_plan, "parent", None),
    }
    if decisions:
        payload["decisions"] = decisions
    if callouts:
        payload["decision_callouts"] = callouts
    decided_by = getattr(validation_plan, "decided_by", None)
    decided_via = getattr(validation_plan, "decided_via", None)
    if decided_by is not None:
        payload["decided_by"] = decided_by
    if decided_via is not None:
        payload["decided_via"] = decided_via
    return payload


def compile_input_properties(
    definitions: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Compile ``decision_<id>`` raw input properties in author order."""
    properties: dict[str, dict[str, Any]] = {}
    for definition in definitions:
        decision_id = str(definition.get("id", ""))
        kind = str(definition.get("kind", ""))
        if not decision_id:
            continue
        if kind == "choice":
            keys: list[str] = []
            for choice in definition.get("choices", []) or []:
                if isinstance(choice, dict) and "key" in choice:
                    keys.append(str(choice["key"]))
            properties[f"{DECISION_SCHEMA_PREFIX}{decision_id}"] = {"enum": keys}
        else:
            properties[f"{DECISION_SCHEMA_PREFIX}{decision_id}"] = {"type": "boolean"}
    return properties


def count_memory(decisions: Any) -> int:
    """Count memory decisions in a validated plan or definition vector."""
    total = 0
    for decision in decisions or ():
        if isinstance(decision, dict):
            if decision.get("memory") is not None:
                total += 1
        elif getattr(decision, "memory", None) is not None:
            total += 1
    return total


__all__ = [
    "compile_input_properties",
    "count_memory",
    "validated_to_wire_dict",
]
