"""Shared settlement adapter for terminal workspace retention.

Python collects workspace/repository evidence and applies the Rust-selected
effect. Classification stays in ``sase_core``; this module never substitutes
a Python policy fallback.

Facade preserving the original public import path. Implementation lives in
the private ``_workspace_retention`` package.
"""

from __future__ import annotations

from ._workspace_retention.discover import discover_workspace_retention_repos
from ._workspace_retention.pending import (
    clear_pending_retention,
    pending_retention_matches_owner,
    read_pending_retention,
    write_pending_retention,
)
from ._workspace_retention.settle import settle_stranded_workspace
from ._workspace_retention.types import (
    PENDING_RETENTION_LOCATOR,
    RETENTION_META_FIELD,
    RETENTION_RECORD_LOCATOR,
    WorkspaceRetentionOwner,
    WorkspaceRetentionRepo,
    WorkspaceRetentionSuccessor,
)

__all__ = [
    "PENDING_RETENTION_LOCATOR",
    "RETENTION_META_FIELD",
    "RETENTION_RECORD_LOCATOR",
    "WorkspaceRetentionOwner",
    "WorkspaceRetentionRepo",
    "WorkspaceRetentionSuccessor",
    "clear_pending_retention",
    "discover_workspace_retention_repos",
    "pending_retention_matches_owner",
    "read_pending_retention",
    "settle_stranded_workspace",
    "write_pending_retention",
]
