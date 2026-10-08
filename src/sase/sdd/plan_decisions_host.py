"""Host steps for the Plan Decisions feature.

Owns the two host steps — memory-scope resolution and quote verification —
plus definition freezing, host checks, and direct (gateless) resolution.
The public entry point remains ``sase.sdd.plan_decisions``.
"""

from __future__ import annotations

from typing import Any

from sase.notification_gates.models import GateError
from sase.sdd._plan_decisions_shared import (
    OVERLAP_CODE,
    UNVERIFIED_CODE,
    PlanDecisionError,
    artifacts_dir_from_env,
    require_binding,
    resolve_memory_records,
)
from sase.sdd.plan_decisions_bindings import payload_binding, resolve_binding
from sase.sdd.plan_decisions_wire import validated_to_wire_dict


def _quote_match_binding(quote: str, texts: list[dict[str, str]]) -> dict[str, Any]:
    """Verify a human quote against ordered human-authored texts."""
    result = require_binding("plan_decision_quote_match")(quote, texts)
    return dict(result) if isinstance(result, dict) else {"verified": False}


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
            records, _keys = resolve_memory_records(list(selectors))
        except PlanDecisionError:
            raise
        requested = getattr(decision, "requested", None)
        if not isinstance(requested, str) or not requested.strip():
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
    except PlanDecisionError:
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
    except PlanDecisionError:
        raise
    except Exception as exc:
        raise GateError(
            "decision-payload-failed", "payload.decisions", str(exc)
        ) from exc


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
            _records, keys = resolve_memory_records(list(selectors))
        except PlanDecisionError:
            raise
        for key in keys:
            if key in seen:
                raise PlanDecisionError(
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
    except PlanDecisionError as exc:
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
    except PlanDecisionError as exc:
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


def resolve_direct_with_definitions(
    definitions: list[dict[str, Any]],
    overrides: dict[str, Any],
    caller: str,
) -> dict[str, Any]:
    """Resolve typed overrides against prebuilt frozen definitions."""
    submitted = dict(overrides or {})
    try:
        return resolve_binding(definitions, submitted, caller)
    except Exception as exc:
        raise GateError("decision-resolve-failed", "decisions", str(exc)) from exc


def resolve_plan_decisions_for_direct_approval(
    validation: Any,
    overrides: dict[str, Any],
    caller: str,
    artifacts_dir: str = "",
    definitions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve effective defaults for a no-live-gate approval route.

    The single direct-resolution implementation for gateless
    ``sase plan approve <file>``, its ``-D`` overrides, and gateless
    ``sase bead work``. Callers with an already-built definition vector
    may pass it as ``definitions`` to avoid rebuilding host facts; the
    same vector is carried in the result.
    """
    plan = getattr(validation, "plan", None)
    if plan is None or not getattr(plan, "decisions", ()):
        return {"values": {}, "rows": [], "errors": []}
    if definitions is None:
        directory = artifacts_dir or artifacts_dir_from_env()
        definitions = build_definitions(validation, directory)
    resolved = resolve_direct_with_definitions(
        list(definitions), dict(overrides or {}), caller
    )
    if isinstance(resolved, dict) and "definitions" not in resolved:
        resolved = {**resolved, "definitions": list(definitions)}
    return resolved


__all__ = [
    "build_definitions",
    "resolve_direct_with_definitions",
    "resolve_plan_decisions_for_direct_approval",
    "validate_host_checks",
]
