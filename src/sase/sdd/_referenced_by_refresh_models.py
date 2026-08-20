"""Result models shared by Referenced By refresh implementations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_RefreshSeverity = Literal["error", "warning"]


@dataclass(frozen=True, slots=True)
class ReferencedByRefreshIssue:
    """One actionable Referenced By refresh diagnostic."""

    severity: _RefreshSeverity
    code: str
    path: str
    message: str


@dataclass(frozen=True, slots=True)
class ReferencedByRefreshAction:
    """One artifact document whose managed projection differs."""

    path: str
    artifact_id: str
    rows: int


@dataclass(frozen=True, slots=True)
class ReferencedByRefreshReport:
    """Complete dry-run or write result for one refresh invocation."""

    root: Path
    role: str
    write: bool
    scanned: int
    actions: tuple[ReferencedByRefreshAction, ...]
    issues: tuple[ReferencedByRefreshIssue, ...]
    changed_files: tuple[str, ...]
    committed: bool

    @property
    def errors(self) -> tuple[ReferencedByRefreshIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def warnings(self) -> tuple[ReferencedByRefreshIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors
