"""Cutover-aware validation for plans entering committed SDD storage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from sase.sdd.plan_tiers import normalize_plan_tier
from sase.sdd.plan_validate import (
    PlanDiagnosticSeverity,
    validate_plan,
)

PLAN_SCHEMA_CUTOVER_YYYYMM = "202608"

_YYYYMM_RE = re.compile(r"^\d{6}$")


@dataclass(frozen=True)
class CommittedPlanIssue:
    """One issue found at a committed-plan enforcement boundary."""

    path: str
    severity: str
    code: str
    message: str
    field_path: str = ""
    line: int | None = None

    @property
    def is_error(self) -> bool:
        """Return whether this issue must block the write or sweep."""
        return self.severity == PlanDiagnosticSeverity.ERROR.value

    def format(self) -> str:
        """Render the stable location-bearing diagnostic form."""
        location = f"{self.path}:{self.line}" if self.line is not None else self.path
        return f"{location}: {self.severity} [{self.code}] {self.message}"


class _CommittedPlanValidationError(ValueError):
    """A plan failed validation before entering committed storage."""

    def __init__(self, issues: tuple[CommittedPlanIssue, ...]) -> None:
        self.issues = issues
        details = "\n".join(issue.format() for issue in issues if issue.is_error)
        super().__init__(f"committed plan validation failed:\n{details}")


def requires_full_plan_schema(yyyymm: str) -> bool:
    """Return whether ``yyyymm`` is at or after the schema cutover."""
    if _YYYYMM_RE.fullmatch(yyyymm) is None:
        raise ValueError(f"invalid plan month {yyyymm!r}; expected YYYYMM")
    return yyyymm >= PLAN_SCHEMA_CUTOVER_YYYYMM


def inspect_committed_plan(
    content: str,
    *,
    tier: object,
    path: str | Path,
    yyyymm: str,
) -> tuple[CommittedPlanIssue, ...]:
    """Return issues for one plan at its destination month.

    Pre-cutover files retain the historical explicit-tier check. Files at or
    after the cutover use the authoritative Rust-backed schema validator.
    """
    display_path = str(path)
    normalized_tier = normalize_plan_tier(tier)
    if not requires_full_plan_schema(yyyymm):
        if normalized_tier is None:
            return (
                CommittedPlanIssue(
                    path=display_path,
                    severity="error",
                    code="plan-tier",
                    message="'tier' must be either 'tale' or 'epic'",
                    field_path="tier",
                ),
            )
        return ()

    # An invalid authored tier cannot select its own schema. Validate against
    # tale as a deterministic fallback; the tier diagnostic still makes the
    # document fail, while the engine can report its other problems in one run.
    validation = validate_plan(content, normalized_tier or "tale")
    return tuple(
        CommittedPlanIssue(
            path=display_path,
            severity=diagnostic.severity.value,
            code=diagnostic.code,
            message=diagnostic.message,
            field_path=diagnostic.field_path,
            line=diagnostic.line,
        )
        for diagnostic in validation.diagnostics
    )


def validate_plan_for_commit(
    content: str,
    *,
    tier: object,
    path: str | Path,
    yyyymm: str,
) -> None:
    """Raise when ``content`` cannot be committed at ``yyyymm``."""
    issues = inspect_committed_plan(
        content,
        tier=tier,
        path=path,
        yyyymm=yyyymm,
    )
    if any(issue.is_error for issue in issues):
        raise _CommittedPlanValidationError(issues)


__all__ = [
    "PLAN_SCHEMA_CUTOVER_YYYYMM",
    "CommittedPlanIssue",
    "inspect_committed_plan",
    "requires_full_plan_schema",
    "validate_plan_for_commit",
]
