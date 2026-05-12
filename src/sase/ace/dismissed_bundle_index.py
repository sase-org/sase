"""SQLite summary index for dismissed agent bundle archives."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from sase.core.paths import parse_filename_timestamp

SCHEMA_VERSION = 2
INDEX_FILENAME = "index.sqlite"
DEFAULT_ARCHIVE_REVISION = 1
LEGACY_BUNDLE_SCHEMA_VERSION = 0
ERROR_MESSAGE_EXCERPT_CHARS = 500

_SHARD_DIR_RE = re.compile(r"^\d{6}$")


@dataclass(frozen=True)
class _DismissedBundleSummary:
    """One indexed dismissed-bundle row."""

    agent_id: str
    raw_suffix: str
    bundle_path: str
    shard: str
    filename: str
    archive_revision: int
    bundle_schema_version: int
    agent_type: str
    cl_name: str
    agent_name: str | None
    status: str
    start_time: str | None
    stop_time: str | None
    dismissed_at: str | None
    revived_at: str | None
    times_revived: int
    project_file: str | None
    project_name: str | None
    model: str | None
    llm_provider: str | None
    runtime: str | None
    vcs_provider: str | None
    workflow: str | None
    is_workflow_child: bool
    parent_timestamp: str | None
    step_index: int | None
    step_name: str | None
    step_type: str | None
    retry_of_timestamp: str | None
    retried_as_timestamp: str | None
    retry_chain_root_timestamp: str | None
    retry_attempt: int
    meta_changespec: str | None
    cost_usd_micros: int | None
    input_tokens: int | None
    output_tokens: int | None
    error_message_excerpt: str | None


@dataclass(frozen=True)
class _DismissedBundleIndexVerifyResult:
    """Verification result for the dismissed bundle summary index."""

    ok: bool
    indexed_rows: int
    valid_bundles: int
    corrupt_bundles: int
    stale_rows: int
    missing_rows: int


@dataclass(frozen=True)
class _DismissedBundleIndexRebuildResult:
    """Rebuild result for the dismissed bundle summary index."""

    indexed_rows: int
    skipped_corrupt: int


def _index_path_for_root(root: Path) -> Path:
    """Return the SQLite index path for *root*."""

    return root / INDEX_FILENAME


def archive_index_exists(root: Path) -> bool:
    """Return whether a dismissed bundle SQLite index exists for *root*."""

    return _index_path_for_root(root).is_file()


@contextmanager
def archive_index_connection(root: Path) -> Iterator[sqlite3.Connection]:
    """Open a schema-checked dismissed bundle index connection."""

    with _connection(root) as conn:
        yield conn


def upsert_bundle_summary(root: Path, path: Path, bundle: dict[str, Any]) -> bool:
    """Insert or update one bundle summary row."""

    try:
        summary = _summary_from_bundle(root, path, bundle)
        with _write_connection(root) as conn:
            _upsert_summary(conn, summary, _file_signature(path))
            _upsert_search_text(conn, summary.bundle_path, bundle)
        return True
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return False


def delete_bundle_summaries_for_suffixes(root: Path, suffixes: set[str]) -> bool:
    """Delete all parent/child index rows for the given raw suffixes."""

    if not suffixes:
        return True
    try:
        with _write_connection(root) as conn:
            conn.executemany(
                """
                DELETE FROM dismissed_bundle_search_fts
                WHERE bundle_path IN (
                    SELECT bundle_path FROM dismissed_bundle_summaries
                    WHERE raw_suffix = ?
                )
                """,
                [(suffix,) for suffix in suffixes],
            )
            conn.executemany(
                "DELETE FROM dismissed_bundle_summaries WHERE raw_suffix = ?",
                [(suffix,) for suffix in suffixes],
            )
        return True
    except sqlite3.Error:
        return False


def query_summaries(
    root: Path,
    *,
    suffixes: set[str] | None = None,
    cl_name: str | None = None,
    project_name: str | None = None,
    top_level_only: bool = False,
    limit: int | None = None,
) -> list[_DismissedBundleSummary] | None:
    """Query summaries, returning ``None`` when no usable index exists."""

    db_path = _index_path_for_root(root)
    if not db_path.is_file():
        return None

    clauses: list[str] = []
    params: list[Any] = []
    if suffixes is not None:
        if not suffixes:
            return []
        placeholders = ",".join("?" for _ in suffixes)
        clauses.append(f"raw_suffix IN ({placeholders})")
        params.extend(sorted(suffixes))
    if cl_name is not None:
        clauses.append("(cl_name = ? OR meta_changespec = ?)")
        params.extend([cl_name, cl_name])
    if project_name is not None:
        clauses.append("(project_name = ? OR project_file LIKE ?)")
        params.extend([project_name, f"%/{project_name}/%"])
    if top_level_only:
        clauses.append("is_workflow_child = 0")

    sql = "SELECT * FROM dismissed_bundle_summaries"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY COALESCE(start_time, raw_suffix) DESC, filename ASC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(max(0, limit))

    try:
        with _connection(root) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_summary_from_row(row) for row in rows]
    except sqlite3.Error:
        return None


def query_bundle_paths_by_suffixes(
    root: Path,
    suffixes: set[str],
    *,
    latest_only: bool = False,
) -> list[Path] | None:
    """Return indexed parent and child bundle paths for *suffixes*."""

    summaries = query_summaries(root, suffixes=suffixes)
    if summaries is None:
        return None
    if latest_only:
        latest_by_agent_id: dict[str, _DismissedBundleSummary] = {}
        for summary in summaries:
            current = latest_by_agent_id.get(summary.agent_id)
            if current is None or summary.archive_revision > current.archive_revision:
                latest_by_agent_id[summary.agent_id] = summary
        summaries = list(latest_by_agent_id.values())
    return [Path(summary.bundle_path) for summary in summaries]


def rebuild_index(root: Path) -> _DismissedBundleIndexRebuildResult:
    """Rebuild the entire dismissed bundle index from bundle JSON files."""

    indexed = 0
    skipped = 0
    root.mkdir(parents=True, exist_ok=True)
    with _archive_maintenance_lock(root):
        with _write_connection(root) as conn:
            conn.execute("DELETE FROM dismissed_bundle_summaries")
            conn.execute("DELETE FROM dismissed_bundle_search_fts")
            indexed = _rebuild_rows_from_bundles(conn, root)
            bundle_count = len(_iter_bundle_paths(root))
            skipped = max(0, bundle_count - indexed)
    return _DismissedBundleIndexRebuildResult(
        indexed_rows=indexed,
        skipped_corrupt=skipped,
    )


def next_archive_revision(root: Path, bundle: dict[str, Any]) -> int:
    """Return the next immutable archive revision for *bundle*."""

    agent_id = _agent_id_for_bundle(bundle)
    max_revision = 0
    if _index_path_for_root(root).is_file():
        try:
            with _connection(root) as conn:
                row = conn.execute(
                    "SELECT MAX(archive_revision) AS max_revision "
                    "FROM dismissed_bundle_summaries WHERE agent_id = ?",
                    (agent_id,),
                ).fetchone()
            if row is not None and row["max_revision"] is not None:
                max_revision = max(max_revision, int(row["max_revision"]))
        except (sqlite3.Error, TypeError, ValueError):
            pass

    for path in _iter_bundle_paths(root):
        try:
            existing = _read_bundle(path)
            if _agent_id_for_bundle(existing) != agent_id:
                continue
            max_revision = max(
                max_revision,
                _positive_int_or_default(
                    existing.get("archive_revision"),
                    DEFAULT_ARCHIVE_REVISION,
                ),
            )
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            continue
    return max_revision + 1 if max_revision else DEFAULT_ARCHIVE_REVISION


def archive_bundle_path(root: Path, bundle: dict[str, Any], revision: int) -> Path:
    """Return the immutable payload path for one archive revision."""

    raw_suffix = _required_str(bundle, "raw_suffix")
    shard = _shard_for_raw_suffix(raw_suffix)
    return root / shard / f"{_agent_id_for_bundle(bundle)}.{revision}" / "bundle.json"


@contextmanager
def _archive_maintenance_lock(root: Path) -> Iterator[None]:
    """Serialize long-running archive maintenance against other maintainers."""

    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".archive.lock"
    with open(lock_path, "a+b") as lock_file:
        try:
            import fcntl
        except ImportError:  # pragma: no cover - Windows fallback
            yield
            return
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def verify_index(root: Path) -> _DismissedBundleIndexVerifyResult:
    """Compare the index to source bundle files without mutating rows."""

    indexed_paths: set[str] = set()
    stale_rows = 0
    if _index_path_for_root(root).is_file():
        try:
            with _connection(root, create=False) as conn:
                rows = conn.execute(
                    "SELECT bundle_path, mtime_ns, size_bytes "
                    "FROM dismissed_bundle_summaries"
                ).fetchall()
            for row in rows:
                bundle_path = str(row["bundle_path"])
                indexed_paths.add(bundle_path)
                path = Path(bundle_path)
                try:
                    mtime_ns, size_bytes = _file_signature(path)
                except OSError:
                    stale_rows += 1
                    continue
                if mtime_ns != row["mtime_ns"] or size_bytes != row["size_bytes"]:
                    stale_rows += 1
        except sqlite3.Error:
            stale_rows = 1

    valid_paths: set[str] = set()
    corrupt = 0
    for path in _iter_bundle_paths(root):
        try:
            _read_bundle(path)
            valid_paths.add(str(path))
        except (OSError, json.JSONDecodeError):
            corrupt += 1

    missing = len(valid_paths - indexed_paths)
    ok = stale_rows == 0 and missing == 0
    return _DismissedBundleIndexVerifyResult(
        ok=ok,
        indexed_rows=len(indexed_paths),
        valid_bundles=len(valid_paths),
        corrupt_bundles=corrupt,
        stale_rows=stale_rows,
        missing_rows=missing,
    )


def _summary_from_bundle(
    root: Path,
    path: Path,
    bundle: dict[str, Any],
) -> _DismissedBundleSummary:
    """Build a summary row from a bundle JSON object."""

    raw_suffix = _required_str(bundle, "raw_suffix")
    filename = _display_filename(root, path)
    shard = _path_shard(root, path)
    project_file = _optional_str(bundle.get("project_file"))
    llm_provider = _optional_str(bundle.get("llm_provider"))
    return _DismissedBundleSummary(
        agent_id=_agent_id_for_bundle(bundle),
        raw_suffix=raw_suffix,
        bundle_path=str(path),
        shard=shard,
        filename=filename,
        archive_revision=_positive_int_or_default(
            bundle.get("archive_revision"), DEFAULT_ARCHIVE_REVISION
        ),
        bundle_schema_version=_nonnegative_int_or_default(
            bundle.get("bundle_schema_version"), LEGACY_BUNDLE_SCHEMA_VERSION
        ),
        agent_type=_string_or_default(bundle.get("agent_type"), "run"),
        cl_name=_string_or_default(bundle.get("cl_name"), "unknown"),
        agent_name=_optional_str(bundle.get("agent_name")),
        status=_string_or_default(bundle.get("status"), "DONE"),
        start_time=_optional_str(bundle.get("start_time")),
        stop_time=_optional_str(bundle.get("stop_time")),
        dismissed_at=_dismissed_at(bundle, path),
        revived_at=_optional_str(bundle.get("revived_at")),
        times_revived=_nonnegative_int_or_default(bundle.get("times_revived"), 0),
        project_file=project_file,
        project_name=_project_name(project_file),
        model=_optional_str(bundle.get("model")),
        llm_provider=llm_provider,
        runtime=_runtime(bundle, llm_provider),
        vcs_provider=_optional_str(bundle.get("vcs_provider")),
        workflow=_optional_str(bundle.get("workflow")),
        is_workflow_child=_is_workflow_child(bundle),
        parent_timestamp=_optional_str(bundle.get("parent_timestamp")),
        step_index=_optional_int(bundle.get("step_index")),
        step_name=_optional_str(bundle.get("step_name")),
        step_type=_optional_str(bundle.get("step_type")),
        retry_of_timestamp=_optional_str(bundle.get("retry_of_timestamp")),
        retried_as_timestamp=_optional_str(bundle.get("retried_as_timestamp")),
        retry_chain_root_timestamp=_optional_str(
            bundle.get("retry_chain_root_timestamp")
        ),
        retry_attempt=_optional_int(bundle.get("retry_attempt")) or 0,
        meta_changespec=_meta_changespec(bundle),
        cost_usd_micros=_optional_int(bundle.get("cost_usd_micros")),
        input_tokens=_usage_int(bundle, "input_tokens"),
        output_tokens=_usage_int(bundle, "output_tokens"),
        error_message_excerpt=_error_message_excerpt(bundle),
    )


def _connect(root: Path, *, create: bool = True) -> sqlite3.Connection:
    if create:
        root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_index_path_for_root(root), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    if create:
        _ensure_schema(conn, root)
    return conn


@contextmanager
def _connection(root: Path, *, create: bool = True) -> Iterator[sqlite3.Connection]:
    """Open an index connection, commit/rollback work, and always close it."""

    with closing(_connect(root, create=create)) as conn:
        with conn:
            yield conn


@contextmanager
def _write_connection(root: Path) -> Iterator[sqlite3.Connection]:
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
    _rebuild_rows_from_bundles(conn, root)


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


def _rebuild_rows_from_bundles(conn: sqlite3.Connection, root: Path) -> int:
    indexed = 0
    for path in _iter_bundle_paths(root):
        try:
            bundle = _read_bundle(path)
            _backfill_archive_projection(path, bundle)
            summary = _summary_from_bundle(root, path, bundle)
            _upsert_summary(conn, summary, _file_signature(path))
            _upsert_search_text(conn, summary.bundle_path, bundle)
            indexed += 1
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            continue
    return indexed


def _backfill_archive_projection(path: Path, bundle: dict[str, Any]) -> None:
    from .archive_search_text import normalize_archive_bundle_projection

    if not normalize_archive_bundle_projection(bundle):
        return
    path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")


def _upsert_summary(
    conn: sqlite3.Connection,
    summary: _DismissedBundleSummary,
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


def _upsert_search_text(
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


def _summary_from_row(row: sqlite3.Row) -> _DismissedBundleSummary:
    return _DismissedBundleSummary(
        agent_id=str(row["agent_id"]),
        raw_suffix=str(row["raw_suffix"]),
        bundle_path=str(row["bundle_path"]),
        shard=str(row["shard"]),
        filename=str(row["filename"]),
        archive_revision=int(row["archive_revision"]),
        bundle_schema_version=int(row["bundle_schema_version"]),
        agent_type=str(row["agent_type"]),
        cl_name=str(row["cl_name"]),
        agent_name=_optional_str(row["agent_name"]),
        status=str(row["status"]),
        start_time=_optional_str(row["start_time"]),
        stop_time=_optional_str(row["stop_time"]),
        dismissed_at=_optional_str(row["dismissed_at"]),
        revived_at=_optional_str(row["revived_at"]),
        times_revived=int(row["times_revived"]),
        project_file=_optional_str(row["project_file"]),
        project_name=_optional_str(row["project_name"]),
        model=_optional_str(row["model"]),
        llm_provider=_optional_str(row["llm_provider"]),
        runtime=_optional_str(row["runtime"]),
        vcs_provider=_optional_str(row["vcs_provider"]),
        workflow=_optional_str(row["workflow"]),
        is_workflow_child=bool(row["is_workflow_child"]),
        parent_timestamp=_optional_str(row["parent_timestamp"]),
        step_index=_optional_int(row["step_index"]),
        step_name=_optional_str(row["step_name"]),
        step_type=_optional_str(row["step_type"]),
        retry_of_timestamp=_optional_str(row["retry_of_timestamp"]),
        retried_as_timestamp=_optional_str(row["retried_as_timestamp"]),
        retry_chain_root_timestamp=_optional_str(row["retry_chain_root_timestamp"]),
        retry_attempt=int(row["retry_attempt"]),
        meta_changespec=_optional_str(row["meta_changespec"]),
        cost_usd_micros=_optional_int(row["cost_usd_micros"]),
        input_tokens=_optional_int(row["input_tokens"]),
        output_tokens=_optional_int(row["output_tokens"]),
        error_message_excerpt=_optional_str(row["error_message_excerpt"]),
    )


def _iter_bundle_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    results: list[Path] = []
    for entry in root.iterdir():
        if entry.is_dir() and _SHARD_DIR_RE.match(entry.name):
            results.extend(path for path in entry.glob("*.json") if path.is_file())
            results.extend(
                path for path in entry.glob("*/bundle.json") if path.is_file()
            )
    for path in root.glob("*.json"):
        if path.is_file():
            results.append(path)
    return results


def _read_bundle(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("bundle JSON must be an object")
    return data


def _file_signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_size


def _agent_id_for_bundle(bundle: dict[str, Any]) -> str:
    raw_suffix = _required_str(bundle, "raw_suffix")
    agent_type = _string_or_default(bundle.get("agent_type"), "run")
    project_file = _optional_str(bundle.get("project_file")) or ""
    step_index = _optional_int(bundle.get("step_index"))
    step_index_text = "" if step_index is None else str(step_index)
    payload = "\0".join((project_file, raw_suffix, agent_type, step_index_text))
    return sha256(payload.encode("utf-8")).hexdigest()


def _shard_for_raw_suffix(raw_suffix: str) -> str:
    ts = parse_filename_timestamp(raw_suffix)
    if ts is not None:
        return ts.strftime("%Y%m")
    if len(raw_suffix) >= 6 and raw_suffix[:6].isdigit():
        return raw_suffix[:6]
    return "000101"


def _path_shard(root: Path, path: Path) -> str:
    try:
        parent = path.parent.relative_to(root)
    except ValueError:
        parent = path.parent
    if parent.parts and _SHARD_DIR_RE.match(parent.parts[0]):
        return parent.parts[0]
    ts = parse_filename_timestamp(path.name)
    if ts is not None:
        return ts.strftime("%Y%m")
    return ""


def _display_filename(root: Path, path: Path) -> str:
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.name
    if path.name == "bundle.json" and len(relative.parts) >= 3:
        return "/".join(relative.parts[-2:])
    return path.name


def _required_str(bundle: dict[str, Any], key: str) -> str:
    value = bundle.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"bundle missing {key}")
    return value


def _string_or_default(value: object, default: str) -> str:
    if isinstance(value, str) and value:
        return value
    return default


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _positive_int_or_default(value: object, default: int) -> int:
    parsed = _optional_int(value)
    if parsed is None or parsed <= 0:
        return default
    return parsed


def _nonnegative_int_or_default(value: object, default: int) -> int:
    parsed = _optional_int(value)
    if parsed is None or parsed < 0:
        return default
    return parsed


def _dismissed_at(bundle: dict[str, Any], path: Path) -> str | None:
    explicit = _optional_str(bundle.get("dismissed_at"))
    if explicit:
        return explicit
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).isoformat()
    except OSError:
        return None


def _project_name(project_file: str | None) -> str | None:
    if not project_file:
        return None
    parent_name = Path(project_file).parent.name
    if parent_name:
        return parent_name
    stem = Path(project_file).stem
    return stem or None


def _runtime(bundle: dict[str, Any], llm_provider: str | None) -> str | None:
    return _optional_str(bundle.get("runtime")) or llm_provider


def _usage_int(bundle: dict[str, Any], key: str) -> int | None:
    direct = _optional_int(bundle.get(key))
    if direct is not None:
        return direct
    usage = bundle.get("usage")
    if isinstance(usage, dict):
        return _optional_int(usage.get(key))
    return None


def _error_message_excerpt(bundle: dict[str, Any]) -> str | None:
    value = _optional_str(bundle.get("error_message"))
    if not value:
        value = _optional_str(bundle.get("error_traceback"))
    if not value:
        return None
    return value[:ERROR_MESSAGE_EXCERPT_CHARS]


def _is_workflow_child(bundle: dict[str, Any]) -> bool:
    explicit = bundle.get("is_workflow_child")
    if isinstance(explicit, bool):
        return explicit
    return (
        bundle.get("parent_workflow") is not None
        or bundle.get("parent_timestamp") is not None
    )


def _meta_changespec(bundle: dict[str, Any]) -> str | None:
    step_output = bundle.get("step_output")
    if not isinstance(step_output, dict):
        return None
    meta_changespec = step_output.get("meta_changespec")
    if meta_changespec:
        return str(meta_changespec).strip()
    meta_new_cl = step_output.get("meta_new_cl")
    if meta_new_cl:
        value = str(meta_new_cl).strip()
        paren_idx = value.rfind(" (")
        if paren_idx > 0:
            return value[:paren_idx].strip()
        return value
    return None
