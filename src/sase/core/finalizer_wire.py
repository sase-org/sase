"""Typed Python records for the Rust finalizer protocol wire contract."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

FINALIZER_WIRE_SCHEMA_VERSION = 2


JsonValue = Any


@dataclass(frozen=True)
class FinalizerProviderSpecWire:
    schema_version: int
    provider_ref: str
    provider_version: str | None = None
    capabilities: list[str] = field(default_factory=list)
    config_schema_digest: str | None = None
    submission_schema_digest: str | None = None
    result_schema_digest: str | None = None
    provenance_id: str | None = None


@dataclass(frozen=True)
class FinalizerInstancePolicyWire:
    max_attempts: int = 1
    refusal: str = "fail"


@dataclass(frozen=True)
class FinalizerInstanceSpecWire:
    schema_version: int
    instance_id: str
    provider_ref: str
    after: list[str] = field(default_factory=list)
    policy: FinalizerInstancePolicyWire = field(
        default_factory=FinalizerInstancePolicyWire
    )
    config_digest: str | None = None
    provenance_id: str | None = None


@dataclass(frozen=True)
class FinalizerSelectorOpWire:
    op: str
    instance_id: str | None = None


@dataclass(frozen=True)
class FinalizerPlanInputWire:
    schema_version: int
    instances: list[FinalizerInstanceSpecWire] = field(default_factory=list)
    defaults: list[str] = field(default_factory=list)
    required: list[str] = field(default_factory=list)
    selectors: list[FinalizerSelectorOpWire] = field(default_factory=list)


@dataclass(frozen=True)
class FinalizerPlanEntryWire:
    instance_id: str
    provider_ref: str
    after: list[str]
    policy: FinalizerInstancePolicyWire
    selector_index: int
    resolved_index: int
    config_digest: str | None = None
    provenance_id: str | None = None


@dataclass(frozen=True)
class FinalizerPlanWire:
    schema_version: int
    entries: list[FinalizerPlanEntryWire]
    plan_digest: str
    required: list[str] = field(default_factory=list)
    selectors: list[FinalizerSelectorOpWire] = field(default_factory=list)


@dataclass(frozen=True)
class FinalizerPayloadRequirementWire:
    instance_id: str
    trigger: str
    submission_required: bool = False
    requirement_digest: str | None = None


@dataclass(frozen=True)
class FinalizerObligationWire:
    obligation_id: str
    kind: str
    display_name: str | None = None
    paths: list[str] = field(default_factory=list)
    digest: str | None = None


@dataclass(frozen=True)
class FinalizerContextWire:
    schema_version: int
    run_id: str
    agent_id: str
    turn_nonce: str
    plan_digest: str
    requirements: list[FinalizerPayloadRequirementWire] = field(default_factory=list)
    obligations: list[FinalizerObligationWire] = field(default_factory=list)
    context_digest: str | None = None


@dataclass(frozen=True)
class FinalizerSubmissionPayloadWire:
    instance_id: str
    payload: JsonValue
    payload_digest: str | None = None


@dataclass(frozen=True)
class FinalizerSubmissionEnvelopeWire:
    schema_version: int
    run_id: str
    agent_id: str
    turn_nonce: str
    plan_digest: str
    context_digest: str
    payloads: list[FinalizerSubmissionPayloadWire] = field(default_factory=list)


@dataclass(frozen=True)
class FinalizerSubmissionValidationWire:
    schema_version: int
    submission_digest: str
    accepted_instances: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FinalizerDiagnosticWire:
    code: str
    message: str
    severity: str
    instance_id: str | None = None
    attempt: int | None = None


@dataclass(frozen=True)
class FinalizerAttemptWire:
    attempt: int
    status: str
    diagnostic_code: str | None = None


@dataclass(frozen=True)
class FinalizerOutcomeEvidenceWire:
    kind: str
    value: str


@dataclass(frozen=True)
class FinalizerInstanceResultWire:
    instance_id: str
    status: str
    attempts: list[FinalizerAttemptWire] = field(default_factory=list)
    refusal_reason: str | None = None
    evidence: list[FinalizerOutcomeEvidenceWire] = field(default_factory=list)
    diagnostics: list[FinalizerDiagnosticWire] = field(default_factory=list)


@dataclass(frozen=True)
class FinalizerAggregateResultWire:
    schema_version: int
    status: str
    instances: list[FinalizerInstanceResultWire]
    diagnostics: list[FinalizerDiagnosticWire] = field(default_factory=list)


def finalizer_add(instance_id: str) -> FinalizerSelectorOpWire:
    return FinalizerSelectorOpWire(op="add", instance_id=instance_id)


def finalizer_remove(instance_id: str) -> FinalizerSelectorOpWire:
    return FinalizerSelectorOpWire(op="remove", instance_id=instance_id)


def finalizer_clear() -> FinalizerSelectorOpWire:
    return FinalizerSelectorOpWire(op="clear")


def finalizer_wire_to_json_dict(record: Any) -> Any:
    """Project finalizer wire dataclasses to JSON-safe dict/list/scalar values."""

    if isinstance(record, (list, tuple)):
        return [finalizer_wire_to_json_dict(item) for item in record]
    if isinstance(record, dict):
        return {str(k): finalizer_wire_to_json_dict(v) for k, v in record.items()}
    if hasattr(record, "__dataclass_fields__"):
        return _drop_none(finalizer_wire_to_json_dict(asdict(record)))
    return record


def _drop_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _drop_none(item)
            for key, item in value.items()
            if item is not None and not (key == "instance_id" and item is None)
        }
    if isinstance(value, list):
        return [_drop_none(item) for item in value]
    return value


def finalizer_provider_spec_from_dict(
    data: dict[str, Any],
) -> FinalizerProviderSpecWire:
    return FinalizerProviderSpecWire(
        schema_version=int(data["schema_version"]),
        provider_ref=str(data["provider_ref"]),
        provider_version=_optional_str(data.get("provider_version")),
        capabilities=[str(item) for item in data.get("capabilities", [])],
        config_schema_digest=_optional_str(data.get("config_schema_digest")),
        submission_schema_digest=_optional_str(data.get("submission_schema_digest")),
        result_schema_digest=_optional_str(data.get("result_schema_digest")),
        provenance_id=_optional_str(data.get("provenance_id")),
    )


def finalizer_instance_policy_from_dict(
    data: dict[str, Any] | None,
) -> FinalizerInstancePolicyWire:
    data = data or {}
    return FinalizerInstancePolicyWire(
        max_attempts=int(data.get("max_attempts", 1)),
        refusal=str(data.get("refusal", "fail")),
    )


def finalizer_instance_spec_from_dict(
    data: dict[str, Any],
) -> FinalizerInstanceSpecWire:
    return FinalizerInstanceSpecWire(
        schema_version=int(data["schema_version"]),
        instance_id=str(data["instance_id"]),
        provider_ref=str(data["provider_ref"]),
        after=[str(item) for item in data.get("after", [])],
        policy=finalizer_instance_policy_from_dict(data.get("policy")),
        config_digest=_optional_str(data.get("config_digest")),
        provenance_id=_optional_str(data.get("provenance_id")),
    )


def finalizer_selector_op_from_dict(data: dict[str, Any]) -> FinalizerSelectorOpWire:
    return FinalizerSelectorOpWire(
        op=str(data["op"]),
        instance_id=_optional_str(data.get("instance_id")),
    )


def finalizer_plan_from_dict(data: dict[str, Any]) -> FinalizerPlanWire:
    return FinalizerPlanWire(
        schema_version=int(data["schema_version"]),
        entries=[
            FinalizerPlanEntryWire(
                instance_id=str(entry["instance_id"]),
                provider_ref=str(entry["provider_ref"]),
                after=[str(item) for item in entry.get("after", [])],
                policy=finalizer_instance_policy_from_dict(entry.get("policy")),
                config_digest=_optional_str(entry.get("config_digest")),
                provenance_id=_optional_str(entry.get("provenance_id")),
                selector_index=int(entry["selector_index"]),
                resolved_index=int(entry["resolved_index"]),
            )
            for entry in data.get("entries", [])
        ],
        required=[str(item) for item in data.get("required", [])],
        selectors=[
            finalizer_selector_op_from_dict(dict(selector))
            for selector in data.get("selectors", [])
        ],
        plan_digest=str(data["plan_digest"]),
    )


def finalizer_context_from_dict(data: dict[str, Any]) -> FinalizerContextWire:
    return FinalizerContextWire(
        schema_version=int(data["schema_version"]),
        run_id=str(data["run_id"]),
        agent_id=str(data["agent_id"]),
        turn_nonce=str(data["turn_nonce"]),
        plan_digest=str(data["plan_digest"]),
        requirements=[
            FinalizerPayloadRequirementWire(
                instance_id=str(requirement["instance_id"]),
                trigger=str(requirement["trigger"]),
                submission_required=bool(requirement.get("submission_required", False)),
                requirement_digest=_optional_str(requirement.get("requirement_digest")),
            )
            for requirement in data.get("requirements", [])
        ],
        obligations=[
            FinalizerObligationWire(
                obligation_id=str(obligation["obligation_id"]),
                kind=str(obligation["kind"]),
                display_name=_optional_str(obligation.get("display_name")),
                paths=[str(item) for item in obligation.get("paths", [])],
                digest=_optional_str(obligation.get("digest")),
            )
            for obligation in data.get("obligations", [])
        ],
        context_digest=_optional_str(data.get("context_digest")),
    )


def finalizer_submission_validation_from_dict(
    data: dict[str, Any],
) -> FinalizerSubmissionValidationWire:
    return FinalizerSubmissionValidationWire(
        schema_version=int(data["schema_version"]),
        submission_digest=str(data["submission_digest"]),
        accepted_instances=[str(item) for item in data.get("accepted_instances", [])],
    )


def finalizer_diagnostic_from_dict(data: dict[str, Any]) -> FinalizerDiagnosticWire:
    return FinalizerDiagnosticWire(
        code=str(data["code"]),
        message=str(data["message"]),
        severity=str(data["severity"]),
        instance_id=_optional_str(data.get("instance_id")),
        attempt=_optional_int(data.get("attempt")),
    )


def finalizer_attempt_from_dict(data: dict[str, Any]) -> FinalizerAttemptWire:
    return FinalizerAttemptWire(
        attempt=int(data["attempt"]),
        status=str(data["status"]),
        diagnostic_code=_optional_str(data.get("diagnostic_code")),
    )


def finalizer_instance_result_from_dict(
    data: dict[str, Any],
) -> FinalizerInstanceResultWire:
    return FinalizerInstanceResultWire(
        instance_id=str(data["instance_id"]),
        status=str(data["status"]),
        attempts=[
            finalizer_attempt_from_dict(dict(attempt))
            for attempt in data.get("attempts", [])
        ],
        refusal_reason=_optional_str(data.get("refusal_reason")),
        evidence=[
            FinalizerOutcomeEvidenceWire(
                kind=str(evidence["kind"]),
                value=str(evidence["value"]),
            )
            for evidence in data.get("evidence", [])
        ],
        diagnostics=[
            finalizer_diagnostic_from_dict(dict(diagnostic))
            for diagnostic in data.get("diagnostics", [])
        ],
    )


def finalizer_aggregate_result_from_dict(
    data: dict[str, Any],
) -> FinalizerAggregateResultWire:
    return FinalizerAggregateResultWire(
        schema_version=int(data["schema_version"]),
        status=str(data["status"]),
        instances=[
            finalizer_instance_result_from_dict(dict(instance))
            for instance in data.get("instances", [])
        ],
        diagnostics=[
            finalizer_diagnostic_from_dict(dict(diagnostic))
            for diagnostic in data.get("diagnostics", [])
        ],
    )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


__all__ = [
    "FINALIZER_WIRE_SCHEMA_VERSION",
    "FinalizerAggregateResultWire",
    "FinalizerAttemptWire",
    "FinalizerContextWire",
    "FinalizerDiagnosticWire",
    "FinalizerInstancePolicyWire",
    "FinalizerInstanceResultWire",
    "FinalizerInstanceSpecWire",
    "FinalizerObligationWire",
    "FinalizerOutcomeEvidenceWire",
    "FinalizerPayloadRequirementWire",
    "FinalizerPlanEntryWire",
    "FinalizerPlanInputWire",
    "FinalizerPlanWire",
    "FinalizerProviderSpecWire",
    "FinalizerSelectorOpWire",
    "FinalizerSubmissionEnvelopeWire",
    "FinalizerSubmissionPayloadWire",
    "FinalizerSubmissionValidationWire",
    "JsonValue",
    "finalizer_add",
    "finalizer_aggregate_result_from_dict",
    "finalizer_clear",
    "finalizer_context_from_dict",
    "finalizer_instance_result_from_dict",
    "finalizer_instance_spec_from_dict",
    "finalizer_plan_from_dict",
    "finalizer_provider_spec_from_dict",
    "finalizer_remove",
    "finalizer_submission_validation_from_dict",
    "finalizer_wire_to_json_dict",
]
