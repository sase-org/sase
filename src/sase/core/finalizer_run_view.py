"""Typed Python facade over the finalizer node-view projection binding."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerDiagnosticWire,
    finalizer_diagnostic_from_dict,
)
from sase.core.rust import require_rust_binding

#: Schema version of the node-view request/response wires. Keep in lockstep
#: with sase-core ``finalizer::run_view::wire::RUN_VIEW_WIRE_SCHEMA_VERSION``.
RUN_VIEW_WIRE_SCHEMA_VERSION = 1

#: Default ``tail_lines`` for node-view requests (plan section 3.4).
RUN_VIEW_TAIL_LINES_DEFAULT = 12


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _coerced_str(value: Any, default: str = "") -> str:
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def _coerced_int(value: Any, default: int = 0) -> int:
    parsed = _optional_int(value)
    return default if parsed is None else parsed


def _optional_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


@dataclass(frozen=True)
class _RunViewEvidence:
    """One typed evidence record (``evidence_type`` mirrors the Rust wire)."""

    kind: str
    value: str
    evidence_type: str | None = None
    display: str | None = None


def _run_view_evidence_from_dict(data: dict[str, Any]) -> _RunViewEvidence:
    return _RunViewEvidence(
        kind=_coerced_str(data.get("kind")),
        value=_coerced_str(data.get("value")),
        evidence_type=_optional_str(data.get("evidence_type")),
        display=_optional_str(data.get("display")),
    )


@dataclass(frozen=True)
class _RunViewAppearance:
    """One run's status appearance of a node-level instance."""

    run_id: str
    status: str


def _run_view_appearance_from_dict(data: dict[str, Any]) -> _RunViewAppearance:
    return _RunViewAppearance(
        run_id=_coerced_str(data.get("run_id")),
        status=_coerced_str(data.get("status")),
    )


@dataclass(frozen=True)
class _RunViewNodeInstance:
    """One node-level instance: the union across runs in DAG order."""

    instance_id: str
    selection_reason: str
    status: str
    provider_ref: str | None = None
    after: list[str] = field(default_factory=list)
    appearances: list[_RunViewAppearance] = field(default_factory=list)


def _run_view_node_instance_from_dict(data: dict[str, Any]) -> _RunViewNodeInstance:
    return _RunViewNodeInstance(
        instance_id=_coerced_str(data.get("instance_id")),
        selection_reason=_coerced_str(data.get("selection_reason")),
        status=_coerced_str(data.get("status")),
        provider_ref=_optional_str(data.get("provider_ref")),
        after=_str_list(data.get("after")),
        appearances=[
            _run_view_appearance_from_dict(dict(item))
            for item in data.get("appearances", [])
            if isinstance(item, dict)
        ],
    )


@dataclass(frozen=True)
class _RunViewUnselected:
    """One configured-but-unselected instance with its reason."""

    instance_id: str
    reason: str
    provider_ref: str | None = None


def _run_view_unselected_from_dict(data: dict[str, Any]) -> _RunViewUnselected:
    return _RunViewUnselected(
        instance_id=_coerced_str(data.get("instance_id")),
        reason=_coerced_str(data.get("reason")),
        provider_ref=_optional_str(data.get("provider_ref")),
    )


@dataclass(frozen=True)
class _RunViewDeclaration:
    """One declaration timeline entry."""

    status: str
    t: float | None = None
    code: str | None = None
    first_line: str | None = None
    payload_count: int | None = None


def _run_view_declaration_from_dict(data: dict[str, Any]) -> _RunViewDeclaration:
    return _RunViewDeclaration(
        status=_coerced_str(data.get("status")),
        t=_optional_float(data.get("t")),
        code=_optional_str(data.get("code")),
        first_line=_optional_str(data.get("first_line")),
        payload_count=_optional_int(data.get("payload_count")),
    )


@dataclass(frozen=True)
class _RunViewRecoveryTurn:
    """The declaration-recovery model turn fact, when one ran."""

    ok: bool | None = None
    code: str | None = None


def _run_view_recovery_turn_from_dict(data: dict[str, Any]) -> _RunViewRecoveryTurn:
    ok = data.get("ok")
    return _RunViewRecoveryTurn(
        ok=None if not isinstance(ok, bool) else ok,
        code=_optional_str(data.get("code")),
    )


