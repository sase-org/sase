"""Python facade over the Rust gate-decision-acceptance policy bindings."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
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


@lru_cache(maxsize=1)
def gate_lifecycle_supports_post_response_failure() -> bool:
    """Return whether the installed Rust binding accepts post-response evidence."""
    binding = require_rust_binding("decide_gate_lifecycle")
    receipt = {
        "schema_version": GATE_DECISION_WIRE_SCHEMA_VERSION,
        "gate_id": "__sase_capability_probe__",
        "request_hash": "request",
        "selected_option_ids": ["accept"],
        "input_identity": "input",
        "acceptance_id": "acceptance",
        "source": "probe",
        "accepted_at_unix": 0.0,
        "identity_fingerprint": "probe",
    }
    failure = {
        "outcome_id": "outcome",
        "acceptance_id": "acceptance",
        "attempt_id": "probe",
        "stage": "side_effects",
        "code": "side_effect_failed",
        "message": "probe",
        "at_unix": 0.0,
        "error_record": "errors/probe.json",
    }
    request = {
        "schema_version": GATE_LIFECYCLE_WIRE_SCHEMA_VERSION,
        "gate_id": "__sase_capability_probe__",
        "request_hash": "request",
        "now_unix": 0.0,
        "grace_seconds": 0.0,
        "has_response": True,
        "receipt_unreadable": False,
        "receipt": receipt,
        "execution_facts": {"post_response_failure": failure},
    }
    try:
        binding(request)
    except ValueError as exc:
        message = str(exc)
        if "post_response_failure" in message or "unknown field" in message:
            return False
        raise
    return True


def claim_gate_decision_execution(request: Mapping[str, Any]) -> dict[str, Any]:
    """Re-own a still-current receipt immediately before executing it.

    Raises ``ValueError`` (code ``gate_decision_conflict``) when the receipt
    named in *request* was superseded while the caller waited to execute it.

    Consumed by the gate executor's claim step before it appends an attempt
    event for the accepted decision.
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
    "gate_lifecycle_supports_post_response_failure",
]
