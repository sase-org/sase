"""Immutable wire and outcome records for completed-agent synchronization."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

BUNDLE_SCHEMA_VERSION = 1
CACHE_SCHEMA_VERSION = 1
MANIFEST_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = 1
STATUS_SCHEMA_VERSION = 4
SYNC_RESULT_SCHEMA_VERSION = 2

StatusState = Literal[
    "ready",
    "disabled",
    "not_created",
    "missing_upstream",
    "configuration_error",
    "error",
]
SourceOwnerKind = Literal["exact", "username_unknown_v1"]
CachedIntegrationDisposition = Literal[
    "applied",
    "owner_observed",
    "already_applied",
    "stale",
    "missing",
    "owner_namespace_conflict",
    "quarantined",
    "failed",
    "sunset_skipped",
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
    primary_repo_name: str | None = None


@dataclass(frozen=True, slots=True)
class CapturedIncomingHood:
    """One immutable, validated foreign hood captured from a fetched commit."""

    project_key: str
    project: str
    fetched_ref: str
    fetched_sha: str
    cache_id: str
    format_version: int
    source_owner_kind: SourceOwnerKind
    source_username: str | None
    source_machine: str
    top_hood: str
    hood_digest: str
    run_count: int
    family_count: int
    cache_created_at: float
    schema_version: int = CACHE_SCHEMA_VERSION

    @property
    def source_hood_key(self) -> tuple[str, str | None, str, str]:
        return (
            self.source_owner_kind,
            self.source_username,
            self.source_machine,
            self.top_hood,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_key": self.project_key,
            "project": self.project,
            "fetched_ref": self.fetched_ref,
            "fetched_sha": self.fetched_sha,
            "cache_id": self.cache_id,
            "format_version": self.format_version,
            "source_owner_kind": self.source_owner_kind,
            "source_username": self.source_username,
            "source_machine": self.source_machine,
            "top_hood": self.top_hood,
            "hood_digest": self.hood_digest,
            "run_count": self.run_count,
            "family_count": self.family_count,
            "cache_created_at": self.cache_created_at,
        }


@dataclass(frozen=True, slots=True)
class AgentHoodImportReceipt:
    """Last successfully applied digest for one exact source hood."""

    project_key: str
    project: str
    source_owner_kind: SourceOwnerKind
    source_username: str | None
    source_machine: str
    top_hood: str
    hood_digest: str
    cache_id: str
    fetched_ref: str
    fetched_sha: str
    cache_created_at: float
    applied_at: float
    schema_version: int = RECEIPT_SCHEMA_VERSION

    @property
    def source_hood_key(self) -> tuple[str, str | None, str, str]:
        return (
            self.source_owner_kind,
            self.source_username,
            self.source_machine,
            self.top_hood,
        )

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "project_key": self.project_key,
            "project": self.project,
            "source_owner_kind": self.source_owner_kind,
            "source_username": self.source_username,
            "source_machine": self.source_machine,
            "top_hood": self.top_hood,
            "hood_digest": self.hood_digest,
            "cache_id": self.cache_id,
            "fetched_ref": self.fetched_ref,
            "fetched_sha": self.fetched_sha,
            "cache_created_at": self.cache_created_at,
            "applied_at": self.applied_at,
        }


@dataclass(frozen=True, slots=True)
class CachedIntegrationResult:
    """Typed outcome for integrating one immutable cache item."""

    captured: CapturedIncomingHood
    disposition: CachedIntegrationDisposition
    integrated: int = 0
    refreshed: int = 0
    unchanged: int = 0
    hoods_imported: int = 0
    hoods_refreshed: int = 0
    hoods_unchanged: int = 0
    hoods_quarantined: int = 0
    families_imported: int = 0
    runs_imported: int = 0
    diagnostics: tuple[str, ...] = ()
    schema_version: int = CACHE_SCHEMA_VERSION

    @property
    def ok(self) -> bool:
        return self.disposition not in {"quarantined", "failed"}

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "captured": self.captured.to_json_dict(),
            "disposition": self.disposition,
            "integrated": self.integrated,
            "refreshed": self.refreshed,
            "unchanged": self.unchanged,
            "hoods_imported": self.hoods_imported,
            "hoods_refreshed": self.hoods_refreshed,
            "hoods_unchanged": self.hoods_unchanged,
            "hoods_quarantined": self.hoods_quarantined,
            "families_imported": self.families_imported,
            "runs_imported": self.runs_imported,
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True, slots=True)
class IntegrationCounts:
    """Counts produced while integrating foreign bundles."""

    integrated: int = 0
    refreshed: int = 0
    unchanged: int = 0
    hoods_imported: int = 0
    hoods_refreshed: int = 0
    hoods_unchanged: int = 0
    hoods_quarantined: int = 0
    families_imported: int = 0
    runs_imported: int = 0
    diagnostics: tuple[str, ...] = ()
    owner_observed_groups: int = 0
    v1_import_skipped: int = 0

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
    hoods_published: int = 0
    hoods_refreshed: int = 0
    hoods_unchanged: int = 0
    families_published: int = 0
    runs_published: int = 0
    schema_version: int = 2

    @property
    def changed(self) -> int:
        return self.exported + self.refreshed

    @property
    def v2_changed(self) -> int:
        return self.hoods_published + self.hoods_refreshed


@dataclass(frozen=True, slots=True)
class SyncOutcome:
    """Complete mutation outcome for one selected project."""

    project_key: str
    project: str
    pulled: bool = False
    exported: int = 0
    export_refreshed: int = 0
    committed: bool = False
    pushed: bool = False
    push_attempts: int = 0
    skip_reason: str | None = None
    error: str | None = None
    diagnostics: tuple[str, ...] = ()
    hoods_published: int = 0
    hoods_refreshed: int = 0
    hoods_unchanged: int = 0
    families_published: int = 0
    runs_published: int = 0
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
            "exported": self.exported,
            "export_refreshed": self.export_refreshed,
            "hoods_published": self.hoods_published,
            "hoods_refreshed": self.hoods_refreshed,
            "hoods_unchanged": self.hoods_unchanged,
            "families_published": self.families_published,
            "runs_published": self.runs_published,
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
    last_fetch_time: float | None = None
    detail: str | None = None
    error: str | None = None
    quarantine_diagnostics: tuple[str, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "project_key": self.project_key,
            "project": self.project,
            "state": self.state,
            "ahead": self.ahead,
            "behind": self.behind,
            "last_fetch_time": self.last_fetch_time,
            "detail": self.detail,
            "error": self.error,
            "quarantine_diagnostics": list(self.quarantine_diagnostics),
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
    "AgentHoodImportReceipt",
    "AgentsManifest",
    "BUNDLE_SCHEMA_VERSION",
    "CACHE_SCHEMA_VERSION",
    "CachedIntegrationDisposition",
    "CachedIntegrationResult",
    "CapturedIncomingHood",
    "CommitRecord",
    "ExportCounts",
    "IntegrationCounts",
    "MANIFEST_SCHEMA_VERSION",
    "ManifestEntry",
    "PortableAgentMetadata",
    "ProjectSyncStatus",
    "ProjectTarget",
    "RECEIPT_SCHEMA_VERSION",
    "SourceOwnerKind",
    "STATUS_SCHEMA_VERSION",
    "SYNC_RESULT_SCHEMA_VERSION",
    "StatusState",
    "SyncOutcome",
    "SyncStatusSnapshot",
    "TargetSelection",
    "sorted_fields",
]
