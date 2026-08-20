"""Python facade over the Rust finalizer protocol bindings."""

from __future__ import annotations

from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAggregateResultWire,
    FinalizerContextWire,
    FinalizerInstanceResultWire,
    FinalizerInstanceSpecWire,
    FinalizerPlanInputWire,
    FinalizerPlanWire,
    FinalizerProviderSpecWire,
    FinalizerSubmissionEnvelopeWire,
    FinalizerSubmissionValidationWire,
    finalizer_aggregate_result_from_dict,
    finalizer_plan_from_dict,
    finalizer_submission_validation_from_dict,
    finalizer_wire_to_json_dict,
)
from sase.core.rust import require_rust_binding


def finalizer_wire_schema_version() -> int:
    binding = require_rust_binding("finalizer_wire_schema_version")
    return int(binding())


def validate_finalizer_provider_spec(
    spec: FinalizerProviderSpecWire | dict[str, Any],
) -> None:
    binding = require_rust_binding("validate_finalizer_provider_spec")
    binding(finalizer_wire_to_json_dict(spec))


def finalizer_provider_spec_digest(
    spec: FinalizerProviderSpecWire | dict[str, Any],
) -> str:
    binding = require_rust_binding("finalizer_provider_spec_digest")
    return str(binding(finalizer_wire_to_json_dict(spec)))


def validate_finalizer_instance_spec(
    spec: FinalizerInstanceSpecWire | dict[str, Any],
) -> None:
    binding = require_rust_binding("validate_finalizer_instance_spec")
    binding(finalizer_wire_to_json_dict(spec))


def finalizer_instance_spec_digest(
    spec: FinalizerInstanceSpecWire | dict[str, Any],
) -> str:
    binding = require_rust_binding("finalizer_instance_spec_digest")
    return str(binding(finalizer_wire_to_json_dict(spec)))


def resolve_finalizer_plan(
    request: FinalizerPlanInputWire | dict[str, Any],
) -> FinalizerPlanWire:
    binding = require_rust_binding("resolve_finalizer_plan")
    payload = binding(finalizer_wire_to_json_dict(request))
    return finalizer_plan_from_dict(dict(payload))


def finalizer_plan_digest(plan: FinalizerPlanWire | dict[str, Any]) -> str:
    binding = require_rust_binding("finalizer_plan_digest")
    return str(binding(finalizer_wire_to_json_dict(plan)))


def finalizer_context_digest(context: FinalizerContextWire | dict[str, Any]) -> str:
    binding = require_rust_binding("finalizer_context_digest")
    return str(binding(finalizer_wire_to_json_dict(context)))


def validate_finalizer_context(
    plan: FinalizerPlanWire | dict[str, Any],
    context: FinalizerContextWire | dict[str, Any],
) -> str:
    binding = require_rust_binding("validate_finalizer_context")
    return str(
        binding(
            finalizer_wire_to_json_dict(plan),
            finalizer_wire_to_json_dict(context),
        )
    )


def validate_finalizer_submission(
    plan: FinalizerPlanWire | dict[str, Any],
    context: FinalizerContextWire | dict[str, Any],
    submission: FinalizerSubmissionEnvelopeWire | dict[str, Any],
) -> FinalizerSubmissionValidationWire:
    binding = require_rust_binding("validate_finalizer_submission")
    payload = binding(
        finalizer_wire_to_json_dict(plan),
        finalizer_wire_to_json_dict(context),
        finalizer_wire_to_json_dict(submission),
    )
    return finalizer_submission_validation_from_dict(dict(payload))


def finalizer_json_digest(value: Any) -> str:
    binding = require_rust_binding("finalizer_json_digest")
    return str(binding(value))


def aggregate_finalizer_outcomes(
    results: list[FinalizerInstanceResultWire] | list[dict[str, Any]],
) -> FinalizerAggregateResultWire:
    binding = require_rust_binding("aggregate_finalizer_outcomes")
    payload = binding(finalizer_wire_to_json_dict(results))
    return finalizer_aggregate_result_from_dict(dict(payload))


__all__ = [
    "aggregate_finalizer_outcomes",
    "finalizer_context_digest",
    "finalizer_instance_spec_digest",
    "finalizer_json_digest",
    "finalizer_plan_digest",
    "finalizer_provider_spec_digest",
    "finalizer_wire_schema_version",
    "resolve_finalizer_plan",
    "validate_finalizer_context",
    "validate_finalizer_instance_spec",
    "validate_finalizer_provider_spec",
    "validate_finalizer_submission",
]
