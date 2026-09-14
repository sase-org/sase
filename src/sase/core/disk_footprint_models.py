"""Data models for SASE disk-footprint inventory and reaping."""

from __future__ import annotations

from dataclasses import asdict, dataclass


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

    @property
    def total_bytes(self) -> int:
        return sum(row.size_bytes for row in self.rows)

    def to_json_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "rows": [row.to_json_dict() for row in self.rows],
            "stray_scan_truncated": self.stray_scan_truncated,
            "stray_scan_visited": self.stray_scan_visited,
            "scan_diagnostics": list(self.scan_diagnostics),
            "total_bytes": self.total_bytes,
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

    def to_json_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["command"] = list(self.command)
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

    def to_json_dict(self) -> dict[str, object]:
        return {
            "apply": self.apply,
            "project": self.project,
            "changed": self.changed,
            "reclaimed_bytes": self.reclaimed_bytes,
            "steps": [step.to_json_dict() for step in self.steps],
        }


__all__ = [
    "DiskFootprintReport",
    "DiskFootprintRow",
    "DiskReapResult",
    "DiskReapStep",
]
