"""Normalization of Plan Decision inputs before gate acceptance."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.notification_gates.models import GateError


_SUPPORTED_PLAN_SOURCES = frozenset(
    {"tui", "cli", "telegram", "mobile", "auto_resolution", "plan_response"}
)


def _validate_plan_source_caller(source: str, caller: str) -> str:
    """Validate stamp coordinates at the normalization boundary.

    Supported surfaces are ``tui``, ``cli``, ``telegram``, and ``mobile``;
    ``auto_resolution`` maps to ``decided_by: auto`` with no ``decided_via``.
    A classified human maps to ``reviewer``; an agent maps to ``agent``.
    An unknown source or invalid caller fails before acceptance. Decision-free
    gates retain their existing contracts (validated by the early return above).
    The legacy ``plan_response`` alias retains its established TUI meaning.
    """
    if source not in _SUPPORTED_PLAN_SOURCES:
        raise GateError(
            "unknown_source",
            "source",
            f"unsupported plan gate source: {source!r}",
        )
    if source == "auto_resolution":
        return "auto"
    if caller not in ("human", "agent"):
        raise GateError(
            "invalid_caller",
            "caller",
            f"invalid plan gate caller: {caller!r}",
        )
    return caller


def normalize_plan_option_inputs(
    envelope: Mapping[str, Any],
    selected_option_ids: Sequence[str],
    option_inputs: Mapping[str, object] | None,
    *,
    source: str,
    caller: str,
) -> Mapping[str, object] | None:
    """Resolve Plan Decisions once for both receipt and execution paths."""
    payload = envelope.get("payload")
    definitions = payload.get("decisions") if isinstance(payload, dict) else None
    if not definitions:
        return option_inputs
    if not isinstance(definitions, list):
        return option_inputs
    validated_caller = _validate_plan_source_caller(source, caller)
    try:
        from sase.sdd.plan_decisions import resolve_binding
    except Exception as exc:
        raise GateError("decision-resolve-failed", "decisions", str(exc)) from exc
    raw_options = envelope.get("options")
    declaring: dict[str, set[str]] = {}
    if isinstance(raw_options, list):
        for raw in raw_options:
            if not isinstance(raw, dict):
                continue
            option_id = raw.get("id")
            if not isinstance(option_id, str) or option_id not in selected_option_ids:
                continue
            schema = raw.get("input_schema")
            props = schema.get("properties") if isinstance(schema, dict) else None
            if not isinstance(props, dict):
                continue
            declaring[option_id] = {
                str(name) for name in props if str(name).startswith("decision_")
            }
    if not any(declaring.values()):
        return option_inputs
    inputs: dict[str, dict[str, Any]] = {}
    for option_id in selected_option_ids:
        raw = None
        if isinstance(option_inputs, Mapping):
            raw = option_inputs.get(option_id, {})
        if isinstance(raw, dict):
            inputs[option_id] = dict(raw)
        else:
            inputs[option_id] = {}
    collected: dict[str, Any] = {}
    owners: dict[str, str] = {}
    for option_id in selected_option_ids:
        if option_id not in declaring:
            continue
        for key, value in inputs[option_id].items():
            if not str(key).startswith("decision_"):
                continue
            decision_id = str(key).removeprefix("decision_")
            if decision_id in collected:
                if collected[decision_id] != value:
                    raise GateError(
                        "decision_conflict",
                        f"decisions.{decision_id}",
                        f"decisions {decision_id!r} disagree across selected options",
                    )
            else:
                collected[decision_id] = value
                owners[decision_id] = option_id
    effective_caller = validated_caller
    try:
        result = resolve_binding(list(definitions), dict(collected), effective_caller)
    except GateError:
        raise
    except Exception as exc:
        raise GateError("decision-resolve-failed", "decisions", str(exc)) from exc
    errors = result.get("errors") or []
    if errors:
        first = errors[0] if isinstance(errors[0], dict) else {}
        code = str(first.get("code") or "decision-resolve-failed")
        message = str(first.get("message") or "plan decisions failed to resolve")
        target = f"decisions.{first.get('id', '')}" if first.get("id") else "decisions"
        raise GateError(code, target, message)
    values = result.get("values") or {}
    if not isinstance(values, dict):
        values = {}
    normalized: dict[str, object] = (
        dict(option_inputs) if isinstance(option_inputs, Mapping) else {}
    )
    for option_id in selected_option_ids:
        if option_id not in declaring or not declaring[option_id]:
            continue
        merged = dict(inputs[option_id])
        for decision_id, value in values.items():
            key = f"decision_{decision_id}"
            if key in declaring[option_id]:
                merged[key] = value
        normalized[option_id] = merged
    return normalized


def _feedback_rows_for_bundle(
    bundle_path: object,
    response: Mapping[str, Any] | None = None,
) -> list[dict[str, object]]:
    """Load envelope and response from a bundle and build feedback rows."""
    try:
        from pathlib import Path as _Path

        from sase.notification_gates.durability import read_json_object as _read

        bundle = _Path(str(bundle_path))
        envelope = _read(bundle / "request.json")
        resp = (
            dict(response)
            if isinstance(response, Mapping)
            else _read(bundle / "response.json")
        )
        return _feedback_decision_rows(envelope, resp)
    except Exception:
        return []


def feedback_rows_for_artifacts(
    artifacts_dir: str,
    response: Mapping[str, Any] | None = None,
) -> list[dict[str, object]]:
    """Build feedback rows via the artifacts dir's gate bundle pointer."""
    try:
        import json as _json
        from pathlib import Path as _Path

        meta_path = _Path(artifacts_dir) / "agent_meta.json"
        meta = _json.loads(meta_path.read_text(encoding="utf-8"))
        bundle_path = meta.get("gate_bundle_path") if isinstance(meta, dict) else None
        if not isinstance(bundle_path, str) or not bundle_path:
            return []
        return _feedback_rows_for_bundle(bundle_path, response)
    except Exception:
        return []


