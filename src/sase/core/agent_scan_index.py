"""Index identity, aliases, metadata, and status for agent artifacts.

These entry points resolve the persistent SQLite index file, read and
write its metadata and layout aliases, and report lightweight status.
Mutating row writes live in
:mod:`sase.core.agent_scan_index_mutations` and index reads live in
:mod:`sase.core.agent_scan_index_queries`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sase.core._agent_scan_shared import DEFAULT_READ_LOCK_TIMEOUT_SECONDS
from sase.core.agent_artifact_index_lock import agent_artifact_index_operation_lock
from sase.core.agent_artifact_index_lock import try_agent_artifact_index_operation_lock
from sase.core.agent_scan_wire import AgentArtifactIndexStatusWire
from sase.core.agent_scan_wire import AgentArtifactIndexVacuumWire
from sase.core.agent_scan_wire import agent_artifact_index_status_from_dict
from sase.core.agent_scan_wire import agent_artifact_index_vacuum_from_dict
from sase.core.paths import sase_home as _sase_home
from sase.core.rust import require_rust_binding


def default_agent_artifact_index_path(sase_home: Path | str | None = None) -> Path:
    """Return the default persistent artifact index path."""
    root = Path(sase_home).expanduser() if sase_home is not None else _sase_home()
    return root / "agent_artifact_index.sqlite"


def read_agent_artifact_index_schema_version(index_path: Path | str) -> int | None:
    """Read the stored schema version without opening a Python SQLite handle."""
    with agent_artifact_index_operation_lock():
        read_version = require_rust_binding("read_agent_artifact_index_schema_version")
        version = read_version(str(index_path))
    return int(version) if version is not None else None


def load_agent_artifact_index_projection(
    index_path: Path | str,
    columns: Sequence[str],
    *,
    busy_timeout_ms: int = 250,
) -> dict[str, Any]:
    """Load selected artifact index columns through the Rust read-only store."""
    with agent_artifact_index_operation_lock():
        load_projection = require_rust_binding("load_agent_artifact_index_projection")
        payload = load_projection(str(index_path), list(columns), busy_timeout_ms)
    return payload


def upsert_agent_artifact_alias(
    index_path: Path | str, alias_path: str, artifact_dir: str
) -> None:
    """Write an artifact layout alias through the Rust index store."""
    with agent_artifact_index_operation_lock():
        upsert_alias = require_rust_binding("upsert_agent_artifact_alias")
        upsert_alias(str(index_path), alias_path, artifact_dir)


def delete_agent_artifact_alias(
    index_path: Path | str, alias_path: str, artifact_dir: str
) -> None:
    """Delete an artifact layout alias through the Rust index store."""
    with agent_artifact_index_operation_lock():
        delete_alias = require_rust_binding("delete_agent_artifact_alias")
        delete_alias(str(index_path), alias_path, artifact_dir)


def list_agent_artifact_aliases(index_path: Path | str) -> dict[str, str]:
    """Read artifact layout aliases through the Rust index store."""
    with agent_artifact_index_operation_lock():
        list_aliases = require_rust_binding("list_agent_artifact_aliases")
        rows = list_aliases(str(index_path))
    return {str(row["alias_path"]): str(row["artifact_dir"]) for row in rows}


def read_agent_artifact_index_meta(
    index_path: Path | str,
    key: str,
) -> str | None:
    """Read one metadata value from the persistent artifact index."""
    with agent_artifact_index_operation_lock():
        rust_read = require_rust_binding("read_agent_artifact_index_meta")
        value = rust_read(str(index_path), str(key))
    return None if value is None else str(value)


def write_agent_artifact_index_meta(
    index_path: Path | str,
    key: str,
    value: str,
) -> None:
    """Write one metadata value in the persistent artifact index."""
    with agent_artifact_index_operation_lock():
        rust_write = require_rust_binding("write_agent_artifact_index_meta")
        rust_write(str(index_path), str(key), str(value))


SOURCE_RECONCILE_OK_META_KEY = "source_reconcile_ok"


def invalidate_agent_artifact_index_source_reconcile(
    index_path: Path | str | None = None,
) -> None:
    """Forget the last source-directory completeness watermark.

    Event overflow, unobserved writes, and process-restart recovery call
    this so a later cached full-history read cannot claim complete history
    on a corpus that has not been rediscovered. Marker revalidation does
    not discover new directories on its own.
    """
    index = (
        Path(index_path).expanduser()
        if index_path is not None
        else default_agent_artifact_index_path()
    )
    if not index.is_file():
        return
    write_agent_artifact_index_meta(index, SOURCE_RECONCILE_OK_META_KEY, "")


def agent_artifact_index_status(
    index_path: Path | str,
) -> AgentArtifactIndexStatusWire:
    """Return lightweight row-count status for the persistent artifact index."""
    with agent_artifact_index_operation_lock():
        rust_status = require_rust_binding("agent_artifact_index_status")
        payload: dict[str, Any] = rust_status(str(index_path))
    return agent_artifact_index_status_from_dict(payload)


def agent_artifact_index_status_bounded(
    index_path: Path | str,
    *,
    lock_timeout_seconds: float = DEFAULT_READ_LOCK_TIMEOUT_SECONDS,
) -> AgentArtifactIndexStatusWire | None:
    """Return index status, or ``None`` when the process-local lock is busy."""
    with try_agent_artifact_index_operation_lock(lock_timeout_seconds) as acquired:
        if not acquired:
            return None
        rust_status = require_rust_binding("agent_artifact_index_status")
        payload: dict[str, Any] = rust_status(str(index_path))
    return agent_artifact_index_status_from_dict(payload)


def vacuum_agent_artifact_index(
    index_path: Path | str,
) -> AgentArtifactIndexVacuumWire:
    """Reclaim freelist pages in the persistent artifact index via VACUUM.

    A tooling-only entry point: nothing in this codebase calls it
    automatically, so running it is always an explicit, user-initiated
    action (``sase agent index vacuum --apply``).
    """
    with agent_artifact_index_operation_lock():
        rust_vacuum = require_rust_binding("vacuum_agent_artifact_index")
        payload: dict[str, Any] = rust_vacuum(str(index_path))
    return agent_artifact_index_vacuum_from_dict(payload)


__all__ = [
    "SOURCE_RECONCILE_OK_META_KEY",
    "agent_artifact_index_status",
    "agent_artifact_index_status_bounded",
    "default_agent_artifact_index_path",
    "delete_agent_artifact_alias",
    "invalidate_agent_artifact_index_source_reconcile",
    "list_agent_artifact_aliases",
    "load_agent_artifact_index_projection",
    "read_agent_artifact_index_meta",
    "read_agent_artifact_index_schema_version",
    "upsert_agent_artifact_alias",
    "vacuum_agent_artifact_index",
    "write_agent_artifact_index_meta",
]
