"""Data models for SASE disk-footprint inventory and reaping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

DISK_COVERAGE_COMPLETE = "complete"
DISK_COVERAGE_PARTIAL = "partial"
DISK_COVERAGE_UNRESOLVED = "unresolved"
DISK_CLEANUP_STATUS_SUCCESS = "success"
DISK_CLEANUP_STATUS_FAILED = "failed"
DISK_CLEANUP_STATUS_BLOCKED = "blocked"
DISK_CLEANUP_STATUS_INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class DiskFootprintRow:
    """One path-sized row in ``sase disk list``."""

    section: str
    name: str
    path: str
    size_bytes: int
    owner: str
    horizon: str
    status: str = "owned"
    reclaim: str | None = None
    physical_path: str | None = None
    exclusive_size_bytes: int | None = None
    coverage: str = DISK_COVERAGE_COMPLETE
    diagnostics: tuple[str, ...] = ()
    overlap_parent_path: str | None = None
    overlap_paths: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class DiskFootprintReport:
    """Rows plus scan diagnostics for one footprint inventory."""

    rows: tuple[DiskFootprintRow, ...]
    generated_at: str
    stray_scan_truncated: bool = False
    stray_scan_visited: int = 0
    scan_diagnostics: tuple[str, ...] = ()
    physical_total_bytes: int | None = None
    logical_total_bytes: int | None = None
    owned_total_bytes: int | None = None
    unowned_total_bytes: int | None = None
    coverage_status: str = DISK_COVERAGE_COMPLETE
    unresolved_owner_coverage: tuple[str, ...] = ()

    @property
    def total_bytes(self) -> int:
        if self.physical_total_bytes is not None:
            return self.physical_total_bytes
        return sum(
            row.exclusive_size_bytes
            if row.exclusive_size_bytes is not None
            else row.size_bytes
            for row in self.rows
        )

    def to_json_dict(self) -> dict[str, object]:
        logical_total = (
            self.logical_total_bytes
            if self.logical_total_bytes is not None
            else sum(row.size_bytes for row in self.rows)
        )
        return {
            "generated_at": self.generated_at,
            "rows": [row.to_json_dict() for row in self.rows],
            "stray_scan_truncated": self.stray_scan_truncated,
            "stray_scan_visited": self.stray_scan_visited,
            "scan_diagnostics": list(self.scan_diagnostics),
            "total_bytes": self.total_bytes,
            "physical_total_bytes": self.total_bytes,
            "logical_total_bytes": logical_total,
            "owned_total_bytes": (
                self.owned_total_bytes
                if self.owned_total_bytes is not None
                else self.total_bytes
            ),
            "unowned_total_bytes": (
                self.unowned_total_bytes if self.unowned_total_bytes is not None else 0
            ),
            "coverage_status": self.coverage_status,
            "unresolved_owner_coverage": list(self.unresolved_owner_coverage),
        }


@dataclass(frozen=True)
class DiskReapStep:
    """One owner delegated to by ``sase disk reap``."""

    owner: str
    mode: str
    summary: str
    reclaimed_bytes: int | None = 0
    changed: bool = False
    command: tuple[str, ...] = ()
    exit_code: int | None = None
    output: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)
    byte_accounting_complete: bool = True
    owner_error: str | None = None
    invalid_result: str | None = None
    blocked_reason: str | None = None
    required_observation_unavailable: bool = False
    incomplete_reason: str | None = None
    protective_skip: str | None = None
    capped: bool = False

    @property
    def failed(self) -> bool:
        return (
            self.mode in {"blocked", "error"}
            or bool(self.owner_error)
            or bool(self.invalid_result)
            or bool(self.blocked_reason)
            or self.required_observation_unavailable
            or bool(self.incomplete_reason)
            or (self.exit_code is not None and self.exit_code != 0)
        )

    def cleanup_owner_wire(self) -> dict[str, object]:
        blocked_reason = self.blocked_reason
        owner_error = self.owner_error
        invalid_result = self.invalid_result
        if self.mode == "blocked" and blocked_reason is None:
            blocked_reason = self.summary
        if self.mode == "error" and owner_error is None:
            owner_error = self.summary
        if self.mode == "invalid" and invalid_result is None:
            invalid_result = self.summary
        return {
            "owner": self.owner,
            "required": True,
            "changed": self.changed,
            "reclaimed_bytes": self.reclaimed_bytes,
            "byte_accounting_complete": self.byte_accounting_complete,
            "owner_error": owner_error,
            "exit_code": self.exit_code,
            "invalid_result": invalid_result,
            "blocked_reason": blocked_reason,
            "required_observation_unavailable": (self.required_observation_unavailable),
            "incomplete_reason": self.incomplete_reason,
            "protective_skip": self.protective_skip,
            "capped": self.capped,
        }

    def to_json_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["command"] = list(self.command)
        payload["failed"] = self.failed
        return payload


@dataclass(frozen=True)
class DiskReapResult:
    """Aggregate outcome for ``sase disk reap``."""

    apply: bool
    project: str | None
    steps: tuple[DiskReapStep, ...]

    @property
    def reclaimed_bytes(self) -> int:
        return sum(step.reclaimed_bytes or 0 for step in self.steps)

    @property
    def changed(self) -> bool:
        return bool(self.cleanup_outcome["changed"])

    @property
    def failed(self) -> bool:
        return not bool(self.cleanup_outcome["success"])

    @property
    def cleanup_outcome(self) -> Mapping[str, Any]:
        return _normalize_disk_cleanup_outcome(
            step.cleanup_owner_wire() for step in self.steps
        )

    @property
    def byte_accounting_complete(self) -> bool:
        return bool(self.cleanup_outcome["byte_accounting_complete"])

    def to_json_dict(self) -> dict[str, object]:
        outcome = dict(self.cleanup_outcome)
        return {
            "apply": self.apply,
            "project": self.project,
            "changed": self.changed,
            "failed": self.failed,
            "status": outcome["status"],
            "reclaimed_bytes": self.reclaimed_bytes,
            "byte_accounting_complete": outcome["byte_accounting_complete"],
            "cleanup_outcome": outcome,
            "steps": [step.to_json_dict() for step in self.steps],
        }


def _normalize_disk_cleanup_outcome(
    owners: Any,
) -> Mapping[str, Any]:
    """Normalize owner cleanup observations through the Rust core contract."""

    from sase.core.rust import require_rust_binding

    schema_version = int(
        require_rust_binding("disk_cleanup_outcome_wire_schema_version")()
    )
    normalize = require_rust_binding("normalize_disk_cleanup_outcome")
    return normalize(
        {
            "schema_version": schema_version,
            "owners": [dict(owner) for owner in owners],
        }
    )


__all__ = [
    "DISK_CLEANUP_STATUS_BLOCKED",
    "DISK_CLEANUP_STATUS_FAILED",
    "DISK_CLEANUP_STATUS_INCOMPLETE",
    "DISK_CLEANUP_STATUS_SUCCESS",
    "DISK_COVERAGE_COMPLETE",
    "DISK_COVERAGE_PARTIAL",
    "DISK_COVERAGE_UNRESOLVED",
    "DiskFootprintReport",
    "DiskFootprintRow",
    "DiskReapResult",
    "DiskReapStep",
]
