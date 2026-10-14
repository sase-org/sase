"""Row mutations for the persistent agent artifact index.

These entry points rebuild, upsert, delete, terminalize, prune, and
reconcile rows through ``sase_core_rs`` under the artifact index
operation lock. Index reads live in
:mod:`sase.core.agent_scan_index_queries`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.core._agent_scan_shared import options_to_dict
from sase.core.agent_artifact_index_lock import agent_artifact_index_operation_lock
from sase.core.agent_artifact_index_lock import try_agent_artifact_index_operation_lock
from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_cleanup_wire import agent_cleanup_wire_to_json_dict
from sase.core.agent_scan_wire import AgentArtifactIndexDismissalReconcileWire
from sase.core.agent_scan_wire import AgentArtifactIndexUpdateWire
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
from sase.core.agent_scan_wire import agent_artifact_index_dismissal_reconcile_from_dict
from sase.core.agent_scan_wire import agent_artifact_index_update_from_dict
from sase.core.rust import require_rust_binding


def rebuild_agent_artifact_index(
    index_path: Path | str,
    projects_root: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexUpdateWire:
    """Rebuild the persistent artifact index from source artifact files."""
    opts = options or AgentArtifactScanOptionsWire()
    with agent_artifact_index_operation_lock():
        rust_rebuild = require_rust_binding("rebuild_agent_artifact_index")
        payload: dict[str, Any] = rust_rebuild(
            str(index_path), str(projects_root), options_to_dict(opts)
        )
    return agent_artifact_index_update_from_dict(payload)


def upsert_agent_artifact_index_row(
    index_path: Path | str,
    projects_root: Path | str,
    artifact_dir: Path | str,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexUpdateWire:
    """Reparse and upsert one artifact directory into the index."""
    opts = options or AgentArtifactScanOptionsWire()
    with agent_artifact_index_operation_lock():
        rust_upsert = require_rust_binding("upsert_agent_artifact_index_row")
        payload: dict[str, Any] = rust_upsert(
            str(index_path),
            str(projects_root),
            str(artifact_dir),
            options_to_dict(opts),
        )
    return agent_artifact_index_update_from_dict(payload)


def delete_agent_artifact_index_row(
    index_path: Path | str,
    artifact_dir: Path | str,
) -> AgentArtifactIndexUpdateWire:
    """Remove one artifact directory row from the index."""
    with agent_artifact_index_operation_lock():
        rust_delete = require_rust_binding("delete_agent_artifact_index_row")
        payload: dict[str, Any] = rust_delete(str(index_path), str(artifact_dir))
    return agent_artifact_index_update_from_dict(payload)


def delete_agent_artifact_index_row_bounded(
    index_path: Path | str,
    artifact_dir: Path | str,
    *,
    lock_timeout_seconds: float,
    busy_timeout_seconds: float,
) -> AgentArtifactIndexUpdateWire | None:
    """Delete one row without waiting indefinitely on process/SQLite locks.

    ``None`` means the process-local lock was busy and the caller should retry
    later. SQLite timeout errors remain exceptions so lifecycle callers can
    distinguish a skipped mutation from a successful zero-row delete.
    """
    with try_agent_artifact_index_operation_lock(lock_timeout_seconds) as acquired:
        if not acquired:
            return None
        rust_delete = require_rust_binding("delete_agent_artifact_index_row_bounded")
        payload: dict[str, Any] = rust_delete(
            str(index_path),
            str(artifact_dir),
            max(0, round(busy_timeout_seconds * 1000.0)),
        )
    return agent_artifact_index_update_from_dict(payload)


def terminalize_stale_active_agent_artifact_index_rows(
    index_path: Path | str,
    projects_root: Path | str,
    *,
    stale_after_seconds: int,
    max_rows: int | None = None,
    options: AgentArtifactScanOptionsWire | None = None,
) -> AgentArtifactIndexUpdateWire:
    """Mark stale, unclaimed no-marker active rows terminal in the index."""
    opts = options or AgentArtifactScanOptionsWire()
    with agent_artifact_index_operation_lock():
        rust_terminalize = require_rust_binding(
            "terminalize_stale_active_agent_artifact_index_rows"
        )
        payload: dict[str, Any] = rust_terminalize(
            str(index_path),
            str(projects_root),
            int(stale_after_seconds),
            max_rows,
            options_to_dict(opts),
        )
    return agent_artifact_index_update_from_dict(payload)


def prune_hidden_terminal_agent_artifact_index_rows(
    index_path: Path | str,
    *,
    hot_rows: int | None = None,
) -> AgentArtifactIndexUpdateWire:
    """Prune old hidden terminal rows from the hot artifact index view."""
    with agent_artifact_index_operation_lock():
        rust_prune = require_rust_binding(
            "prune_hidden_terminal_agent_artifact_index_rows"
        )
        payload: dict[str, Any] = rust_prune(str(index_path), hot_rows)
    return agent_artifact_index_update_from_dict(payload)


def replace_agent_artifact_index_dismissed_agents(
    index_path: Path | str,
    dismissed: Sequence[AgentCleanupIdentityWire],
    *,
    force: bool = False,
) -> AgentArtifactIndexUpdateWire:
    """Replace the artifact index's dismissed identity table.

    The Rust core diffs the incoming identities against the stored table
    unless *force* is true, which keeps the unconditional full-table rewrite.
    """
    with agent_artifact_index_operation_lock():
        rust_replace = require_rust_binding(
            "replace_agent_artifact_index_dismissed_agents"
        )
        identities = agent_cleanup_wire_to_json_dict(list(dismissed))
        index = str(index_path)
        if force:
            try:
                payload: dict[str, Any] = rust_replace(index, identities, True)
            except TypeError:
                payload = rust_replace(index, identities)
        else:
            payload = rust_replace(index, identities)
    return agent_artifact_index_update_from_dict(payload)


def reconcile_agent_artifact_index_dismissed_agent_session_members(
    index_path: Path | str,
    *,
    dry_run: bool = False,
) -> AgentArtifactIndexDismissalReconcileWire:
    """Back-fill dismissed identities for dead members of dismissed agent sessions."""
    with agent_artifact_index_operation_lock():
        rust_reconcile = require_rust_binding(
            "reconcile_agent_artifact_index_dismissed_agent_session_members"
        )
        payload: dict[str, Any] = rust_reconcile(str(index_path), bool(dry_run))
    return agent_artifact_index_dismissal_reconcile_from_dict(payload)


__all__ = [
    "delete_agent_artifact_index_row",
    "delete_agent_artifact_index_row_bounded",
    "prune_hidden_terminal_agent_artifact_index_rows",
    "rebuild_agent_artifact_index",
    "reconcile_agent_artifact_index_dismissed_agent_session_members",
    "replace_agent_artifact_index_dismissed_agents",
    "terminalize_stale_active_agent_artifact_index_rows",
    "upsert_agent_artifact_index_row",
]