@dataclass(frozen=True)
class _RunViewDrift:
    """One sealed-vs-live configuration drift entry."""

    message: str
    instance_id: str | None = None
    code: str | None = None


def _run_view_drift_from_dict(data: dict[str, Any]) -> _RunViewDrift:
    return _RunViewDrift(
        message=_coerced_str(data.get("message")),
        instance_id=_optional_str(data.get("instance_id")),
        code=_optional_str(data.get("code")),
    )


@dataclass(frozen=True)
class _RunViewAttempt:
    """One budgeted try of an instance."""

    attempt: int
    status: str
    started_at: float | None = None
    duration_seconds: float | None = None
    code: str | None = None


def _run_view_attempt_from_dict(data: dict[str, Any]) -> _RunViewAttempt:
    return _RunViewAttempt(
        attempt=_coerced_int(data.get("attempt"), 0),
        status=_coerced_str(data.get("status")),
        started_at=_optional_float(data.get("started_at")),
        duration_seconds=_optional_float(data.get("duration_seconds")),
        code=_optional_str(data.get("code")),
    )


@dataclass(frozen=True)
class _RunViewStep:
    """One structured progress step inside an operation."""

    step: str
    state: str
    t: float | None = None
    detail: str | None = None


def _run_view_step_from_dict(data: dict[str, Any]) -> _RunViewStep:
    return _RunViewStep(
        step=_coerced_str(data.get("step")),
        state=_coerced_str(data.get("state")),
        t=_optional_float(data.get("t")),
        detail=_optional_str(data.get("detail")),
    )


@dataclass(frozen=True)
class _RunViewLog:
    """One log file backing an operation."""

    kind: str
    name: str
    size: int | None = None
    line_count: int | None = None
    truncated: bool | None = None


def _run_view_log_from_dict(data: dict[str, Any]) -> _RunViewLog:
    truncated = data.get("truncated")
    return _RunViewLog(
        kind=_coerced_str(data.get("kind")),
        name=_coerced_str(data.get("name")),
        size=_optional_int(data.get("size")),
        line_count=_optional_int(data.get("line_count")),
        truncated=None if not isinstance(truncated, bool) else truncated,
    )


@dataclass(frozen=True)
class _RunViewOperation:
    """One unit of work inside an attempt."""

    op: str
    argv: list[str] = field(default_factory=list)
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False
    logs: list[_RunViewLog] = field(default_factory=list)
    steps: list[_RunViewStep] = field(default_factory=list)
    steps_truncated: bool = False
    live_tail: list[str] = field(default_factory=list)
    kind: str | None = None
    label: str | None = None
    attempt: int | None = None
    started_at: float | None = None
    duration_seconds: float | None = None
    returncode: int | None = None


def _coerced_bool(value: Any, default: bool = False) -> bool:
    return default if not isinstance(value, bool) else value


def _run_view_operation_from_dict(data: dict[str, Any]) -> _RunViewOperation:
    return _RunViewOperation(
        op=_coerced_str(data.get("op")),
        argv=_str_list(data.get("argv")),
        timed_out=_coerced_bool(data.get("timed_out")),
        stdout_truncated=_coerced_bool(data.get("stdout_truncated")),
        stderr_truncated=_coerced_bool(data.get("stderr_truncated")),
        logs=[
            _run_view_log_from_dict(dict(item))
            for item in data.get("logs", [])
            if isinstance(item, dict)
        ],
        steps=[
            _run_view_step_from_dict(dict(item))
            for item in data.get("steps", [])
            if isinstance(item, dict)
        ],
        steps_truncated=_coerced_bool(data.get("steps_truncated")),
        live_tail=_str_list(data.get("live_tail")),
        kind=_optional_str(data.get("kind")),
        label=_optional_str(data.get("label")),
        attempt=_optional_int(data.get("attempt")),
        started_at=_optional_float(data.get("started_at")),
        duration_seconds=_optional_float(data.get("duration_seconds")),
        returncode=_optional_int(data.get("returncode")),
    )


@dataclass(frozen=True)
class _RunViewInstanceDiagnostic:
    """One deduped instance diagnostic with attempt-scoped severity."""

    code: str
    message: str
    severity: str
    attempt: int | None = None


