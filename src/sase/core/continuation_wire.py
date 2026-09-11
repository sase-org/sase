"""Typed Python mirrors for the Rust continuation wire contract."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, NotRequired, TypedDict

CONTINUATION_WIRE_SCHEMA_VERSION = 1

type JsonObject = dict[str, Any]
type JsonMapping = Mapping[str, Any]

ContinuationNodeKind = Literal[
    "agent_delta",
    "monitor_result",
    "checkpoint",
    "legacy_boundary",
]
AgentDeltaStatus = Literal["completed", "interrupted", "failed"]
ContinuationPromptSegmentProvenance = Literal[
    "local_authored",
    "local_materialized",
    "injected_parent",
    "host_fact",
    "tool_result",
]
MonitorOutcome = Literal[
    "completed",
    "failed",
    "timeout",
    "stopped",
    "lost",
    "unknown",
]
MonitorTimeoutKind = Literal["wall_clock", "no_progress", "external"]
DiagnosticStageStatus = Literal[
    "passed",
    "failed",
    "skipped",
    "error",
    "unknown",
]
ContinuationDeliveryDisposition = Literal[
    "pending",
    "reserved",
    "dispatching",
    "acknowledged",
    "settled",
    "cancelled",
    "nonlaunchable",
    "needs_attention",
]
ContinuationEvidencePolicy = Literal["auto", "tail", "file", "none"]
ContinuationEvidenceContextKind = Literal[
    "facts_only",
    "failed_diagnostics",
    "timeout_tail",
    "recovery_refs",
    "tail",
    "file_refs",
    "retrieval_only",
    "historical_facts",
]
ContinuationAction = Literal["continue", "none", "complete"]
ContinuationBudgetReductionKind = Literal[
    "identity_deduplication",
    "old_raw_excerpts",
    "newest_diagnostics",
    "checkpoint",
]
ContinuationBudgetDecisionKind = Literal["fits", "compact", "refuse"]


class ContinuationExecutionIdentityWire(TypedDict):
    project: str
    run_id: str
    agent_name: str
    machine_name: NotRequired[str | None]
    workspace_id: NotRequired[str | None]


class ContinuationAttributionWire(TypedDict):
    actor_kind: str
    actor_id: str
    decision_ref: NotRequired[str | None]


class ContinuationNodeWire(TypedDict):
    schema_version: int
    node_id: str
    kind: ContinuationNodeKind
    owner: ContinuationExecutionIdentityWire
    content_ref: str
    content_sha256: str
    parent_ids: NotRequired[list[str]]
    checkpoint_ref: NotRequired[str | None]
    intent_ref: NotRequired[str | None]
    workspace_ref: NotRequired[str | None]
    attribution: NotRequired[ContinuationAttributionWire | None]


class ContinuationPromptSegmentWire(TypedDict):
    segment_id: str
    provenance: ContinuationPromptSegmentProvenance
    text_ref: str
    text_sha256: str
    utf8_bytes: int
    source_ref: NotRequired[str | None]


class AgentDeltaWire(TypedDict):
    schema_version: int
    node_id: str
    authored_local_request: str
    status: AgentDeltaStatus
    materialized_local_prompt_segments: NotRequired[list[ContinuationPromptSegmentWire]]
    final_response_ref: NotRequired[str | None]
    handoff_checkpoint_ref: NotRequired[str | None]
    source_refs: NotRequired[list[str]]


class ContinuationModelRouteWire(TypedDict):
    model: NotRequired[str | None]
    effort: NotRequired[str | None]
    inherit_model: NotRequired[bool]
    inherit_effort: NotRequired[bool]


class ContinuationIntentWire(TypedDict):
    schema_version: int
    intent_id: str
    next_action: str
    route: ContinuationModelRouteWire
    outcome_policy_ref: str
    checkpoint_ref: NotRequired[str | None]
    conditional_completion_ref: NotRequired[str | None]


class ContinuationByteRangeWire(TypedDict):
    start: int
    end: int


class RetainedLogMetadataWire(TypedDict):
    log_ref: NotRequired[str | None]
    local_locator: NotRequired[str | None]
    total_observed_bytes: NotRequired[int | None]
    retained_ranges: NotRequired[list[ContinuationByteRangeWire]]
    complete: NotRequired[bool]
    drain_confirmed: NotRequired[bool]


class DiagnosticStageWire(TypedDict):
    stage_id: str
    name: str
    status: DiagnosticStageStatus
    exit_code: NotRequired[int | None]
    diagnostic_refs: NotRequired[list[str]]
    counts: NotRequired[dict[str, int]]
    retained_ranges: NotRequired[list[ContinuationByteRangeWire]]
    capture_errors: NotRequired[list[str]]


class DiagnosticManifestWire(TypedDict):
    schema_version: int
    producer: str
    stages: NotRequired[list[DiagnosticStageWire]]
    complete: NotRequired[bool]
    manifest_ref: NotRequired[str | None]


class MonitorResultWire(TypedDict):
    schema_version: int
    result_id: str
    monitor_id: str
    starter_execution_id: str
    outcome: MonitorOutcome
    cwd: str
    started_at: str
    workspace_identity: str
    retained_log: RetainedLogMetadataWire
    exit_code: NotRequired[int | None]
    command: NotRequired[list[str]]
    ended_at: NotRequired[str | None]
    elapsed_ms: NotRequired[int | None]
    timeout_kind: NotRequired[MonitorTimeoutKind | None]
    timeout_budget_ms: NotRequired[int | None]
    diagnostic_manifest_ref: NotRequired[str | None]


class ContinuationEvidenceSelectionRequestWire(TypedDict):
    schema_version: int
    result: MonitorResultWire
    policy: ContinuationEvidencePolicy
    historical_result: NotRequired[bool]
    diagnostic_manifest: NotRequired[DiagnosticManifestWire | None]
    limits: NotRequired[JsonObject]


class ContinuationReplayPlanRequestWire(TypedDict):
    schema_version: int
    records: NotRequired[list[ContinuationNodeWire]]
    root_ids: NotRequired[list[str]]
    selected_evidence_refs: NotRequired[list[str]]
    checkpoint_coverage: NotRequired[list[JsonObject]]
    rendered_components: NotRequired[list[JsonObject]]
    budget: NotRequired[JsonObject | None]
    prefix_reset_reason: NotRequired[str | None]
    max_depth: NotRequired[int | None]


class ContinuationPolicyResolutionRequestWire(TypedDict):
    schema_version: int
    outcome: MonitorOutcome
    explicit_policy: NotRequired[JsonObject | None]
    profile: NotRequired[str | None]
    shared_next: NotRequired[str | None]
    shared_model: NotRequired[str | None]
    inherited_model: NotRequired[str | None]
    inherited_effort: NotRequired[str | None]
    prepared_completion_ref: NotRequired[str | None]


class ContinuationBudgetRequestWire(TypedDict):
    schema_version: int
    rendered_prompt_bytes: int
    essential_bytes: int
    selected_evidence_bytes: NotRequired[int]
    provider_budget: NotRequired[JsonObject]
    reduction_candidates: NotRequired[list[JsonObject]]


def continuation_wire_to_json_dict(value: Any) -> Any:
    """Project continuation wire values to plain dict/list primitives."""

    if isinstance(value, Mapping):
        return {
            str(key): continuation_wire_to_json_dict(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [continuation_wire_to_json_dict(item) for item in value]
    return value


__all__ = [
    "CONTINUATION_WIRE_SCHEMA_VERSION",
    "AgentDeltaStatus",
    "AgentDeltaWire",
    "ContinuationAction",
    "ContinuationAttributionWire",
    "ContinuationBudgetDecisionKind",
    "ContinuationBudgetReductionKind",
    "ContinuationBudgetRequestWire",
    "ContinuationByteRangeWire",
    "ContinuationDeliveryDisposition",
    "ContinuationEvidenceContextKind",
    "ContinuationEvidencePolicy",
    "ContinuationEvidenceSelectionRequestWire",
    "ContinuationExecutionIdentityWire",
    "ContinuationIntentWire",
    "ContinuationModelRouteWire",
    "ContinuationNodeKind",
    "ContinuationNodeWire",
    "ContinuationPolicyResolutionRequestWire",
    "ContinuationPromptSegmentProvenance",
    "ContinuationPromptSegmentWire",
    "ContinuationReplayPlanRequestWire",
    "DiagnosticManifestWire",
    "DiagnosticStageStatus",
    "DiagnosticStageWire",
    "JsonMapping",
    "JsonObject",
    "MonitorOutcome",
    "MonitorResultWire",
    "MonitorTimeoutKind",
    "RetainedLogMetadataWire",
    "continuation_wire_to_json_dict",
]
