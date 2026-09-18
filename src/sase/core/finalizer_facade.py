"""Python facade over the Rust finalizer protocol bindings."""

from __future__ import annotations

from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAggregateResultWire,
    FinalizerAssignedBeadWire,
    FinalizerContextWire,
    FinalizerInstanceResultWire,
    FinalizerInstanceSpecWire,
    FinalizerPlanInputWire,
    FinalizerPlanWire,
    FinalizerProviderSpecWire,
    FinalizerSubmissionEnvelopeWire,
    FinalizerSubmissionValidationWire,
    RemainingCommitWorkOutcomeWire,
    RemainingCommitWorkRequestWire,
    finalizer_aggregate_result_from_dict,
    finalizer_plan_from_dict,
    finalizer_submission_validation_from_dict,
    finalizer_wire_to_json_dict,
    remaining_commit_work_outcome_from_dict,
)
from sase.core.rust import require_rust_binding


class RemainingCommitWorkError(ValueError):
    """Raised when remaining-work selection rejects a repair handoff."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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


def validate_finalizer_plan(plan: FinalizerPlanWire | dict[str, Any]) -> str:
    binding = require_rust_binding("validate_finalizer_plan")
    payload = plan if isinstance(plan, dict) else finalizer_wire_to_json_dict(plan)
    return str(binding(payload))


def authenticate_finalizer_plan(
    plan: FinalizerPlanWire | dict[str, Any],
    expected_digest: str,
) -> str:
    binding = require_rust_binding("authenticate_finalizer_plan")
    payload = plan if isinstance(plan, dict) else finalizer_wire_to_json_dict(plan)
    return str(binding(payload, expected_digest))


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


def validate_finalizer_assigned_bead_binding(
    context: FinalizerContextWire | dict[str, Any],
    expected: FinalizerAssignedBeadWire | dict[str, Any] | None = None,
) -> None:
    """Validate that a finalizer context is bound to the expected assigned bead."""

    binding = require_rust_binding("validate_finalizer_assigned_bead_binding")
    expected_payload = (
        None if expected is None else finalizer_wire_to_json_dict(expected)
    )
    binding(finalizer_wire_to_json_dict(context), expected_payload)


def finalizer_json_digest(value: Any) -> str:
    binding = require_rust_binding("finalizer_json_digest")
    return str(binding(value))


def aggregate_finalizer_outcomes(
    results: list[FinalizerInstanceResultWire] | list[dict[str, Any]],
) -> FinalizerAggregateResultWire:
    binding = require_rust_binding("aggregate_finalizer_outcomes")
    payload = binding(finalizer_wire_to_json_dict(results))
    return finalizer_aggregate_result_from_dict(dict(payload))


def validate_finalizer_bead_decision(
    context: FinalizerContextWire | dict[str, Any],
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Validate one commit repository decision against assigned-bead context."""

    binding = require_rust_binding("validate_finalizer_bead_decision")
    payload = binding(finalizer_wire_to_json_dict(context), dict(decision))
    if not isinstance(payload, dict):
        raise TypeError("validate_finalizer_bead_decision returned a non-mapping")
    return dict(payload)


def select_remaining_commit_obligations(
    request: RemainingCommitWorkRequestWire | dict[str, Any],
) -> RemainingCommitWorkOutcomeWire:
    """Select remaining repository obligations after conflict repair."""

    binding = require_rust_binding("select_remaining_commit_obligations")
    payload = binding(finalizer_wire_to_json_dict(request))
    if not isinstance(payload, dict):
        raise TypeError("select_remaining_commit_obligations returned a non-mapping")
    outcome = remaining_commit_work_outcome_from_dict(dict(payload))
    if outcome.status == "rejected":
        raise RemainingCommitWorkError(
            outcome.code or "repair_handoff_rejected",
            outcome.message or "repair remaining-work selection was rejected",
        )
    if outcome.status != "remaining":
        raise TypeError(
            "select_remaining_commit_obligations returned unknown status "
            f"{outcome.status!r}"
        )
    return outcome


__all__ = [
    "RemainingCommitWorkError",
    "aggregate_finalizer_outcomes",
    "authenticate_finalizer_plan",
    "finalizer_context_digest",
    "finalizer_instance_spec_digest",
    "finalizer_json_digest",
    "finalizer_plan_digest",
    "finalizer_provider_spec_digest",
    "finalizer_wire_schema_version",
    "resolve_finalizer_plan",
    "select_remaining_commit_obligations",
    "validate_finalizer_assigned_bead_binding",
    "validate_finalizer_bead_decision",
    "validate_finalizer_context",
    "validate_finalizer_instance_spec",
    "validate_finalizer_plan",
    "validate_finalizer_provider_spec",
    "validate_finalizer_submission",
]
