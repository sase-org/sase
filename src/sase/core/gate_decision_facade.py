"""Python facade over the Rust gate-decision-acceptance policy bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding

GATE_DECISION_WIRE_SCHEMA_VERSION = 1
GATE_LIFECYCLE_WIRE_SCHEMA_VERSION = 1


def decide_gate_decision_acceptance(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the Rust acceptance outcome for one gate-decision fact set.

    Raises ``ValueError`` (propagated from the Rust binding, message prefixed
    with its stable error code, e.g. ``gate_decision_conflict: ...``) when
    the request names a decision that conflicts with an existing receipt, or
    carries an unsupported schema version.
    """
    binding = require_rust_binding("decide_gate_decision_acceptance")
    result = binding(dict(request))
    if not isinstance(result, dict):
        raise TypeError("decide_gate_decision_acceptance returned a non-mapping")
    return dict(result)


def decide_gate_lifecycle(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the Rust lifecycle disposition for one gate's collected evidence.

    Raises ``ValueError`` (propagated from the Rust binding, message prefixed
    with its stable error code, e.g. ``invalid_gate_decision_receipt: ...``)
    when a decision receipt is unreadable or names a different gate or
    request, or the request carries an unsupported schema version.
    """
    binding = require_rust_binding("decide_gate_lifecycle")
    result = binding(dict(request))
    if not isinstance(result, dict):
        raise TypeError("decide_gate_lifecycle returned a non-mapping")
    return dict(result)


def claim_gate_decision_execution(request: Mapping[str, Any]) -> dict[str, Any]:
    """Re-own a still-current receipt immediately before executing it.

    Raises ``ValueError`` (code ``gate_decision_conflict``) when the receipt
    named in *request* was superseded while the caller waited to execute it.

    Consumed by the ``owner_conflict`` phase's claim step
    (bead ``sase-zr.7.1.1.3``); not called yet.
    """
    binding = require_rust_binding("claim_gate_decision_execution")
    result = binding(dict(request))
    if not isinstance(result, dict):
        raise TypeError("claim_gate_decision_execution returned a non-mapping")
    return dict(result)


__all__ = [
    "GATE_DECISION_WIRE_SCHEMA_VERSION",
    "GATE_LIFECYCLE_WIRE_SCHEMA_VERSION",
    "claim_gate_decision_execution",
    "decide_gate_decision_acceptance",
    "decide_gate_lifecycle",
]
