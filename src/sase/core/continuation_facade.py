"""Thin Python facade for Rust-owned continuation contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.continuation_wire import (
    AgentDeltaWire,
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ContinuationBudgetRequestWire,
    ContinuationEvidenceSelectionRequestWire,
    ContinuationIntentWire,
    ContinuationNodeWire,
    ContinuationPolicyResolutionRequestWire,
    ContinuationReplayPlanRequestWire,
    DiagnosticManifestWire,
    JsonMapping,
    JsonObject,
    LaunchRequesterContinuationWire,
    MonitorResultWire,
    continuation_wire_to_json_dict,
)
from sase.core.rust import require_rust_binding


def continuation_wire_schema_version() -> int:
    """Return the Rust continuation wire schema version."""

    binding = require_rust_binding("continuation_wire_schema_version")
    return int(binding())


def validate_continuation_node(
    record: ContinuationNodeWire | JsonMapping,
) -> JsonObject:
    """Validate one continuation node and return Rust's normalized shape."""

    binding = require_rust_binding("continuation_validate_node")
    return _json_object(
        binding(continuation_wire_to_json_dict(record)),
        "continuation_validate_node",
    )


def validate_continuation_graph(
    records: Sequence[ContinuationNodeWire | JsonMapping],
) -> JsonObject:
    """Validate exact node identity, duplicate IDs, parents, and cycles."""

    binding = require_rust_binding("continuation_validate_graph")
    return _json_object(
        binding(continuation_wire_to_json_dict(records)),
        "continuation_validate_graph",
    )


def validate_agent_delta(delta: AgentDeltaWire | JsonMapping) -> JsonObject:
    """Validate one agent-delta record."""

    binding = require_rust_binding("continuation_validate_agent_delta")
    return _json_object(
        binding(continuation_wire_to_json_dict(delta)),
        "continuation_validate_agent_delta",
    )


def validate_continuation_intent(
    intent: ContinuationIntentWire | JsonMapping,
) -> JsonObject:
    """Validate one continuation-intent record."""

    binding = require_rust_binding("continuation_validate_intent")
    return _json_object(
        binding(continuation_wire_to_json_dict(intent)),
        "continuation_validate_intent",
    )


def validate_monitor_result(result: MonitorResultWire | JsonMapping) -> JsonObject:
    """Validate one monitor-result record."""

    binding = require_rust_binding("continuation_validate_monitor_result")
    return _json_object(
        binding(continuation_wire_to_json_dict(result)),
        "continuation_validate_monitor_result",
    )


def validate_diagnostic_manifest(
    manifest: DiagnosticManifestWire | JsonMapping,
) -> JsonObject:
    """Validate one diagnostic-manifest record."""

    binding = require_rust_binding("continuation_validate_diagnostic_manifest")
    return _json_object(
        binding(continuation_wire_to_json_dict(manifest)),
        "continuation_validate_diagnostic_manifest",
    )


def validate_continuation_delivery_record(record: JsonMapping) -> JsonObject:
    """Validate one mutable delivery record."""

    binding = require_rust_binding("continuation_validate_delivery_record")
    return _json_object(
        binding(continuation_wire_to_json_dict(record)),
        "continuation_validate_delivery_record",
    )


def validate_launch_requester_continuation(
    continuation: LaunchRequesterContinuationWire | JsonMapping,
) -> JsonObject:
    """Validate one LaunchApproval requester-continuation contract."""

    binding = require_rust_binding(
        "continuation_validate_launch_requester_continuation"
    )
    return _json_object(
        binding(continuation_wire_to_json_dict(continuation)),
        "continuation_validate_launch_requester_continuation",
    )


def plan_continuation_replay(
    request: ContinuationReplayPlanRequestWire | JsonMapping,
) -> JsonObject:
    """Return the deterministic parent-first replay manifest."""

    binding = require_rust_binding("continuation_plan_replay")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_plan_replay",
    )


def select_continuation_evidence(
    request: ContinuationEvidenceSelectionRequestWire | JsonMapping,
) -> JsonObject:
    """Select outcome-aware evidence for continuation context."""

    binding = require_rust_binding("continuation_select_evidence")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_select_evidence",
    )


def resolve_continuation_policy(
    request: ContinuationPolicyResolutionRequestWire | JsonMapping,
) -> JsonObject:
    """Resolve the next-action branch for a terminal monitor outcome."""

    binding = require_rust_binding("continuation_resolve_policy")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_resolve_policy",
    )


def plan_continuation_budget(
    request: ContinuationBudgetRequestWire | JsonMapping,
) -> JsonObject:
    """Decide whether an expanded continuation fits the provider budget."""

    binding = require_rust_binding("continuation_plan_budget")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_plan_budget",
    )


def _json_object(value: Any, operation: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{operation} returned a non-mapping payload")
    return dict(value)


__all__ = [
    "CONTINUATION_WIRE_SCHEMA_VERSION",
    "continuation_wire_schema_version",
    "plan_continuation_budget",
    "plan_continuation_replay",
    "resolve_continuation_policy",
    "select_continuation_evidence",
    "validate_agent_delta",
    "validate_continuation_delivery_record",
    "validate_continuation_graph",
    "validate_continuation_intent",
    "validate_continuation_node",
    "validate_diagnostic_manifest",
    "validate_launch_requester_continuation",
    "validate_monitor_result",
]
