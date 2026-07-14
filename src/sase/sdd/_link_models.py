"""Models and JSON serialization for SDD link validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class SddIssue:
    severity: Severity
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class SddFile:
    path: Path
    relpath: str
    kind: str
    yyyymm: str
    name: str
    frontmatter: dict[str, Any]
    had_frontmatter: bool
    parse_error: str | None = None


@dataclass(frozen=True)
class SddValidation:
    root: Path
    files: list[SddFile]
    issues: list[SddIssue]

    @property
    def errors(self) -> list[SddIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]

    @property
    def warnings(self) -> list[SddIssue]:
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


@dataclass(frozen=True)
class RepairAction:
    path: str
    field: str
    old: str | None
    new: str


@dataclass(frozen=True)
class RepairReport:
    root: Path
    write: bool
    actions: list[RepairAction]
    issues: list[SddIssue]
    changed_files: list[str]


def validation_to_json(validation: SddValidation) -> dict[str, Any]:
    return {
        "root": str(validation.root),
        "ok": validation.ok,
        "files": [_file_to_json(file) for file in validation.files],
        "errors": [asdict(issue) for issue in validation.errors],
        "warnings": [asdict(issue) for issue in validation.warnings],
    }


def repair_to_json(report: RepairReport) -> dict[str, Any]:
    return {
        "root": str(report.root),
        "write": report.write,
        "actions": [asdict(action) for action in report.actions],
        "warnings": [
            asdict(issue) for issue in report.issues if issue.severity == "warning"
        ],
        "errors": [
            asdict(issue) for issue in report.issues if issue.severity == "error"
        ],
        "changed_files": report.changed_files,
    }


def _file_to_json(file: SddFile) -> dict[str, Any]:
    return {
        "path": file.relpath,
        "kind": file.kind,
        "yyyymm": file.yyyymm,
        "name": file.name,
        "has_frontmatter": file.had_frontmatter,
        "parse_error": file.parse_error,
    }
