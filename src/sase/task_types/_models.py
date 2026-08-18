"""Data models shared by task-type registry components."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

DiagnosticSeverity = Literal["warning", "error"]
TaskTypeSource = Literal["builtin", "plugin", "project"]


@dataclass(frozen=True)
class TaskTypeProvenance:
    """Origin metadata for one discovered task-type spec."""

    source: TaskTypeSource
    name: str
    package: str
    version: str
    builtin: bool = False

    @property
    def label(self) -> str:
        if self.source == "builtin":
            return "builtin:sase"
        if self.source == "project":
            return "project:bead.task_types"
        return f"plugin:{self.name}"


@dataclass(frozen=True)
class TaskTypeDiagnostic:
    """Structured diagnostic emitted while assembling the task-type catalog."""

    code: str
    message: str
    severity: DiagnosticSeverity = "warning"
    task_type: str | None = None
    source: str | None = None
    package: str | None = None
    version: str | None = None


@dataclass(frozen=True)
class TaskTypeRecord:
    """One validated task-type spec plus its resolved presentation."""

    task_type: str
    spec: Mapping[str, Any]
    digest: str
    provenance: TaskTypeProvenance
    resolved_glyph: str = ""
    resolved_accent_color: str = ""

    @property
    def agent_creatable(self) -> bool:
        return bool(self.spec.get("agent_creatable", True))


@dataclass(frozen=True)
class TaskTypeRegistry:
    """Effective task-type catalog plus assembly diagnostics."""

    records: tuple[TaskTypeRecord, ...]
    diagnostics: tuple[TaskTypeDiagnostic, ...]
    disabled_env: tuple[str, ...] = ()

    @property
    def by_slug(self) -> dict[str, TaskTypeRecord]:
        return {record.task_type: record for record in self.records}

    @property
    def agent_creatable(self) -> tuple[TaskTypeRecord, ...]:
        return tuple(record for record in self.records if record.agent_creatable)


__all__ = [
    "DiagnosticSeverity",
    "TaskTypeDiagnostic",
    "TaskTypeProvenance",
    "TaskTypeRecord",
    "TaskTypeRegistry",
    "TaskTypeSource",
]
