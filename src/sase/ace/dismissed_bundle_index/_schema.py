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
        if existing_version is not None and (
            existing_version != SCHEMA_VERSION or not _schema_compatible(conn)
        ):
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


def _schema_compatible(conn: sqlite3.Connection) -> bool:
    summary_columns = _table_columns(conn, "dismissed_bundle_summaries")
    projection_columns = _table_columns(conn, "archive_visibility_projection")
    required_summary_columns = {
        "bundle_path",
        "agent_id",
        "raw_suffix",
        "source_username",
        "source_machine",
        "source_run_id",
        "archive_visibility",
        "historically_viewable",
        "durably_revivable",
        "restartable",
        "missing_requirements",
        "mtime_ns",
        "size_bytes",
    }
    required_projection_columns = {
        "source_username",
        "source_machine",
        "source_run_id",
        "visibility",
    }
    return (
        required_summary_columns <= summary_columns
        and required_projection_columns <= projection_columns
    )


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


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
            source_username TEXT,
            source_machine TEXT,
            source_run_id TEXT,
            archive_visibility TEXT NOT NULL DEFAULT 'hidden',
            archive_payload_sha256 TEXT,
            historically_viewable INTEGER NOT NULL DEFAULT 1,
            durably_revivable INTEGER NOT NULL DEFAULT 1,
            restartable INTEGER NOT NULL DEFAULT 0,
            missing_requirements TEXT NOT NULL DEFAULT '[]',
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
            runtime TEXT,
            llm_provider TEXT,
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
            meta_patch TEXT,
            mtime_ns INTEGER NOT NULL,
            size_bytes INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS archive_visibility_projection (
            source_username TEXT NOT NULL,
            source_machine TEXT NOT NULL,
            source_run_id TEXT NOT NULL,
            visibility TEXT NOT NULL CHECK (
                visibility IN ('hidden', 'visible', 'pinned')
            ),
            dismissed_at TEXT,
            revived_at TEXT,
            pinned_at TEXT,
            times_revived INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT,
            PRIMARY KEY(source_username, source_machine, source_run_id)
        )
        """
    )
    conn.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS dismissed_bundle_search_fts
        USING fts5(bundle_path UNINDEXED, archive_search_text)
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
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dismissed_bundle_archive_key "
        "ON dismissed_bundle_summaries(source_username, source_machine, source_run_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dismissed_bundle_visibility "
        "ON dismissed_bundle_summaries(archive_visibility)"
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
            bundle_path, agent_id, raw_suffix, shard, filename,
            source_username, source_machine, source_run_id, archive_visibility,
            archive_payload_sha256, historically_viewable, durably_revivable,
            restartable, missing_requirements, agent_type, cl_name, agent_name,
            status, start_time, stop_time, dismissed_at, revived_at,
            times_revived, project_file, project_name, model, runtime,
            llm_provider, vcs_provider, workflow, is_workflow_child,
            parent_timestamp, step_index, step_name, step_type,
            retry_of_timestamp, retried_as_timestamp, retry_chain_root_timestamp,
            retry_attempt, meta_changespec, meta_patch, mtime_ns, size_bytes
        )
        VALUES (
            :bundle_path, :agent_id, :raw_suffix, :shard, :filename,
            :source_username, :source_machine, :source_run_id,
            :archive_visibility, :archive_payload_sha256,
            :historically_viewable, :durably_revivable, :restartable,
            :missing_requirements, :agent_type, :cl_name, :agent_name,
            :status, :start_time, :stop_time, :dismissed_at, :revived_at,
            :times_revived, :project_file, :project_name, :model, :runtime,
            :llm_provider, :vcs_provider, :workflow, :is_workflow_child,
            :parent_timestamp, :step_index, :step_name, :step_type,
            :retry_of_timestamp, :retried_as_timestamp,
            :retry_chain_root_timestamp, :retry_attempt, :meta_changespec,
            :meta_patch, :mtime_ns, :size_bytes
        )
        ON CONFLICT(bundle_path) DO UPDATE SET
            agent_id=excluded.agent_id,
            raw_suffix=excluded.raw_suffix,
            shard=excluded.shard,
            filename=excluded.filename,
            source_username=excluded.source_username,
            source_machine=excluded.source_machine,
            source_run_id=excluded.source_run_id,
            archive_visibility=excluded.archive_visibility,
            archive_payload_sha256=excluded.archive_payload_sha256,
            historically_viewable=excluded.historically_viewable,
            durably_revivable=excluded.durably_revivable,
            restartable=excluded.restartable,
            missing_requirements=excluded.missing_requirements,
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
            runtime=excluded.runtime,
            llm_provider=excluded.llm_provider,
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
            meta_patch=excluded.meta_patch,
            mtime_ns=excluded.mtime_ns,
            size_bytes=excluded.size_bytes
        """,
        _summary_sql_params(summary, mtime_ns, size_bytes),
    )
    if summary.source_username and summary.source_machine and summary.source_run_id:
        conn.execute(
            """
            INSERT INTO archive_visibility_projection (
                source_username, source_machine, source_run_id, visibility,
                dismissed_at, updated_at
            )
            VALUES (
                :source_username, :source_machine, :source_run_id,
                :archive_visibility, :dismissed_at, :dismissed_at
            )
            ON CONFLICT(source_username, source_machine, source_run_id)
            DO NOTHING
            """,
            _summary_sql_params(summary, mtime_ns, size_bytes),
        )