def _run_view_instance_diagnostic_from_dict(
    data: dict[str, Any],
) -> _RunViewInstanceDiagnostic:
    return _RunViewInstanceDiagnostic(
        code=_coerced_str(data.get("code")),
        message=_coerced_str(data.get("message")),
        severity=_coerced_str(data.get("severity")),
        attempt=_optional_int(data.get("attempt")),
    )


@dataclass(frozen=True)
class _RunViewDeferral:
    """The typed deferral payload for a deferred instance."""

    reason: str
    paths: list[str] = field(default_factory=list)


def _run_view_deferral_from_dict(data: dict[str, Any]) -> _RunViewDeferral:
    return _RunViewDeferral(
        reason=_coerced_str(data.get("reason")),
        paths=_str_list(data.get("paths")),
    )


@dataclass(frozen=True)
class RunViewRunInstance:
    """Per-instance detail inside one run."""

    instance_id: str
    status: str
    after: list[str] = field(default_factory=list)
    submission_required: bool = False
    obligation_count: int = 0
    payload_summary: dict[str, str] = field(default_factory=dict)
    evidence: list[_RunViewEvidence] = field(default_factory=list)
    attempts: list[_RunViewAttempt] = field(default_factory=list)
    operations: list[_RunViewOperation] = field(default_factory=list)
    diagnostics: list[_RunViewInstanceDiagnostic] = field(default_factory=list)
    warnings: int = 0
    protocol_files: list[str] = field(default_factory=list)
    provider_ref: str | None = None
    selection_reason: str | None = None
    waiting_on: str | None = None
    blocked_by: str | None = None
    trigger_kind: str | None = None
    attempt: int | None = None
    max_attempts: int | None = None
    op: str | None = None
    headline: _RunViewEvidence | None = None
    refusal_reason: str | None = None
    deferral: _RunViewDeferral | None = None
    failure_reason: str | None = None


def _run_view_run_instance_from_dict(data: dict[str, Any]) -> RunViewRunInstance:
    headline = data.get("headline")
    deferral = data.get("deferral")
    payload_summary = data.get("payload_summary")
    summary: dict[str, str] = {}
    if isinstance(payload_summary, dict):
        summary = {str(key): str(item) for key, item in payload_summary.items()}
    return RunViewRunInstance(
        instance_id=_coerced_str(data.get("instance_id")),
        status=_coerced_str(data.get("status")),
        after=_str_list(data.get("after")),
        submission_required=_coerced_bool(data.get("submission_required")),
        obligation_count=_coerced_int(data.get("obligation_count"), 0),
        payload_summary=summary,
        evidence=[
            _run_view_evidence_from_dict(dict(item))
            for item in data.get("evidence", [])
            if isinstance(item, dict)
        ],
        attempts=[
            _run_view_attempt_from_dict(dict(item))
            for item in data.get("attempts", [])
            if isinstance(item, dict)
        ],
        operations=[
            _run_view_operation_from_dict(dict(item))
            for item in data.get("operations", [])
            if isinstance(item, dict)
        ],
        diagnostics=[
            _run_view_instance_diagnostic_from_dict(dict(item))
            for item in data.get("diagnostics", [])
            if isinstance(item, dict)
        ],
        warnings=_coerced_int(data.get("warnings"), 0),
        protocol_files=_str_list(data.get("protocol_files")),
        provider_ref=_optional_str(data.get("provider_ref")),
        selection_reason=_optional_str(data.get("selection_reason")),
        waiting_on=_optional_str(data.get("waiting_on")),
        blocked_by=_optional_str(data.get("blocked_by")),
        trigger_kind=_optional_str(data.get("trigger_kind")),
        attempt=_optional_int(data.get("attempt")),
        max_attempts=_optional_int(data.get("max_attempts")),
        op=_optional_str(data.get("op")),
        headline=(
            _run_view_evidence_from_dict(dict(headline))
            if isinstance(headline, dict)
            else None
        ),
        refusal_reason=_optional_str(data.get("refusal_reason")),
        deferral=(
            _run_view_deferral_from_dict(dict(deferral))
            if isinstance(deferral, dict)
            else None
        ),
        failure_reason=_optional_str(data.get("failure_reason")),
    )


