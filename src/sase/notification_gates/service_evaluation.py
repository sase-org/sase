"""Automatic-gate evaluation for the notification-gate creation service."""

from __future__ import annotations

import dataclasses
from typing import Any

from sase.notification_gates.models import GateError, GateSpec
from sase.notification_gates.registry import GateAdapter


def _evaluate_gate_request(
    spec: GateSpec, adapter: GateAdapter
) -> tuple[dict[str, Any] | None, dict[str, Any], dict[str, Any]]:
    """Evaluate one gate creation through core ``evaluate()`` exactly once.

    Returns ``(record, decision, policy_block)`` from the record snapshot
    the spec carries (or the legacy ``enabled``/``argument`` translation
    for hand-built specs). A cross-tier argument evaluates to ``ask``
    through the record's policy, so the gate parks as manual; an unknown
    spelling stays an ``invalid_auto_argument`` error.
    """
    from sase.autonomy.gates import (
        evaluate_gate,
        policy_block_for_decision,
        record_for_auto_block,
    )

    try:
        record = record_for_auto_block(
            {
                "enabled": spec.auto.enabled,
                "argument": spec.auto.argument,
                "policy": spec.auto.policy,
            }
        )
    except ValueError as exc:
        raise GateError("invalid_auto_argument", "auto.argument", str(exc)) from exc
    decision = evaluate_gate(
        record,
        gate_kind=adapter.kind,
        option_ids=[option.id for option in spec.options],
    )
    if decision.get("profile") != "manual":
        _append_gate_decision_log(spec, adapter, record, decision)
    return record, decision, policy_block_for_decision(decision)


def _append_gate_decision_log(
    spec: GateSpec,
    adapter: GateAdapter,
    record: dict[str, Any] | None,
    decision: dict[str, Any],
) -> None:
    """Append the host decision-log row for one non-manual evaluation."""
    from sase.autonomy.gates import append_decision_log, creator_meta_for_producer

    try:
        producer = spec.producer if isinstance(spec.producer, dict) else {}
    except Exception:
        producer = {}
    append_decision_log(
        decision=decision,
        gate_kind=adapter.kind,
        gate_id=spec.request_id or "",
        creator_meta=creator_meta_for_producer(producer),
    )


def effective_auto_state(
    spec: GateSpec, adapter: GateAdapter
) -> tuple[GateSpec, dict[str, Any], dict[str, Any], bool]:
    """Evaluate one creation and normalize the spec to its outcome.

    Returns ``(effective_spec, decision, policy_block, auto_execute)``.
    The effective spec keeps the requested auto block only when the gate
    actually auto-executes; an ``ask`` decision normalizes it to manual
    before fingerprinting, so the notification and pending row are
    published as today. The policy block rides along either way, so every
    plan, epic, and question gate carries one.
    """
    from sase.autonomy.gates import POLICY_BLOCK_KINDS

    _record, decision, block = _evaluate_gate_request(spec, adapter)
    auto_execute = bool(spec.auto.enabled) and decision.get("outcome") == "auto"
    if auto_execute:
        return spec, decision, block, True
    return (
        dataclasses.replace(
            spec,
            auto=dataclasses.replace(
                spec.auto, enabled=False, argument=None, policy=spec.auto.policy
            ),
        ),
        decision,
        block,
        False,
    )


__all__ = ["effective_auto_state"]
