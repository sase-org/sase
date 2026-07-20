"""Typed Python adapter for strict Rust-backed plan validation.

The authoritative frontmatter schema and every content-validation rule live in
``sase-core``.  This module only rehydrates the JSON-shaped binding payloads
into frozen Python records for CLI and workflow callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding

PLAN_WIRE_SCHEMA_VERSION = 2


class PlanDiagnosticSeverity(StrEnum):
    """Severity values emitted by the plan validator."""

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class PlanDiagnostic:
    """One actionable plan-validation problem."""

    severity: PlanDiagnosticSeverity
    code: str
    field_path: str
    message: str
    line: int | None

    @property
    def is_error(self) -> bool:
        """Return whether this diagnostic makes validation fail."""
        return self.severity is PlanDiagnosticSeverity.ERROR


@dataclass(frozen=True)
class PlanFrontmatterFieldSpec:
    """Authoritative metadata for one accepted frontmatter field."""

    name: str
    field_type: str
    required: bool
    description: str
    example: Any


@dataclass(frozen=True)
class ValidatedPlanPhase:
    """Normalized epic-phase data returned by the Rust validator."""

    id: str
    title: str
    depends_on: tuple[str, ...]
    description: str | None
    size: str
    model: str | None


@dataclass(frozen=True)
class _ValidatedPlan:
    """Normalized plan data available only after error-free validation."""

    tier: str
    goal: str
    model: str | None
    title: str
    phases: tuple[ValidatedPlanPhase, ...]
    changespec: str | None
    bug_id: int | None
    parent_bead: str | None
    bead: str | None
    parent: str | None


@dataclass(frozen=True)
class PlanValidationResult:
    """Complete strict-validation result from ``sase-core``."""

    schema_version: int
    ok: bool
    diagnostics: tuple[PlanDiagnostic, ...]
    plan: _ValidatedPlan | None


def validate_plan(
    content: str,
    tier: str,
    *,
    mode: str = "authoring",
) -> PlanValidationResult:
    """Validate one complete Markdown plan against ``tier``.

    ``tier`` must be ``"tale"`` or ``"epic"``.  Invalid caller tiers are
    rejected by the binding as usage errors; document problems are returned as
    diagnostics so callers receive every problem in one pass.

    ``mode`` defaults to strict authoring validation. Launch consumers may pass
    ``"launch"`` to normalize a missing legacy phase size to ``"small"`` while
    retaining the validator's warning.
    """
    binding = require_rust_binding("plan_validate")
    return _validation_result_from_dict(binding(content, tier, mode))


def validate_plan_file(
    path: Path,
    tier: str,
    *,
    mode: str = "authoring",
) -> PlanValidationResult:
    """Read and validate one UTF-8 plan file against ``tier``.

    File-system and UTF-8 failures use the same diagnostic envelope as
    content-validation failures so approval gates and the CLI can render one
    consistent, actionable result.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        detail = exc.strerror or str(exc)
        return _file_error("file-unreadable", f"cannot read plan file: {detail}")

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = raw[: exc.start].count(b"\n") + 1
        return _file_error(
            "utf8-invalid",
            "plan file is not valid UTF-8",
            line=line,
        )
    return validate_plan(content, tier, mode=mode)


def plan_frontmatter_schema(tier: str) -> tuple[PlanFrontmatterFieldSpec, ...]:
    """Return the ordered authoritative field specification for ``tier``."""
    binding = require_rust_binding("plan_frontmatter_schema")
    return tuple(_field_spec_from_dict(item) for item in binding(tier))


def _validation_result_from_dict(payload: dict[str, Any]) -> PlanValidationResult:
    schema_version = int(payload["schema_version"])
    if schema_version != PLAN_WIRE_SCHEMA_VERSION:
        raise ValueError(
            "unsupported plan validation wire schema version "
            f"{schema_version}; expected {PLAN_WIRE_SCHEMA_VERSION}"
        )
    plan_payload = payload.get("plan")
    return PlanValidationResult(
        schema_version=schema_version,
        ok=bool(payload["ok"]),
        diagnostics=tuple(
            _diagnostic_from_dict(item) for item in payload["diagnostics"]
        ),
        plan=(
            _validated_plan_from_dict(plan_payload)
            if isinstance(plan_payload, dict)
            else None
        ),
    )


def _diagnostic_from_dict(payload: dict[str, Any]) -> PlanDiagnostic:
    line = payload.get("line")
    return PlanDiagnostic(
        severity=PlanDiagnosticSeverity(payload["severity"]),
        code=str(payload["code"]),
        field_path=str(payload["field_path"]),
        message=str(payload["message"]),
        line=int(line) if line is not None else None,
    )


def _field_spec_from_dict(payload: dict[str, Any]) -> PlanFrontmatterFieldSpec:
    return PlanFrontmatterFieldSpec(
        name=str(payload["name"]),
        field_type=str(payload["type"]),
        required=bool(payload["required"]),
        description=str(payload["description"]),
        example=payload["example"],
    )


def _validated_plan_from_dict(payload: dict[str, Any]) -> _ValidatedPlan:
    return _ValidatedPlan(
        tier=str(payload["tier"]),
        goal=str(payload["goal"]),
        model=_optional_str(payload.get("model")),
        title=str(payload["title"]),
        phases=tuple(_validated_phase_from_dict(item) for item in payload["phases"]),
        changespec=_optional_str(payload.get("changespec")),
        bug_id=(int(payload["bug_id"]) if payload.get("bug_id") is not None else None),
        parent_bead=_optional_str(payload.get("parent_bead")),
        bead=_optional_str(payload.get("bead")),
        parent=_optional_str(payload.get("parent")),
    )


def _validated_phase_from_dict(payload: dict[str, Any]) -> ValidatedPlanPhase:
    return ValidatedPlanPhase(
        id=str(payload["id"]),
        title=str(payload["title"]),
        depends_on=tuple(str(item) for item in payload["depends_on"]),
        description=_optional_str(payload.get("description")),
        size=str(payload["size"]),
        model=_optional_str(payload.get("model")),
    )


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _file_error(
    code: str, message: str, *, line: int | None = None
) -> PlanValidationResult:
    return PlanValidationResult(
        schema_version=PLAN_WIRE_SCHEMA_VERSION,
        ok=False,
        diagnostics=(
            PlanDiagnostic(
                severity=PlanDiagnosticSeverity.ERROR,
                code=code,
                field_path="",
                message=message,
                line=line,
            ),
        ),
        plan=None,
    )


__all__ = [
    "PLAN_WIRE_SCHEMA_VERSION",
    "PlanDiagnostic",
    "PlanDiagnosticSeverity",
    "PlanFrontmatterFieldSpec",
    "PlanValidationResult",
    "ValidatedPlanPhase",
    "plan_frontmatter_schema",
    "validate_plan",
    "validate_plan_file",
]
