"""Pending-retention facts written before a risky settlement."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.turns.workspace_retention_pending import (
    clear_pending_retention_identity,
    pending_retention_identity_matches,
    read_pending_retention_identity,
    write_pending_retention_identity,
)

from .types import WorkspaceRetentionOwner


def write_pending_retention(owner: WorkspaceRetentionOwner, reason: str) -> str | None:
    """Record a durable pending-retention fact before a risky settlement.

    Crash ordering starts here: pending evidence, then pinning, then the
    final retention record. Stale cleanup honors an exact-owner pending fact
    until a matching guarded settlement or recovery decision completes.
    Delegates to the adapter-independent identity writer so a stale
    settlement adapter cannot block the pending fact.
    """
    return write_pending_retention_identity(
        owner.artifacts_dir,
        workspace_num=owner.workspace_num,
        workflow=owner.workflow,
        cl_name=owner.cl_name,
        artifacts_timestamp=owner.artifacts_timestamp,
        pid=owner.pid,
        reason=reason,
        terminal_reason=owner.terminal_reason,
    )


def read_pending_retention(artifacts_dir: str | Path | None) -> dict[str, Any] | None:
    """Read a pending-retention fact; malformed and absent data is ignored."""
    return read_pending_retention_identity(artifacts_dir)


def clear_pending_retention(artifacts_dir: str | Path | None) -> None:
    """Remove a pending-retention fact after settlement or recovery decides."""
    clear_pending_retention_identity(artifacts_dir)


def pending_retention_matches_owner(
    pending: dict[str, Any] | None, owner: WorkspaceRetentionOwner
) -> bool:
    """Check a pending fact names the exact owner awaiting settlement."""
    return pending_retention_identity_matches(
        pending,
        workspace_num=owner.workspace_num,
        workflow=owner.workflow,
        cl_name=owner.cl_name,
        artifacts_timestamp=owner.artifacts_timestamp,
        pid=owner.pid,
    )


__all__ = [
    "clear_pending_retention",
    "pending_retention_matches_owner",
    "read_pending_retention",
    "write_pending_retention",
]
