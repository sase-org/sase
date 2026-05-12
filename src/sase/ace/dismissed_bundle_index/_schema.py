"""SQLite schema and row persistence for the dismissed bundle index."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

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
            _migrate_schema_by_rebuilding_from_bundles(conn, root, existing_version)
        else:
            _create_schema(conn)
        _ensure_archive_query_schema(conn)
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


def _migrate_schema_by_rebuilding_from_bundles(
    conn: sqlite3.Connection,
    root: Path,
    existing_version: int,
) -> None:
    """Replace a legacy index schema with v2 rows rebuilt from bundle JSON."""

    if existing_version == SCHEMA_VERSION:
        return
    conn.execute("DROP TABLE IF EXISTS dismissed_bundle_search_fts")
    conn.execute("DROP TABLE IF EXISTS dismissed_bundle_summaries")
    _create_schema(conn)
    rebuild_rows_from_bundles(conn, root)


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dismissed_bundle_summaries (
            bundle_path TEXT PRIMARY KEY,
            agent_id TEXT NOT NULL,
            raw_suffix TEXT NOT NULL,
            shard TEXT NOT NULL,
            filename TEXT NOT NULL,
            archive_revision INTEGER NOT NULL DEFAULT 1,
            bundle_schema_version INTEGER NOT NULL DEFAULT 0,
            agent_type TEXT NOT NULL,
            cl_name TEXT NOT NULL,
            agent_name TEXT,
            status TEXT NOT NULL,
            start_time TEXT,
            stop_time TEXT,
            dismissed_at TEXT,
            revived_at TEXT,
            times_revived INTEGER NOT NULL DEFAULT 0,
            project_file TEXT,
            project_name TEXT,
            model TEXT,
            llm_provider TEXT,
            runtime TEXT,
            vcs_provider TEXT,
            workflow TEXT,
            is_workflow_child INTEGER NOT NULL,
            parent_timestamp TEXT,
            step_index INTEGER,
            step_name TEXT,
            step_type TEXT,
            retry_of_timestamp TEXT,
            retried_as_timestamp TEXT,
            retry_chain_root_timestamp TEXT,
            retry_attempt INTEGER NOT NULL DEFAULT 0,
            meta_changespec TEXT,
            cost_usd_micros INTEGER,
            input_tokens INTEGER,
            output_tokens INTEGER,
            error_message_excerpt TEXT,
            mtime_ns INTEGER NOT NULL,
            size_bytes INTEGER NOT NULL
        )
        """
    )
    _create_fts_table(conn)
    _create_indexes(conn)


def _ensure_archive_query_schema(conn: sqlite3.Connection) -> None:
    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(dismissed_bundle_summaries)")
    }
    if "step_type" not in columns:
        conn.execute("ALTER TABLE dismissed_bundle_summaries ADD COLUMN step_type TEXT")
    _create_fts_table(conn)
    _create_indexes(conn)


