"""Schema-version maintenance for the persistent agent artifact index."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from sase.core.agent_artifact_index_lifecycle_common import (
    _INDEX_ERRORS,
    _LIFECYCLE_SCAN_OPTIONS,
    default_agent_artifact_projects_root,
)
from sase.core.agent_artifact_index_lock import agent_artifact_index_operation_lock
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    rebuild_agent_artifact_index,
)
from sase.core.agent_scan_wire import AGENT_ARTIFACT_INDEX_SCHEMA_VERSION

log = logging.getLogger(__name__)

_INDEX_SCHEMA_META_KEY = "schema_version"


@dataclass(frozen=True)
class _ArtifactIndexSchemaRefreshReport:
    """Outcome of startup schema refresh for the persistent artifact index."""

    checked: bool
    refreshed: bool = False
    stored_schema_version: int | None = None
    rows_indexed: int = 0


@dataclass(frozen=True)
class _ArtifactIndexSchemaStatus:
    """Cheap stored-schema check that never opens the Rust index."""

    checked: bool
    stale: bool = False
    stored_schema_version: int | None = None


def read_agent_artifact_index_schema_status(
    *,
    index_path: Path | str | None = None,
) -> _ArtifactIndexSchemaStatus:
    """Read stored schema metadata without migrating or rebuilding the index."""

    with agent_artifact_index_operation_lock():
        index = (
            Path(index_path).expanduser()
            if index_path is not None
            else default_agent_artifact_index_path()
        )
        return _read_agent_artifact_index_schema_status(index)


def refresh_agent_artifact_index_if_schema_stale(
    *,
    index_path: Path | str | None = None,
    projects_root: Path | str | None = None,
) -> _ArtifactIndexSchemaRefreshReport:
    """Rebuild the index once when stored schema metadata is older.

    The Rust index open path mutates ``meta.schema_version`` as part of normal
    DDL migration, so this reads the value directly with sqlite3 before any
    Rust query/status call can mask an old ``record_json`` projection.
    """
    with agent_artifact_index_operation_lock():
        index = (
            Path(index_path).expanduser()
            if index_path is not None
            else default_agent_artifact_index_path()
        )
        status = _read_agent_artifact_index_schema_status(index)
        if not status.checked:
            return _ArtifactIndexSchemaRefreshReport(checked=False)
        stored_version = status.stored_schema_version
        if not status.stale:
            return _ArtifactIndexSchemaRefreshReport(
                checked=True,
                stored_schema_version=stored_version,
            )

        root = (
            Path(projects_root).expanduser()
            if projects_root is not None
            else default_agent_artifact_projects_root()
        )
        try:
            update = rebuild_agent_artifact_index(index, root, _LIFECYCLE_SCAN_OPTIONS)
        except _INDEX_ERRORS:
            log.debug("agent artifact index stale-schema rebuild failed", exc_info=True)
            return _ArtifactIndexSchemaRefreshReport(
                checked=True,
                stored_schema_version=stored_version,
            )
        return _ArtifactIndexSchemaRefreshReport(
            checked=True,
            refreshed=True,
            stored_schema_version=stored_version,
            rows_indexed=update.rows_indexed,
        )


def _read_agent_artifact_index_schema_status(
    index: Path,
) -> _ArtifactIndexSchemaStatus:
    """Return schema status for *index* without invoking Rust migrations."""

    if not index.is_file():
        return _ArtifactIndexSchemaStatus(checked=False)
    stored_version = _read_stored_index_schema_version(index)
    if stored_version is None:
        return _ArtifactIndexSchemaStatus(checked=False)
    return _ArtifactIndexSchemaStatus(
        checked=True,
        stale=stored_version < AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
        stored_schema_version=stored_version,
    )


def _read_stored_index_schema_version(index: Path) -> int | None:
    """Read stored schema metadata without invoking Rust index migration."""
    try:
        with sqlite3.connect(f"{index.resolve().as_uri()}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?",
                (_INDEX_SCHEMA_META_KEY,),
            ).fetchone()
    except sqlite3.OperationalError as error:
        message = str(error).lower()
        if "no such table" in message:
            return 0
        log.debug("agent artifact index schema-version read failed", exc_info=True)
        return None
    except sqlite3.Error:
        log.debug("agent artifact index schema-version read failed", exc_info=True)
        return None
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0
