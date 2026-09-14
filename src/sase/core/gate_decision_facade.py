"""Python facade over the Rust gate-decision-acceptance policy bindings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.rust import require_rust_binding

GATE_DECISION_WIRE_SCHEMA_VERSION = 1


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


__all__ = [
    "GATE_DECISION_WIRE_SCHEMA_VERSION",
    "decide_gate_decision_acceptance",
]
