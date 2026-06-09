"""Shared diagnostic report models for SASE doctor-style commands."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

CheckStatus = Literal["OK", "WARN", "ERROR", "SKIP"]

SCHEMA_VERSION = 1
COMMAND_NAME = "doctor"

_STATUS_ORDER: tuple[CheckStatus, ...] = ("OK", "WARN", "ERROR", "SKIP")
_VALID_STATUSES = frozenset(_STATUS_ORDER)
_SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|token|secret|password|passwd|credential|authorization|cookie)"
)
_ASSIGNMENT_SECRET_RE = re.compile(
    r"(?i)\b([A-Z0-9_.-]*(?:API[_-]?KEY|TOKEN|SECRET|PASSWORD|PASSWD|"
    r"CREDENTIAL|COOKIE)[A-Z0-9_.-]*)\s*([:=])\s*([\"']?)([^\"'\s,;]+)"
)
_AUTH_HEADER_RE = re.compile(
    r"(?i)\b(authorization\s*[:=]\s*)(bearer|basic)\s+([A-Za-z0-9._~+/=-]+)"
)


def _utc_timestamp() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class DiagnosticCheck:
    """One bounded diagnostic finding."""

    id: str
    group: str
    status: CheckStatus
    title: str
    summary: str
    details: Sequence[str] = ()
    next_steps: Sequence[str] = ()
    data: Mapping[str, Any] = field(default_factory=dict)
    duration_ms: int = 0

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("DiagnosticCheck.id must be non-empty")
        if not self.group:
            raise ValueError("DiagnosticCheck.group must be non-empty")
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"unsupported diagnostic status: {self.status!r}")
        if not self.title:
            raise ValueError("DiagnosticCheck.title must be non-empty")

        object.__setattr__(self, "details", tuple(str(item) for item in self.details))
        object.__setattr__(
            self, "next_steps", tuple(str(item) for item in self.next_steps)
        )
        object.__setattr__(self, "data", _freeze_mapping(dict(self.data)))
        object.__setattr__(self, "duration_ms", max(int(self.duration_ms), 0))

    def with_duration(self, duration_ms: int) -> DiagnosticCheck:
        """Return this check with a non-negative duration."""
        return replace(self, duration_ms=max(int(duration_ms), 0))

    def to_dict(self) -> dict[str, Any]:
        """Serialize this check to redacted JSON-compatible primitives."""
        return diagnostic_check_to_dict(self)


@dataclass(frozen=True)
class DiagnosticReport:
    """Complete diagnostic report for the top-level doctor contract."""

    checks: Sequence[DiagnosticCheck]
    generated_at: str = field(default_factory=_utc_timestamp)
    cwd: str = field(default_factory=lambda: str(Path.cwd()))
    project: str | None = None
    sase_home: str = field(default_factory=lambda: str(Path.home() / ".sase"))
    deep: bool = False
    strict: bool = False
    selected_checks: Sequence[str] = ()
    schema_version: int = SCHEMA_VERSION
    command: str = COMMAND_NAME

    def __post_init__(self) -> None:
        object.__setattr__(self, "checks", tuple(self.checks))
        object.__setattr__(
            self, "selected_checks", tuple(str(item) for item in self.selected_checks)
        )

    @property
    def status(self) -> CheckStatus:
        """Aggregate report status."""
        return aggregate_check_status(tuple(self.checks))

    @property
    def counts(self) -> dict[CheckStatus, int]:
        """Count checks by status in stable JSON order."""
        return count_check_statuses(tuple(self.checks))

    def exit_code(self, *, strict: bool | None = None) -> int:
        """Return the process exit code implied by this report."""
        return diagnostic_exit_code(
            self.status, strict=self.strict if strict is None else strict
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize this report to redacted JSON-compatible primitives."""
        return diagnostic_report_to_dict(self)


def aggregate_check_status(checks: Sequence[DiagnosticCheck]) -> CheckStatus:
    """Aggregate individual check statuses into one report status."""
    statuses = {check.status for check in checks}
    if "ERROR" in statuses:
        return "ERROR"
    if "WARN" in statuses:
        return "WARN"
    if not statuses or statuses == {"SKIP"}:
        return "SKIP"
    return "OK"


def count_check_statuses(checks: Sequence[DiagnosticCheck]) -> dict[CheckStatus, int]:
    """Return status counts with deterministic key order."""
    return {
        status: sum(1 for check in checks if check.status == status)
        for status in _STATUS_ORDER
    }


def diagnostic_exit_code(status: CheckStatus, *, strict: bool = False) -> int:
    """Return doctor-style exit code for *status*."""
    if status == "ERROR":
        return 1
    if strict and status == "WARN":
        return 1
    return 0


def diagnostic_check_to_dict(check: DiagnosticCheck) -> dict[str, Any]:
    """Serialize a diagnostic check using the stable JSON contract."""
    return {
        "id": check.id,
        "group": check.group,
        "status": check.status,
        "title": redact_string(check.title),
        "summary": redact_string(check.summary),
        "details": [redact_string(detail) for detail in check.details],
        "next_steps": [redact_string(step) for step in check.next_steps],
        "data": redact_value(check.data),
        "duration_ms": check.duration_ms,
    }


def diagnostic_report_to_dict(report: DiagnosticReport) -> dict[str, Any]:
    """Serialize a diagnostic report using the stable JSON contract."""
    return {
        "schema_version": report.schema_version,
        "command": report.command,
        "status": report.status,
        "generated_at": report.generated_at,
        "cwd": report.cwd,
        "project": report.project,
        "sase_home": report.sase_home,
        "deep": report.deep,
        "strict": report.strict,
        "selected_checks": list(report.selected_checks),
        "counts": report.counts,
        "checks": [diagnostic_check_to_dict(check) for check in report.checks],
    }


def redact_string(value: str) -> str:
    """Redact secret-looking values from a diagnostic string."""
    value = _AUTH_HEADER_RE.sub(r"\1\2 [REDACTED]", value)
    return _ASSIGNMENT_SECRET_RE.sub(r"\1\2\3[REDACTED]", value)


def redact_value(value: Any, *, key: str | None = None) -> Any:
    """Return a JSON-compatible value with secret-looking fields redacted."""
    if key and _SECRET_KEY_RE.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        return {
            str(child_key): redact_value(child_value, key=str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [redact_value(item) for item in value]
    return value


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {str(key): _freeze_value(item) for key, item in value.items()}
    )


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping({str(key): item for key, item in value.items()})
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(_freeze_value(item) for item in value)
    return value
