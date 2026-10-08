"""Single Python entry point for Plan Decisions.

Telegram and every other surface import this module, not ``sase_core_rs``,
for decisions. It wraps the seven core bindings and owns the two host
steps: memory-scope resolution and quote verification.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sase.notification_gates.models import GateError

OVERLAP_CODE = "decision-memory-overlap"
UNVERIFIED_CODE = "decision-requested-unverified"

DECISION_SCHEMA_PREFIX = "decision_"

SEVEN_BINDINGS = (
    "plan_decisions_payload",
    "plan_decisions_digest",
    "plan_decisions_resolve",
    "plan_decision_quote_match",
    "plan_decision_sheet",
    "plan_decision_summary",
    "plan_decisions_prompt_block",
)


class _PlanDecisionError(ValueError):
    """Host-side decision failure with a stable diagnostic code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def in_agent_context() -> bool:
    """Return whether this process runs inside an agent."""
    return bool(os.environ.get("SASE_AGENT") or os.environ.get("SASE_ARTIFACTS_DIR"))


def artifacts_dir_from_env() -> str:
    """Return the planner artifacts dir for quote checks."""
    return str(os.environ.get("SASE_ARTIFACTS_DIR") or "")


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


def _binding(name: str) -> Any:
    from sase.core.rust import require_rust_binding

    return require_rust_binding(name)


def payload_binding(
    validated_dict: dict[str, Any], host_facts: dict[str, Any]
) -> list[dict[str, Any]]:
    """Freeze a validated plan into the ordered review vector."""
    return list(_binding("plan_decisions_payload")(validated_dict, host_facts))


def digest_binding(definitions: list[dict[str, Any]]) -> str:
    """Digest frozen definitions for the edit freeze."""
    result = _binding("plan_decisions_digest")(definitions)
    return str(result)


def resolve_binding(
    definitions: list[dict[str, Any]],
    submitted: dict[str, Any],
    caller: str,
) -> dict[str, Any]:
    """Strictly resolve one accepted answer vector."""
    result = _binding("plan_decisions_resolve")(definitions, submitted, caller)
    if not isinstance(result, dict):
        raise _PlanDecisionError(
            "decision-resolve-failed", "resolver returned no result"
        )
    return dict(result)


def _quote_match_binding(quote: str, texts: list[dict[str, str]]) -> dict[str, Any]:
    """Verify a human quote against ordered human-authored texts."""
    result = _binding("plan_decision_quote_match")(quote, texts)
    return dict(result) if isinstance(result, dict) else {"verified": False}


def sheet_binding(
    definitions: list[dict[str, Any]],
    values: dict[str, Any],
    review_revision: int = 0,
) -> dict[str, Any]:
    """Build the Decision Sheet wire from frozen definitions and answers."""
    result = _binding("plan_decision_sheet")(definitions, values, int(review_revision))
    if not isinstance(result, dict):
        raise _PlanDecisionError(
            "decision-sheet-failed", "sheet builder returned no result"
        )
    return dict(result)


def summary_binding(sheet: dict[str, Any], verdict: str, form: str) -> str:
    """Render the shared summary sentence for a Decision Sheet."""
    return str(_binding("plan_decision_summary")(sheet, verdict, form))


def prompt_block_binding(
    sheet: dict[str, Any],
    decided_by: str,
    decided_via: str | None,
    audience: str,
    inherited: dict[str, Any] | None = None,
) -> str:
    """Render the host-written implementer block for an accepted sheet."""
    return str(
        _binding("plan_decisions_prompt_block")(
            sheet, decided_by, decided_via, audience, inherited
        )
    )