def set_visibility_for_suffixes(
    conn: sqlite3.Connection,
    suffixes: set[str],
    visibility: str,
    *,
    revived_at: str | None = None,
    dismissed_at: str | None = None,
    pinned_at: str | None = None,
) -> int:
    """Update the local visibility projection for all indexed suffix rows."""

    if not suffixes:
        return 0
    rows = conn.execute(
        "SELECT DISTINCT source_username, source_machine, source_run_id, bundle_path "
        "FROM dismissed_bundle_summaries "
        f"WHERE raw_suffix IN ({','.join('?' for _ in suffixes)})",
        tuple(sorted(suffixes)),
    ).fetchall()
    changed = 0
    for row in rows:
        username = row["source_username"]
        machine = row["source_machine"]
        run_id = row["source_run_id"]
        if username and machine and run_id:
            conn.execute(
                """
                INSERT INTO archive_visibility_projection (
                    source_username, source_machine, source_run_id, visibility,
                    dismissed_at, revived_at, pinned_at, times_revived, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, ?, ?))
                ON CONFLICT(source_username, source_machine, source_run_id)
                DO UPDATE SET
                    visibility=excluded.visibility,
                    dismissed_at=COALESCE(excluded.dismissed_at, dismissed_at),
                    revived_at=COALESCE(excluded.revived_at, revived_at),
                    pinned_at=COALESCE(excluded.pinned_at, pinned_at),
                    updated_at=COALESCE(
                        excluded.updated_at,
                        archive_visibility_projection.updated_at
                    ),
                    times_revived=archive_visibility_projection.times_revived
                        + excluded.times_revived
                """,
                (
                    username,
                    machine,
                    run_id,
                    visibility,
                    dismissed_at,
                    revived_at,
                    pinned_at,
                    1 if revived_at is not None else 0,
                    revived_at,
                    dismissed_at,
                    pinned_at,
                ),
            )
        conn.execute(
            """
            UPDATE dismissed_bundle_summaries
            SET archive_visibility = ?,
                revived_at = COALESCE(?, revived_at),
                dismissed_at = COALESCE(?, dismissed_at),
                times_revived = times_revived + ?
            WHERE bundle_path = ?
            """,
            (
                visibility,
                revived_at,
                dismissed_at,
                1 if revived_at is not None else 0,
                row["bundle_path"],
            ),
        )
        changed += 1
    return changed


def _summary_sql_params(
    summary: DismissedBundleSummary,
    mtime_ns: int,
    size_bytes: int,
) -> dict[str, object]:
    return {
        "bundle_path": summary.bundle_path,
        "agent_id": summary.agent_id,
        "raw_suffix": summary.raw_suffix,
        "shard": summary.shard,
        "filename": summary.filename,
        "source_username": summary.source_username,
        "source_machine": summary.source_machine,
        "source_run_id": summary.source_run_id,
        "archive_visibility": summary.archive_visibility,
        "archive_payload_sha256": summary.archive_payload_sha256,
        "historically_viewable": int(summary.historically_viewable),
        "durably_revivable": int(summary.durably_revivable),
        "restartable": int(summary.restartable),
        "missing_requirements": json.dumps(list(summary.missing_requirements)),
        "agent_type": summary.agent_type,
        "cl_name": summary.cl_name,
        "agent_name": summary.agent_name,
        "status": summary.status,
        "start_time": summary.start_time,
        "stop_time": summary.stop_time,
        "dismissed_at": summary.dismissed_at,
        "revived_at": summary.revived_at,
        "times_revived": summary.times_revived,
        "project_file": summary.project_file,
        "project_name": summary.project_name,
        "model": summary.model,
        "runtime": summary.runtime,
        "llm_provider": summary.llm_provider,
        "vcs_provider": summary.vcs_provider,
        "workflow": summary.workflow,
        "is_workflow_child": int(summary.is_workflow_child),
        "parent_timestamp": summary.parent_timestamp,
        "step_index": summary.step_index,
        "step_name": summary.step_name,
        "step_type": summary.step_type,
        "retry_of_timestamp": summary.retry_of_timestamp,
        "retried_as_timestamp": summary.retried_as_timestamp,
        "retry_chain_root_timestamp": summary.retry_chain_root_timestamp,
        "retry_attempt": summary.retry_attempt,
        "meta_changespec": summary.meta_changespec,
        "meta_patch": summary.meta_patch,
        "mtime_ns": mtime_ns,
        "size_bytes": size_bytes,
    }
