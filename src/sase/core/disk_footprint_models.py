"""Data models for SASE disk-footprint inventory and reaping."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

DISK_COVERAGE_COMPLETE = "complete"
DISK_COVERAGE_PARTIAL = "partial"
DISK_COVERAGE_UNRESOLVED = "unresolved"


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
    reclaimed_bytes: int = 0
    changed: bool = False
    command: tuple[str, ...] = ()
    exit_code: int | None = None
    output: str = ""
    details: Mapping[str, Any] = field(default_factory=dict)

    @property
    def failed(self) -> bool:
        return self.mode in {"blocked", "error"} or (
            self.exit_code is not None and self.exit_code != 0
        )

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
        return sum(step.reclaimed_bytes for step in self.steps)

    @property
    def changed(self) -> bool:
        return any(step.changed for step in self.steps)

    @property
    def failed(self) -> bool:
        return any(step.failed for step in self.steps)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "apply": self.apply,
            "project": self.project,
            "changed": self.changed,
            "failed": self.failed,
            "reclaimed_bytes": self.reclaimed_bytes,
            "steps": [step.to_json_dict() for step in self.steps],
        }


__all__ = [
    "DISK_COVERAGE_COMPLETE",
    "DISK_COVERAGE_PARTIAL",
    "DISK_COVERAGE_UNRESOLVED",
    "DiskFootprintReport",
    "DiskFootprintRow",
    "DiskReapResult",
    "DiskReapStep",
]
