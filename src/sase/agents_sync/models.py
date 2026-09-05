"""Immutable wire and outcome records for completed-agent synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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


__all__ = [
    "CommitRecord",
    "ExportCounts",
    "ProjectSyncStatus",
    "ProjectTarget",
    "STATUS_SCHEMA_VERSION",
    "SYNC_RESULT_SCHEMA_VERSION",
    "StatusState",
    "SyncOutcome",
    "SyncStatusSnapshot",
    "TargetSelection",
]
