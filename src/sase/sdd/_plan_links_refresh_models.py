"""Result models for tree-wide plan provenance reconciliation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

RefreshSeverity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class PlanLinksRefreshIssue:
    """One actionable refresh diagnostic."""

    severity: RefreshSeverity
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class PlanLinksRefreshAction:
    """One plan whose projected header differs from durable state."""

    path: str
    plan: str
    parent_migrated: bool
    agents: int
    commits: int


@dataclass(frozen=True, slots=True)
class PlanLinksRefreshReport:
    """Complete dry-run or write result for one refresh invocation."""

    root: Path
    write: bool
    plan: str | None
    scanned: int
    actions: tuple[PlanLinksRefreshAction, ...]
    issues: tuple[PlanLinksRefreshIssue, ...]
    changed_files: tuple[str, ...]
    committed: bool

    @property
    def errors(self) -> tuple[PlanLinksRefreshIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[PlanLinksRefreshIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors


def plan_links_refresh_to_json(report: PlanLinksRefreshReport) -> dict[str, Any]:
    """Return the stable CLI JSON envelope for a refresh report."""

    return {
        "root": str(report.root),
        "write": report.write,
        "plan": report.plan,
        "ok": report.ok,
        "scanned": report.scanned,
        "would_change": len(report.actions),
        "actions": [asdict(action) for action in report.actions],
        "warnings": [asdict(issue) for issue in report.warnings],
        "errors": [asdict(issue) for issue in report.errors],
        "changed_files": list(report.changed_files),
        "committed": report.committed,
    }


__all__ = [
    "PlanLinksRefreshAction",
    "PlanLinksRefreshIssue",
    "PlanLinksRefreshReport",
    "plan_links_refresh_to_json",
]
