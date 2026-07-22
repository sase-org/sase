"""Immutable wire and outcome records for completed-agent synchronization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

BUNDLE_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
STATUS_SCHEMA_VERSION = 1
SYNC_RESULT_SCHEMA_VERSION = 1

StatusState = Literal[
    "ready",
    "disabled",
    "not_created",
    "missing_upstream",
    "configuration_error",
    "error",
]


@dataclass(frozen=True, slots=True)
class PortableAgentMetadata:
    """Allowlisted metadata transported for one completed agent."""

    name: str
    machine: str
    artifact_timestamp: str
    artifact_layout_version: int
    fields: tuple[tuple[str, Any], ...] = ()
    schema_version: int = BUNDLE_SCHEMA_VERSION

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "machine": self.machine,
            "artifact_timestamp": self.artifact_timestamp,
            "artifact_layout_version": self.artifact_layout_version,
            **dict(self.fields),
        }


@dataclass(frozen=True, slots=True)
class CommitRecord:
    """Portable primary-repository commit attribution."""

    sha: str
    subject: str
    committed_at: int

    def to_json_dict(self) -> dict[str, object]:
        return {
            "sha": self.sha,
            "subject": self.subject,
            "committed_at": self.committed_at,
        }


@dataclass(frozen=True, slots=True)
class AgentBundle:
    """Validated bundle contents plus their stable digest."""

    metadata: PortableAgentMetadata
    commits: tuple[CommitRecord, ...]
    chat_bytes: bytes
    digest: str


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    """One advertised bundle in an agents-sidecar manifest."""

    name: str
    machine: str
    digest: str
    artifact_timestamp: str
    updated_at: str
    schema_version: int = BUNDLE_SCHEMA_VERSION

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "machine": self.machine,
            "digest": self.digest,
            "artifact_timestamp": self.artifact_timestamp,
            "updated_at": self.updated_at,
        }


@dataclass(frozen=True, slots=True)
class AgentsManifest:
    """Strict manifest envelope for all sidecar agent bundles."""

    entries: tuple[ManifestEntry, ...] = ()
    schema_version: int = MANIFEST_SCHEMA_VERSION

    def by_name(self) -> dict[str, ManifestEntry]:
        return {entry.name: entry for entry in self.entries}

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "agents": {
                entry.name: entry.to_json_dict()
                for entry in sorted(self.entries, key=lambda item: item.name)
            },
        }


@dataclass(frozen=True, slots=True)
class ProjectTarget:
    """Resolved primary checkout and hidden sidecar for one project."""

    project_key: str
    project: str
    primary_checkout: Path
    primary_roots: tuple[Path, ...]
    sidecar_path: Path
    remote_url: str


@dataclass(frozen=True, slots=True)
class IntegrationCounts:
    """Counts produced while integrating foreign bundles."""

    integrated: int = 0
    refreshed: int = 0
    unchanged: int = 0

    @property
    def changed(self) -> int:
        return self.integrated + self.refreshed


@dataclass(frozen=True, slots=True)
class ExportCounts:
    """Counts produced while exporting locally owned bundles."""

    exported: int = 0
    refreshed: int = 0
    unchanged: int = 0
    skipped: int = 0
    diagnostics: tuple[str, ...] = ()

    @property
    def changed(self) -> int:
        return self.exported + self.refreshed


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    """Complete mutation outcome for one selected project."""

    project_key: str
    project: str
    pulled: bool = False
    integrated: int = 0
    refreshed: int = 0
    exported: int = 0
    export_refreshed: int = 0
    committed: bool = False
    pushed: bool = False
    push_attempts: int = 0
    skip_reason: str | None = None
    error: str | None = None
    diagnostics: tuple[str, ...] = ()
    schema_version: int = SYNC_RESULT_SCHEMA_VERSION

    @property
    def ok(self) -> bool:
        return self.error is None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_key": self.project_key,
            "project": self.project,
            "pulled": self.pulled,
            "integrated": self.integrated,
            "refreshed": self.refreshed,
            "exported": self.exported,
            "export_refreshed": self.export_refreshed,
            "committed": self.committed,
            "pushed": self.pushed,
            "push_attempts": self.push_attempts,
            "skip_reason": self.skip_reason,
            "error": self.error,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class ProjectSyncStatus:
    """Cheap cached/revalidated status for one project."""

    project_key: str
    project: str
    state: StatusState
    ahead: int | None = None
    behind: int | None = None
    unexported_agents: int | None = None
    last_fetch_time: float | None = None
    detail: str | None = None
    error: str | None = None

    def to_json_dict(self) -> dict[str, object]:
        return {
            "project_key": self.project_key,
            "project": self.project,
            "state": self.state,
            "ahead": self.ahead,
            "behind": self.behind,
            "unexported_agents": self.unexported_agents,
            "last_fetch_time": self.last_fetch_time,
            "detail": self.detail,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class SyncStatusSnapshot:
    """Versioned cache envelope for all selected project statuses."""

    checked_at: float
    projects: tuple[ProjectSyncStatus, ...] = ()
    schema_version: int = STATUS_SCHEMA_VERSION

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "checked_at": self.checked_at,
            "projects": [
                status.to_json_dict()
                for status in sorted(self.projects, key=lambda item: item.project_key)
            ],
        }


@dataclass(frozen=True, slots=True)
class TargetSelection:
    """Resolved sync targets plus truthful non-target outcomes."""

    targets: tuple[ProjectTarget, ...] = ()
    outcomes: tuple[SyncOutcome, ...] = ()


def sorted_fields(values: Mapping[str, Any]) -> tuple[tuple[str, Any], ...]:
    """Freeze a metadata mapping in deterministic key order."""

    return tuple(sorted(values.items()))


__all__ = [
    "AgentBundle",
    "AgentsManifest",
    "BUNDLE_SCHEMA_VERSION",
    "CommitRecord",
    "ExportCounts",
    "IntegrationCounts",
    "MANIFEST_SCHEMA_VERSION",
    "ManifestEntry",
    "PortableAgentMetadata",
    "ProjectSyncStatus",
    "ProjectTarget",
    "STATUS_SCHEMA_VERSION",
    "SYNC_RESULT_SCHEMA_VERSION",
    "StatusState",
    "SyncOutcome",
    "SyncStatusSnapshot",
    "TargetSelection",
    "sorted_fields",
]
