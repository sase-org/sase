"""Backup-first stale-replay recovery for unpublished sidecar commits.

This is a finite recovery helper, not a normal drain. It inventories unique
owner data outside the clone, classifies conflicting files through Rust,
regenerates browsing pages on current upstream, and reapplies preserved
owner snapshots through the existing sidecar transaction callback.
"""

from __future__ import annotations

from sase.agents_sync._publication_replay_recovery_recover import (
    recover_stale_replay,
)
from sase.agents_sync._publication_replay_recovery_types import (
    BUNDLE_NAME,
    CHECKSUMS_NAME,
    OBJECTS_DIR,
    PRESERVED_DIR,
    PROGRESS_NAME,
    REVISIONS_NAME,
    ReplayRecoveryReport,
)

__all__ = [
    "BUNDLE_NAME",
    "CHECKSUMS_NAME",
    "OBJECTS_DIR",
    "PRESERVED_DIR",
    "PROGRESS_NAME",
    "REVISIONS_NAME",
    "ReplayRecoveryReport",
    "recover_stale_replay",
]
