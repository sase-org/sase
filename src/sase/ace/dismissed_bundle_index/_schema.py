"""SQLite schema and row persistence for the dismissed bundle index."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from ._bundle_io import (
    file_signature,
    index_path_for_root,
    iter_bundle_paths,
    read_bundle,
)
from ._models import SCHEMA_VERSION, DismissedBundleSummary
from ._summary import summary_from_bundle


def _connect(root: Path, *, create: bool = True) -> sqlite3.Connection:
    if create:
        root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(index_path_for_root(root), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    if create:
        _ensure_schema(conn, root)
    return conn


@contextmanager
def connection(root: Path, *, create: bool = True) -> Iterator[sqlite3.Connection]:
    """Open an index connection, commit/rollback work, and always close it."""

    with closing(_connect(root, create=create)) as conn:
        with conn:
            yield conn


@contextmanager
def write_connection(root: Path) -> Iterator[sqlite3.Connection]:
    """Open an index connection and run the caller inside BEGIN IMMEDIATE."""

    with closing(_connect(root)) as conn:
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _ensure_schema(conn: sqlite3.Connection, root: Path) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dismissed_bundle_index_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        row = conn.execute(
            "SELECT value FROM dismissed_bundle_index_meta WHERE key = 'schema_version'"
        ).fetchone()
        existing_version = _schema_version_from_row(row)
        if existing_version is not None and existing_version != SCHEMA_VERSION:
            _drop_index_tables(conn)
            conn.execute("DELETE FROM dismissed_bundle_index_meta")
            _create_schema(conn)
        else:
            _create_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO dismissed_bundle_index_meta(key, value) "
            "VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _schema_version_from_row(row: sqlite3.Row | None) -> int | None:
    if row is None:
        return None
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return -1


def _drop_index_tables(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT name FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
          AND name != 'dismissed_bundle_index_meta'
        """
    ).fetchall()
    for row in rows:
        name = str(row["name"])
        quoted_name = '"' + name.replace('"', '""') + '"'
        conn.execute(f"DROP TABLE IF EXISTS {quoted_name}")


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dismissed_bundle_summaries (
            bundle_path TEXT PRIMARY KEY,
            raw_suffix TEXT NOT NULL,
            shard TEXT NOT NULL,
            filename TEXT NOT NULL,
            agent_type TEXT NOT NULL,
            cl_name TEXT NOT NULL,
            agent_name TEXT,
            status TEXT NOT NULL,
            start_time TEXT,
            stop_time TEXT,
            project_file TEXT,
            model TEXT,
            llm_provider TEXT,
            vcs_provider TEXT,
            workflow TEXT,
            is_workflow_child INTEGER NOT NULL,
            parent_timestamp TEXT,
            step_index INTEGER,
            step_name TEXT,
            retry_of_timestamp TEXT,
            retried_as_timestamp TEXT,
            retry_chain_root_timestamp TEXT,
            retry_attempt INTEGER NOT NULL DEFAULT 0,
            meta_patch TEXT,
            mtime_ns INTEGER NOT NULL,
            size_bytes INTEGER NOT NULL
        )
        """
    )
    _create_indexes(conn)


def _create_indexes(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dismissed_bundle_raw_suffix "
        "ON dismissed_bundle_summaries(raw_suffix)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dismissed_bundle_cl "
        "ON dismissed_bundle_summaries(cl_name, meta_patch)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dismissed_bundle_project "
        "ON dismissed_bundle_summaries(project_file)"
    )


def rebuild_rows_from_bundles(conn: sqlite3.Connection, root: Path) -> int:
    indexed = 0
    for path in iter_bundle_paths(root):
        try:
            bundle = read_bundle(path)
            summary = summary_from_bundle(root, path, bundle)
            upsert_summary(conn, summary, file_signature(path))
            indexed += 1
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            continue
    return indexed


def upsert_summary(
    conn: sqlite3.Connection,
    summary: DismissedBundleSummary,
    signature: tuple[int, int],
) -> None:
    mtime_ns, size_bytes = signature
    conn.execute(
        """
        INSERT INTO dismissed_bundle_summaries (
            bundle_path, raw_suffix, shard, filename, agent_type, cl_name,
            agent_name, status, start_time, stop_time, project_file, model,
            llm_provider, vcs_provider, workflow, is_workflow_child,
            parent_timestamp, step_index, step_name, retry_of_timestamp,
            retried_as_timestamp, retry_chain_root_timestamp, retry_attempt,
            meta_patch, mtime_ns, size_bytes
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?
        )
        ON CONFLICT(bundle_path) DO UPDATE SET
            raw_suffix=excluded.raw_suffix,
            shard=excluded.shard,
            filename=excluded.filename,
            agent_type=excluded.agent_type,
            cl_name=excluded.cl_name,
            agent_name=excluded.agent_name,
            status=excluded.status,
            start_time=excluded.start_time,
            stop_time=excluded.stop_time,
            project_file=excluded.project_file,
            model=excluded.model,
            llm_provider=excluded.llm_provider,
            vcs_provider=excluded.vcs_provider,
            workflow=excluded.workflow,
            is_workflow_child=excluded.is_workflow_child,
            parent_timestamp=excluded.parent_timestamp,
            step_index=excluded.step_index,
            step_name=excluded.step_name,
            retry_of_timestamp=excluded.retry_of_timestamp,
            retried_as_timestamp=excluded.retried_as_timestamp,
            retry_chain_root_timestamp=excluded.retry_chain_root_timestamp,
            retry_attempt=excluded.retry_attempt,
            meta_patch=excluded.meta_patch,
            mtime_ns=excluded.mtime_ns,
            size_bytes=excluded.size_bytes
        """,
        (
            summary.bundle_path,
            summary.raw_suffix,
            summary.shard,
            summary.filename,
            summary.agent_type,
            summary.cl_name,
            summary.agent_name,
            summary.status,
            summary.start_time,
            summary.stop_time,
            summary.project_file,
            summary.model,
            summary.llm_provider,
            summary.vcs_provider,
            summary.workflow,
            int(summary.is_workflow_child),
            summary.parent_timestamp,
            summary.step_index,
            summary.step_name,
            summary.retry_of_timestamp,
            summary.retried_as_timestamp,
            summary.retry_chain_root_timestamp,
            summary.retry_attempt,
            summary.meta_patch,
            mtime_ns,
            size_bytes,
        ),
    )