@dataclass(frozen=True)
class RunViewRun:
    """One run's projected view."""

    run_id: str
    number: int
    label: str
    kind: str
    disposition: str
    cycles: int = 0
    earlier_segments: int = 0
    reactivated: bool = False
    declarations: list[_RunViewDeclaration] = field(default_factory=list)
    drift: list[_RunViewDrift] = field(default_factory=list)
    diagnostics: list[FinalizerDiagnosticWire] = field(default_factory=list)
    instances: list[RunViewRunInstance] = field(default_factory=list)
    reason: str | None = None
    plan_digest: str | None = None
    result_status: str | None = None
    recovery_turn: _RunViewRecoveryTurn | None = None


def _run_view_run_from_dict(data: dict[str, Any]) -> RunViewRun:
    recovery_turn = data.get("recovery_turn")
    return RunViewRun(
        run_id=_coerced_str(data.get("run_id")),
        number=_coerced_int(data.get("number"), 0),
        label=_coerced_str(data.get("label")),
        kind=_coerced_str(data.get("kind")),
        disposition=_coerced_str(data.get("disposition")),
        cycles=_coerced_int(data.get("cycles"), 0),
        earlier_segments=_coerced_int(data.get("earlier_segments"), 0),
        reactivated=_coerced_bool(data.get("reactivated")),
        declarations=[
            _run_view_declaration_from_dict(dict(item))
            for item in data.get("declarations", [])
            if isinstance(item, dict)
        ],
        drift=[
            _run_view_drift_from_dict(dict(item))
            for item in data.get("drift", [])
            if isinstance(item, dict)
        ],
        diagnostics=[
            finalizer_diagnostic_from_dict(dict(item))
            for item in data.get("diagnostics", [])
            if isinstance(item, dict)
        ],
        instances=[
            _run_view_run_instance_from_dict(dict(item))
            for item in data.get("instances", [])
            if isinstance(item, dict)
        ],
        reason=_optional_str(data.get("reason")),
        plan_digest=_optional_str(data.get("plan_digest")),
        result_status=_optional_str(data.get("result_status")),
        recovery_turn=(
            _run_view_recovery_turn_from_dict(dict(recovery_turn))
            if isinstance(recovery_turn, dict)
            else None
        ),
    )


@dataclass(frozen=True)
class FinalizerNodeView:
    """The projected node view: one run for a lone turn, every member run."""

    schema_version: int
    status: str
    glyph: str
    run_level_trouble: bool = False
    instances: list[_RunViewNodeInstance] = field(default_factory=list)
    unselected: list[_RunViewUnselected] = field(default_factory=list)
    runs: list[RunViewRun] = field(default_factory=list)
    attention_instance_id: str | None = None


def finalizer_node_view_from_dict(data: dict[str, Any]) -> FinalizerNodeView:
    """Coerce a raw projection payload tolerantly (plan section 3.4).

    Missing keys fall back to neutral defaults and unknown values survive
    as strings, so a future projection shape still renders instead of
    raising. Only a non-mapping payload raises :class:`ValueError`.
    """
    if not isinstance(data, dict):
        raise ValueError("node view payload must be a mapping")
    return FinalizerNodeView(
        schema_version=_coerced_int(data.get("schema_version"), 0),
        status=_coerced_str(data.get("status")),
        glyph=_coerced_str(data.get("glyph")),
        run_level_trouble=_coerced_bool(data.get("run_level_trouble")),
        instances=[
            _run_view_node_instance_from_dict(dict(item))
            for item in data.get("instances", [])
            if isinstance(item, dict)
        ],
        unselected=[
            _run_view_unselected_from_dict(dict(item))
            for item in data.get("unselected", [])
            if isinstance(item, dict)
        ],
        runs=[
            _run_view_run_from_dict(dict(item))
            for item in data.get("runs", [])
            if isinstance(item, dict)
        ],
        attention_instance_id=_optional_str(data.get("attention_instance_id")),
    )


def project_finalizer_node_view(request: dict[str, Any]) -> FinalizerNodeView:
    """Project one finalizer node view from a collected request mapping."""
    binding = require_rust_binding("project_finalizer_node_view")
    payload = binding(dict(request))
    return finalizer_node_view_from_dict(dict(payload))


__all__ = [
    "RUN_VIEW_TAIL_LINES_DEFAULT",
    "RUN_VIEW_WIRE_SCHEMA_VERSION",
    "FinalizerNodeView",
    "RunViewRun",
    "RunViewRunInstance",
    "finalizer_node_view_from_dict",
    "project_finalizer_node_view",
]