def _create_fts_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS dismissed_bundle_search_fts
        USING fts5(bundle_path UNINDEXED, archive_search_text)
        """
    )


def _create_indexes(conn: sqlite3.Connection) -> None:
    indexes = {
        "idx_dismissed_bundle_agent_id": "agent_id",
        "idx_dismissed_bundle_raw_suffix": "raw_suffix",
        "idx_dismissed_bundle_status": "status",
        "idx_dismissed_bundle_name": "agent_name",
        "idx_dismissed_bundle_model": "model",
        "idx_dismissed_bundle_provider": "llm_provider",
        "idx_dismissed_bundle_runtime": "runtime",
        "idx_dismissed_bundle_start": "start_time",
        "idx_dismissed_bundle_project": "project_file",
        "idx_dismissed_bundle_project_name": "project_name",
        "idx_dismissed_bundle_dismissed": "dismissed_at",
        "idx_dismissed_bundle_revived": "revived_at",
        "idx_dismissed_bundle_step_type": "step_type",
    }
    for name, expression in indexes.items():
        conn.execute(
            f"CREATE INDEX IF NOT EXISTS {name} "
            f"ON dismissed_bundle_summaries({expression})"
        )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dismissed_bundle_cl "
        "ON dismissed_bundle_summaries(cl_name, meta_changespec)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dismissed_bundle_project_cl "
        "ON dismissed_bundle_summaries(project_name, cl_name, meta_changespec)"
    )


def rebuild_rows_from_bundles(conn: sqlite3.Connection, root: Path) -> int:
    indexed = 0
    for path in iter_bundle_paths(root):
        try:
            bundle = read_bundle(path)
            _backfill_archive_projection(path, bundle)
            summary = summary_from_bundle(root, path, bundle)
            upsert_summary(conn, summary, file_signature(path))
            upsert_search_text(conn, summary.bundle_path, bundle)
            indexed += 1
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            continue
    return indexed


def _backfill_archive_projection(path: Path, bundle: dict[str, Any]) -> None:
    from ..archive_search_text import normalize_archive_bundle_projection

    if not normalize_archive_bundle_projection(bundle):
        return
    path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")


def upsert_summary(
    conn: sqlite3.Connection,
    summary: DismissedBundleSummary,
    signature: tuple[int, int],
) -> None:
    mtime_ns, size_bytes = signature
    conn.execute(
        """
        INSERT INTO dismissed_bundle_summaries (
            bundle_path, agent_id, raw_suffix, shard, filename,
            archive_revision, bundle_schema_version, agent_type, cl_name,
            agent_name, status, start_time, stop_time, dismissed_at, revived_at,
            times_revived, project_file, project_name, model, llm_provider,
            runtime, vcs_provider, workflow, is_workflow_child, parent_timestamp,
            step_index, step_name, step_type, retry_of_timestamp, retried_as_timestamp,
            retry_chain_root_timestamp, retry_attempt, meta_changespec,
            cost_usd_micros, input_tokens, output_tokens, error_message_excerpt,
            mtime_ns, size_bytes
        )
        VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        ON CONFLICT(bundle_path) DO UPDATE SET
            agent_id=excluded.agent_id,
            raw_suffix=excluded.raw_suffix,
            shard=excluded.shard,
            filename=excluded.filename,
            archive_revision=excluded.archive_revision,
            bundle_schema_version=excluded.bundle_schema_version,
            agent_type=excluded.agent_type,
            cl_name=excluded.cl_name,
            agent_name=excluded.agent_name,
            status=excluded.status,
            start_time=excluded.start_time,
            stop_time=excluded.stop_time,
            dismissed_at=excluded.dismissed_at,
            revived_at=excluded.revived_at,
            times_revived=excluded.times_revived,
            project_file=excluded.project_file,
            project_name=excluded.project_name,
            model=excluded.model,
            llm_provider=excluded.llm_provider,
            runtime=excluded.runtime,
            vcs_provider=excluded.vcs_provider,
            workflow=excluded.workflow,
            is_workflow_child=excluded.is_workflow_child,
            parent_timestamp=excluded.parent_timestamp,
            step_index=excluded.step_index,
            step_name=excluded.step_name,
            step_type=excluded.step_type,
            retry_of_timestamp=excluded.retry_of_timestamp,
            retried_as_timestamp=excluded.retried_as_timestamp,
            retry_chain_root_timestamp=excluded.retry_chain_root_timestamp,
            retry_attempt=excluded.retry_attempt,
            meta_changespec=excluded.meta_changespec,
            cost_usd_micros=excluded.cost_usd_micros,
            input_tokens=excluded.input_tokens,
            output_tokens=excluded.output_tokens,
            error_message_excerpt=excluded.error_message_excerpt,
            mtime_ns=excluded.mtime_ns,
            size_bytes=excluded.size_bytes
        """,
        (
            summary.bundle_path,
            summary.agent_id,
            summary.raw_suffix,
            summary.shard,
            summary.filename,
            summary.archive_revision,
            summary.bundle_schema_version,
            summary.agent_type,
            summary.cl_name,
            summary.agent_name,
            summary.status,
            summary.start_time,
            summary.stop_time,
            summary.dismissed_at,
            summary.revived_at,
            summary.times_revived,
            summary.project_file,
            summary.project_name,
            summary.model,
            summary.llm_provider,
            summary.runtime,
            summary.vcs_provider,
            summary.workflow,
            int(summary.is_workflow_child),
            summary.parent_timestamp,
            summary.step_index,
            summary.step_name,
            summary.step_type,
            summary.retry_of_timestamp,
            summary.retried_as_timestamp,
            summary.retry_chain_root_timestamp,
            summary.retry_attempt,
            summary.meta_changespec,
            summary.cost_usd_micros,
            summary.input_tokens,
            summary.output_tokens,
            summary.error_message_excerpt,
            mtime_ns,
            size_bytes,
        ),
    )


def upsert_search_text(
    conn: sqlite3.Connection,
    bundle_path: str,
    bundle: dict[str, Any],
) -> None:
    text = bundle.get("archive_search_text")
    conn.execute(
        "DELETE FROM dismissed_bundle_search_fts WHERE bundle_path = ?",
        (bundle_path,),
    )
    if not isinstance(text, str) or not text:
        return
    conn.execute(
        """
        INSERT INTO dismissed_bundle_search_fts(bundle_path, archive_search_text)
        VALUES (?, ?)
        """,
        (bundle_path, text),
    )