def _feedback_decision_rows(
    envelope: Mapping[str, Any],
    response: Mapping[str, Any],
) -> list[dict[str, object]]:
    """Build provisional decision rows from the feedback option's inputs."""
    payload = envelope.get("payload")
    definitions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(definitions, list) or not definitions:
        return []
    option_inputs = response.get("option_inputs")
    feedback_input: Mapping[str, Any] = {}
    if isinstance(option_inputs, dict):
        raw = option_inputs.get("feedback", {})
        if isinstance(raw, dict):
            feedback_input = raw
    rows: list[dict[str, object]] = []
    for definition in definitions:
        if not isinstance(definition, dict):
            continue
        decision_id = str(definition.get("id", ""))
        if not decision_id:
            continue
        effective_default = definition.get("effective_default")
        key = f"decision_{decision_id}"
        value = feedback_input.get(key, effective_default)
        changed = value != effective_default
        rows.append(
            {
                "id": decision_id,
                "value": value,
                "default": effective_default,
                "memory": definition.get("memory") is not None,
                "changed": bool(changed),
            }
        )
    return rows


def _accepted_values_from_response(
    response: Mapping[str, Any],
) -> dict[str, Any]:
    """Extract the accepted answer vector from a published gate response.

    Reads ``decision_*`` inputs across selected options (and the command
    results' ``decisions`` object when present) without re-running the
    resolver, quote verification, or caller discovery. Changed submitted
    overrides cannot replace an accepted vector: conflicting values raise.
    """
    values: dict[str, Any] = {}
    option_inputs = response.get("option_inputs")
    if isinstance(option_inputs, dict):
        for inputs in option_inputs.values():
            if not isinstance(inputs, dict):
                continue
            for key, value in inputs.items():
                if not str(key).startswith("decision_"):
                    continue
                decision_id = str(key).removeprefix("decision_")
                if decision_id in values and values[decision_id] != value:
                    raise GateError(
                        "decision_conflict",
                        f"decisions.{decision_id}",
                        f"decisions {decision_id!r} disagree across stored options",
                    )
                values.setdefault(decision_id, value)
    option_results = response.get("option_results")
    if isinstance(option_results, list):
        for entry in option_results:
            if not isinstance(entry, Mapping):
                continue
            result = entry.get("result")
            if not isinstance(result, Mapping):
                continue
            stored = result.get("decisions")
            if not isinstance(stored, dict):
                continue
            for decision_id, value in stored.items():
                if not isinstance(decision_id, str):
                    continue
                if decision_id in values and values[decision_id] != value:
                    raise GateError(
                        "decision_conflict",
                        f"decisions.{decision_id}",
                        f"decisions {decision_id!r} disagree with stored results",
                    )
                values.setdefault(decision_id, value)
    return values


def recover_plan_stamp_from_response(bundle_path: object) -> bool:
    """Re-stamp the durable plan from a published response without re-resolving.

    Extracts the accepted answers and original attribution from
    ``response.json`` (and its translated fields), stamps the durable plan
    when it lacks answers, and reuses the same operation wherever a completed
    response bypasses ordinary terminal preparation. Never re-runs the
    resolver, quote verification, or caller discovery, and never re-asks the
    reviewer. Identical recovery is a no-op; conflicting stamps raise.
    Returns ``True`` when a stamp was written or was already complete.
    """
    from pathlib import Path as _Path

    from sase.notification_gates.durability import read_json_object as _read

    bundle = _Path(str(bundle_path))
    try:
        response = _read(bundle / "response.json")
    except Exception:
        return False
    if not isinstance(response, dict):
        return False
    try:
        envelope = _read(bundle / "request.json")
    except Exception:
        return False
    if not isinstance(envelope, Mapping):
        return False
    payload = envelope.get("payload")
    definitions = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(definitions, list) or not definitions:
        return False
    try:
        values = _accepted_values_from_response(response)
    except GateError:
        raise
    except Exception:
        return False
    if not values:
        return False
    source = response.get("source")
    caller = response.get("caller")
    if not isinstance(source, str) or not source:
        source = str(response.get("_gate_source") or "plan_response")
    if not isinstance(caller, str) or not caller:
        caller = str(response.get("_gate_caller") or "human")
    if source == "auto_resolution":
        decided_by = "auto"
    elif source in ("tui", "plan_response", "cli", "telegram", "mobile"):
        decided_by = "reviewer" if caller == "human" else "agent"
    else:
        return False
    try:
        from sase.plan_gate import plan_context_from_envelope
        from sase.plan_gate_stamp import stamp_durable_plan
    except Exception:
        return False
    try:
        context = plan_context_from_envelope(bundle, envelope)
    except Exception:
        return False
    try:
        stamp_durable_plan(
            context,
            {"decisions": dict(values)},
            source=source,
            caller=caller
            if caller in ("human", "agent")
            else ("human" if decided_by == "reviewer" else "agent"),
        )
    except Exception as exc:
        from sase.plan_approval_actions import PlanApprovalActionError

        if isinstance(exc, (PlanApprovalActionError, GateError)):
            # Identical recovery is a no-op only when the stamp helper
            # returns quietly; any conflict propagates.
            raise
        raise
    return True


__all__ = [
    "feedback_rows_for_artifacts",
    "normalize_plan_option_inputs",
    "recover_plan_stamp_from_response",
]
