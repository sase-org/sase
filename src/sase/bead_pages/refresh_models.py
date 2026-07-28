"""Result models for tree-wide bead-page reconciliation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

BeadPagesRefreshSeverity = Literal["error", "warning"]
BeadPagesRefreshChange = Literal["create", "remove", "update"]


@dataclass(frozen=True, slots=True)
class BeadPagesRefreshIssue:
    """One actionable refresh diagnostic."""

    severity: BeadPagesRefreshSeverity
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class BeadPagesRefreshAction:
    """One generated page whose desired bytes differ from disk."""

    path: str
    change: BeadPagesRefreshChange
    bead_id: str | None = None


@dataclass(frozen=True, slots=True)
class BeadPagesRefreshReport:
    """Complete dry-run or write result for one refresh invocation."""

    root: Path
    write: bool
    bead: str | None
    scanned: int
    lineages: int
    actions: tuple[BeadPagesRefreshAction, ...]
    issues: tuple[BeadPagesRefreshIssue, ...]
    changed_files: tuple[str, ...]
    removed_files: tuple[str, ...]
    committed: bool

    @property
    def errors(self) -> tuple[BeadPagesRefreshIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[BeadPagesRefreshIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors


def bead_pages_refresh_to_json(report: BeadPagesRefreshReport) -> dict[str, Any]:
    """Return the stable CLI JSON envelope for a refresh report."""

    return {
        "root": str(report.root),
        "write": report.write,
        "bead": report.bead,
        "ok": report.ok,
        "scanned": report.scanned,
        "lineages": report.lineages,
        "would_change": len(report.actions),
        "actions": [asdict(action) for action in report.actions],
        "warnings": [asdict(issue) for issue in report.warnings],
        "errors": [asdict(issue) for issue in report.errors],
        "changed_files": list(report.changed_files),
        "removed_files": list(report.removed_files),
        "committed": report.committed,
    }


__all__ = [
    "BeadPagesRefreshAction",
    "BeadPagesRefreshIssue",
    "BeadPagesRefreshReport",
    "bead_pages_refresh_to_json",
]