def _resolve_memory_records(
    selectors: list[str],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Resolve one decision's selectors to memory records and note keys.

    Raises :class:`_PlanDecisionError` when a selector cannot be resolved.
    """
    from sase.memory.selector import resolve_memory_selector_batch
    from sase.memory.selector_models import MemorySelectorError

    records: list[dict[str, Any]] = []
    note_keys: set[str] = set()
    for selector in selectors:
        try:
            batch = resolve_memory_selector_batch([selector])
        except MemorySelectorError as exc:
            raise _PlanDecisionError("decision-memory-unresolvable", str(exc)) from exc
        except Exception as exc:
            raise _PlanDecisionError("decision-memory-unresolvable", str(exc)) from exc
        for note in batch.notes:
            try:
                canonical = note.content.path.canonical_path
                note_type = str(note.content.path.note.type or "reference")
                scope = str(note.origin)
            except Exception:
                continue
            kind = "note"
            path = str(canonical)
            note_keys.add(f"{kind}:{scope}:{path}")
            records.append(
                {
                    "selector": selector,
                    "kind": kind,
                    "scope": scope,
                    "path": path,
                    "type": note_type
                    if note_type in ("core", "reference", "web", "strand")
                    else "reference",
                    "exists": True,
                }
            )
        for section in batch.web_sections:
            try:
                web = section.web
                frozen = [node.strand.keyword for node in section.nodes]
                scope = str(section.nodes[0].scope) if section.nodes else "project"
            except Exception:
                continue
            path = str(getattr(web, "relative_path", web.slug))
            note_keys.add(f"web:{scope}:{path}")
            record: dict[str, Any] = {
                "selector": selector,
                "kind": "web",
                "scope": scope,
                "path": path,
                "type": "web",
                "exists": True,
                "strands": list(frozen),
            }
            records.append(record)
            for node in section.nodes:
                try:
                    strand_path = str(node.strand.relative_path)
                    strand_scope = str(node.scope)
                except Exception:
                    continue
                note_keys.add(f"strand:{strand_scope}:{strand_path}")
    if not records and not note_keys:
        raise _PlanDecisionError(
            "decision-memory-unresolvable",
            f"memory selector did not resolve: {selectors!r}",
        )
    return records, note_keys


def _build_host_facts(
    validation: Any,
    artifacts_dir: str = "",
) -> dict[str, dict[str, Any]]:
    """Build ``{id: {requested_verified, provenance, resolved}}`` for a plan.

    Fails closed: unknown provenance, a missing quote source, or an
    unresolvable context counts as not requested. Never emits ``inherited``.
    """
    plan = getattr(validation, "plan", None)
    if plan is None:
        return {}
    directory = artifacts_dir or artifacts_dir_from_env()
    human_texts: list[dict[str, str]] = []
    if directory:
        try:
            from sase.sdd.plan_human_text import human_authored_texts

            for item in human_authored_texts(directory):
                human_texts.append(
                    {"source": item.source, "ref": item.ref, "text": item.text}
                )
        except Exception:
            human_texts = []
    facts: dict[str, dict[str, Any]] = {}
    for decision in getattr(plan, "decisions", ()):
        selectors = getattr(decision, "memory", None)
        if selectors is None:
            continue
        try:
            records, _keys = _resolve_memory_records(list(selectors))
        except _PlanDecisionError:
            raise
        default = getattr(decision, "default", None)
        requested = getattr(decision, "requested", None)
        if not isinstance(requested, str) or not requested.strip():
            facts[decision.id] = {
                "requested_verified": False,
                "provenance": "not_asked",
                "resolved": records,
            }
            continue
        if default is False:
            facts[decision.id] = {
                "requested_verified": False,
                "provenance": "not_asked",
                "resolved": records,
            }
            continue
        if not human_texts:
            facts[decision.id] = {
                "requested_verified": False,
                "provenance": "quote_not_found",
                "resolved": records,
            }
            continue
        try:
            match = _quote_match_binding(requested, human_texts)
        except Exception:
            match = {"verified": False}
        verified = bool(match.get("verified"))
        facts[decision.id] = {
            "requested_verified": verified,
            "provenance": "asked" if verified else "quote_not_found",
            "resolved": records,
        }
    return facts


def _host_facts_for_gate_build(
    validation: Any,
    artifacts_dir: str = "",
) -> dict[str, dict[str, Any]]:
    """Build fresh host facts for gate creation, failing closed, never raising.

    An unverified quote forces provenance ``quote_not_found`` and does not
    block gate creation. An unresolvable selector is the caller's GateError.
    """
    try:
        return _build_host_facts(validation, artifacts_dir)
    except _PlanDecisionError:
        raise
    except Exception:
        return {}


def build_definitions(
    validation: Any,
    artifacts_dir: str = "",
) -> list[dict[str, Any]]:
    """Freeze the validated plan's decisions with fresh host facts."""
    plan = getattr(validation, "plan", None)
    if plan is None:
        return []
    if not getattr(plan, "decisions", ()):
        return []
    facts = _host_facts_for_gate_build(validation, artifacts_dir)
    wired = validated_to_wire_dict(plan)
    try:
        return payload_binding(wired, facts)
    except _PlanDecisionError:
        raise
    except Exception as exc:
        raise GateError(
            "decision-payload-failed", "payload.decisions", str(exc)
        ) from exc


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


def _check_memory_overlap(validation: Any) -> None:
    """Raise ``decision-memory-overlap`` when two decisions share a note."""
    plan = getattr(validation, "plan", None)
    if plan is None:
        return
    seen: dict[str, str] = {}
    for decision in getattr(plan, "decisions", ()):
        selectors = getattr(decision, "memory", None)
        if selectors is None:
            continue
        try:
            _records, keys = _resolve_memory_records(list(selectors))
        except _PlanDecisionError:
            raise
        for key in keys:
            if key in seen:
                raise _PlanDecisionError(
                    OVERLAP_CODE,
                    f"decisions {seen[key]!r} and {decision.id!r} resolve to the same note",
                )
            seen[key] = decision.id


def _closest_sentence_for(
    requested: str,
    artifacts_dir: str = "",
) -> str | None:
    """Return the matcher's closest human sentence for a quote."""
    directory = artifacts_dir or artifacts_dir_from_env()
    if not directory or not requested.strip():
        return None
    try:
        from sase.sdd.plan_human_text import human_authored_texts

        texts = [
            {"source": item.source, "ref": item.ref, "text": item.text}
            for item in human_authored_texts(directory)
        ]
    except Exception:
        return None
    if not texts:
        return None
    try:
        match = _quote_match_binding(requested, texts)
    except Exception:
        return None
    closest = match.get("closest")
    if isinstance(closest, dict):
        sentence = closest.get("sentence") or closest.get("text")
        if isinstance(sentence, str) and sentence.strip():
            return sentence.strip()
    return None


def validate_host_checks(
    content: str,
    validation: Any,
    artifacts_dir: str = "",
    *,
    strict_quotes: bool,
) -> list[Any]:
    """Run selector, overlap, and quote checks for validate/propose.

    Returns extra diagnostics to append. Raises nothing; overlap and
    unresolvable selectors become diagnostics here.
    """
    from sase.sdd.plan_validate import PlanDiagnostic, PlanDiagnosticSeverity

    plan = getattr(validation, "plan", None)
    if plan is None or not getattr(plan, "decisions", ()):
        return []
    extra: list[Any] = []
    try:
        _check_memory_overlap(validation)
    except _PlanDecisionError as exc:
        extra.append(
            PlanDiagnostic(
                severity=PlanDiagnosticSeverity.ERROR,
                code=str(exc.code),
                field_path="decisions",
                message=str(exc.message),
                line=None,
            )
        )
        return extra
    if not strict_quotes:
        return extra
    try:
        facts = _build_host_facts(validation, artifacts_dir)
    except _PlanDecisionError as exc:
        extra.append(
            PlanDiagnostic(
                severity=PlanDiagnosticSeverity.ERROR,
                code=str(exc.code),
                field_path="decisions",
                message=str(exc.message),
                line=None,
            )
        )
        return extra
    for decision in getattr(plan, "decisions", ()):
        if getattr(decision, "memory", None) is None:
            continue
        if getattr(decision, "default", None) is not True:
            continue
        fact = facts.get(decision.id, {})
        if fact.get("requested_verified"):
            continue
        closest = _closest_sentence_for(
            str(getattr(decision, "requested", "") or ""), artifacts_dir
        )
        message = f"memory decision {decision.id!r} quote was not found in human text"
        if closest:
            message += f'; closest: "{closest}"'
        extra.append(
            PlanDiagnostic(
                severity=PlanDiagnosticSeverity.ERROR,
                code=UNVERIFIED_CODE,
                field_path=f"decisions.{decision.id}.requested",
                message=message,
                line=None,
            )
        )
    return extra


def resolve_plan_decisions_for_direct_approval(
    validation: Any,
    overrides: dict[str, Any],
    caller: str,
    artifacts_dir: str = "",
) -> dict[str, Any]:
    """Resolve effective defaults for a no-live-gate approval route."""
    plan = getattr(validation, "plan", None)
    if plan is None or not getattr(plan, "decisions", ()):
        return {"values": {}, "rows": [], "errors": []}
    definitions = build_definitions(validation, artifacts_dir)
    submitted = dict(overrides or {})
    try:
        return resolve_binding(definitions, submitted, caller)
    except Exception as exc:
        raise GateError("decision-resolve-failed", "decisions", str(exc)) from exc


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
    "DECISION_SCHEMA_PREFIX",
    "OVERLAP_CODE",
    "SEVEN_BINDINGS",
    "UNVERIFIED_CODE",
    "build_definitions",
    "compile_input_properties",
    "count_memory",
    "digest_binding",
    "in_agent_context",
    "artifacts_dir_from_env",
    "payload_binding",
    "prompt_block_binding",
    "resolve_binding",
    "resolve_plan_decisions_for_direct_approval",
    "sheet_binding",
    "summary_binding",
    "validate_host_checks",
    "validated_to_wire_dict",
]
