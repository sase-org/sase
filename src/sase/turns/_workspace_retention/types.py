"""Owner, repository, and successor types for workspace retention."""

from __future__ import annotations

from dataclasses import dataclass

RETENTION_RECORD_LOCATOR = "diagnostics/workspace_retention.json"
RETENTION_META_FIELD = "workspace_retention_record_path"
PENDING_RETENTION_LOCATOR = "diagnostics/pending_workspace_retention.json"


@dataclass(frozen=True, slots=True)
class WorkspaceRetentionRepo:
    """One relevant repository belonging to the settling owner."""

    repo_id: str
    path: str
    is_primary: bool = False
    positive_custody: bool = False


@dataclass(frozen=True, slots=True)
class WorkspaceRetentionOwner:
    """Exact claim and checkout being relinquished."""

    project_file: str
    workspace_num: int
    workflow: str
    cl_name: str
    artifacts_timestamp: str
    pid: int
    artifacts_dir: str
    checkout_dir: str | None = None
    repos: tuple[WorkspaceRetentionRepo, ...] = ()
    origin_repo_ids: tuple[str, ...] = ()
    staged_id: str | None = None
    session_id: str | None = None
    turn_id: str | None = None
    terminal_reason: str = ""
    evidence_artifacts_dir: str | None = None
    notify_on_retain: bool = False
    discovery_errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkspaceRetentionSuccessor:
    """Confirmed successor custody for the workspace being settled."""

    confirmed_active: bool = False
    same_workspace: bool = False
    inherited_obligations: bool = False


__all__ = [
    "PENDING_RETENTION_LOCATOR",
    "RETENTION_META_FIELD",
    "RETENTION_RECORD_LOCATOR",
    "WorkspaceRetentionOwner",
    "WorkspaceRetentionRepo",
    "WorkspaceRetentionSuccessor",
]
