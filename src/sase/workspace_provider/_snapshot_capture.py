"""Non-destructive verified snapshot capture (facade).

The implementation lives in :mod:`sase.workspace_provider._snapshot_capture_source`
(orchestration and source-state reading) and
:mod:`sase.workspace_provider._snapshot_capture_payload` (capture, pack, and
manifest). This module re-exports the public entry points so the original import
path keeps working.
"""

from __future__ import annotations

from sase.workspace_provider._snapshot_capture_payload import publish_manifest
from sase.workspace_provider._snapshot_capture_source import (
    read_source_state,
    snapshot_git_repo,
    snapshot_source_fingerprint,
)

__all__ = [
    "publish_manifest",
    "read_source_state",
    "snapshot_git_repo",
    "snapshot_source_fingerprint",
]
