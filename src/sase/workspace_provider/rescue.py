"""Public API for durable workspace rescue."""

from sase.workspace_provider._rescue_git import (
    RESCUE_BUNDLE_NAME,
    rescue_git_repo,
)
from sase.workspace_provider._rescue_git_commands import RESCUE_GIT_TIMEOUT_SECONDS
from sase.workspace_provider._rescue_git_worktree import (
    RESCUE_PATCH_MAX_BYTES,
    RESCUE_PATCH_NAME,
)
from sase.workspace_provider._rescue_store import (
    RESCUE_ENTRY_RETENTION_DAYS,
    RESCUE_MANIFEST_NAME,
    RESCUE_QUARANTINE_DIRNAME,
    RESCUE_QUARANTINE_RETENTION_DAYS,
    RESCUE_SCHEMA_VERSION,
    RescueRecord,
    quarantine_directory,
)
from sase.workspace_provider.snapshot import (
    PreservationError,
    SnapshotRecord,
    restore_git_snapshot,
    snapshot_git_repo,
)

__all__ = [
    "PreservationError",
    "RESCUE_BUNDLE_NAME",
    "RESCUE_ENTRY_RETENTION_DAYS",
    "RESCUE_GIT_TIMEOUT_SECONDS",
    "RESCUE_MANIFEST_NAME",
    "RESCUE_PATCH_MAX_BYTES",
    "RESCUE_PATCH_NAME",
    "RESCUE_QUARANTINE_DIRNAME",
    "RESCUE_QUARANTINE_RETENTION_DAYS",
    "RESCUE_SCHEMA_VERSION",
    "RescueRecord",
    "SnapshotRecord",
    "quarantine_directory",
    "rescue_git_repo",
    "restore_git_snapshot",
    "snapshot_git_repo",
]
