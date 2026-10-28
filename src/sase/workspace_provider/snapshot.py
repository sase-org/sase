"""Strict verified checkout snapshots adjacent to workspace rescue.

``snapshot_git_repo`` is the required-preservation entry point. It reuses
rescue store allocation and never mutates the source index, worktree, HEAD,
or operation state. Callers that still want best-effort behavior keep using
:func:`sase.workspace_provider.rescue.rescue_git_repo`.
"""

from __future__ import annotations

from sase.workspace_provider._snapshot_capture import (
    snapshot_git_repo,
    snapshot_source_fingerprint,
)
from sase.workspace_provider._snapshot_model import (
    SNAPSHOT_KIND,
    SNAPSHOT_MAX_BYTES,
    SNAPSHOT_PACK_NAME,
    NestedPreservationError,
    PreservationError,
    SnapshotRecord,
)
from sase.workspace_provider._snapshot_nested import (
    NestedPreservation,
    format_preservation_locations,
    preserve_nested_repositories,
)
from sase.workspace_provider._snapshot_restore import restore_git_snapshot

__all__ = [
    "SNAPSHOT_KIND",
    "SNAPSHOT_MAX_BYTES",
    "SNAPSHOT_PACK_NAME",
    "NestedPreservation",
    "NestedPreservationError",
    "PreservationError",
    "SnapshotRecord",
    "format_preservation_locations",
    "preserve_nested_repositories",
    "restore_git_snapshot",
    "snapshot_git_repo",
    "snapshot_source_fingerprint",
]
