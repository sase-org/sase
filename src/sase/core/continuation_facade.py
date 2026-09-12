"""Thin Python facade for Rust-owned continuation contracts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.continuation_wire import (
    AgentDeltaWire,
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ConditionalCompletionBindRequestWire,
    ConditionalCompletionConsumeRequestWire,
    ConditionalCompletionEvaluateRequestWire,
    ConditionalCompletionIntentWire,
    ConditionalCompletionPrepareRequestWire,
    ConditionalCompletionRollbackRequestWire,
    ContinuationBudgetRequestWire,
    ContinuationEvidenceSelectionRequestWire,
    ContinuationIntentWire,
    ContinuationNodeWire,
    ContinuationPolicyFreezeRequestWire,
    ContinuationPolicyResolutionRequestWire,
    ContinuationReplayPlanRequestWire,
    DiagnosticManifestWire,
    JsonMapping,
    JsonObject,
    MonitorResultWire,
    continuation_wire_to_json_dict,
)
from sase.core.rust import require_rust_binding


def validate_continuation_node(
    record: ContinuationNodeWire | JsonMapping,
) -> JsonObject:
    """Validate one continuation node and return Rust's normalized shape."""

    binding = require_rust_binding("continuation_validate_node")
    return _json_object(
        binding(continuation_wire_to_json_dict(record)),
        "continuation_validate_node",
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


def new_continuation_delivery_record(request: JsonMapping) -> JsonObject:
    """Create a pending delivery record through the Rust contract."""

    binding = require_rust_binding("continuation_new_delivery_record")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_new_delivery_record",
    )


def transition_continuation_delivery(request: JsonMapping) -> JsonObject:
    """Apply one legal delivery transition through the Rust contract."""

    binding = require_rust_binding("continuation_transition_delivery")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_transition_delivery",
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


def validate_continuation_policy(policy: JsonMapping) -> JsonObject:
    """Validate and normalize a versioned outcome-policy object."""

    binding = require_rust_binding("continuation_validate_policy")
    return _json_object(
        binding(continuation_wire_to_json_dict(policy)),
        "continuation_validate_policy",
    )


def freeze_continuation_policy(
    request: ContinuationPolicyFreezeRequestWire | JsonMapping,
) -> JsonObject:
    """Freeze every outcome branch before monitor claim changes."""

    binding = require_rust_binding("continuation_freeze_policy")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_freeze_policy",
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


def validate_conditional_completion_intent(
    intent: ConditionalCompletionIntentWire | JsonMapping,
) -> JsonObject:
    """Validate one host-sealed conditional completion intent."""

    binding = require_rust_binding("continuation_validate_conditional_completion")
    return _json_object(
        binding(continuation_wire_to_json_dict(intent)),
        "continuation_validate_conditional_completion",
    )


def seal_conditional_completion(
    request: ConditionalCompletionPrepareRequestWire | JsonMapping,
) -> JsonObject:
    """Seal a conditional completion intent from host observations."""

    binding = require_rust_binding("continuation_seal_conditional_completion")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_seal_conditional_completion",
    )


def preview_conditional_completion(
    intent: ConditionalCompletionIntentWire | JsonMapping,
) -> JsonObject:
    """Render a host-completion preview for a sealed intent."""

    binding = require_rust_binding("continuation_preview_conditional_completion")
    return _json_object(
        binding(continuation_wire_to_json_dict(intent)),
        "continuation_preview_conditional_completion",
    )


def bind_conditional_completion(
    request: ConditionalCompletionBindRequestWire | JsonMapping,
) -> JsonObject:
    """Bind a prepared intent to one monitor request (single-use)."""

    binding = require_rust_binding("continuation_bind_conditional_completion")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_bind_conditional_completion",
    )


def rollback_conditional_completion_binding(
    request: ConditionalCompletionRollbackRequestWire | JsonMapping,
) -> JsonObject:
    """Roll back a failed monitor-start binding so the intent is reusable."""

    binding = require_rust_binding(
        "continuation_rollback_conditional_completion_binding"
    )
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_rollback_conditional_completion_binding",
    )


def evaluate_conditional_completion(
    request: ConditionalCompletionEvaluateRequestWire | JsonMapping,
) -> JsonObject:
    """Decide whether a bound intent is eligible for no-model host completion."""

    binding = require_rust_binding("continuation_evaluate_conditional_completion")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_evaluate_conditional_completion",
    )


def consume_conditional_completion(
    request: ConditionalCompletionConsumeRequestWire | JsonMapping,
) -> JsonObject:
    """Mark a bound intent consumed after successful host completion."""

    binding = require_rust_binding("continuation_consume_conditional_completion")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_consume_conditional_completion",
    )


def invalidate_conditional_completion(
    request: ConditionalCompletionConsumeRequestWire | JsonMapping,
) -> JsonObject:
    """Invalidate a bound intent that cannot complete and must recover."""

    binding = require_rust_binding("continuation_invalidate_conditional_completion")
    return _json_object(
        binding(continuation_wire_to_json_dict(request)),
        "continuation_invalidate_conditional_completion",
    )


def _json_object(value: Any, operation: str) -> JsonObject:
    if not isinstance(value, Mapping):
        raise TypeError(f"{operation} returned a non-mapping payload")
    return dict(value)


__all__ = [
    "CONTINUATION_WIRE_SCHEMA_VERSION",
    "bind_conditional_completion",
    "consume_conditional_completion",
    "evaluate_conditional_completion",
    "freeze_continuation_policy",
    "invalidate_conditional_completion",
    "new_continuation_delivery_record",
    "plan_continuation_budget",
    "plan_continuation_replay",
    "preview_conditional_completion",
    "resolve_continuation_policy",
    "rollback_conditional_completion_binding",
    "seal_conditional_completion",
    "select_continuation_evidence",
    "transition_continuation_delivery",
    "validate_agent_delta",
    "validate_conditional_completion_intent",
    "validate_continuation_delivery_record",
    "validate_continuation_intent",
    "validate_continuation_node",
    "validate_continuation_policy",
    "validate_diagnostic_manifest",
    "validate_monitor_result",
]
