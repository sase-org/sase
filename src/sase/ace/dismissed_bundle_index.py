"""SQLite summary index for dismissed agent bundle archives."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import parse_filename_timestamp

SCHEMA_VERSION = 1
INDEX_FILENAME = "index.sqlite"

_SHARD_DIR_RE = re.compile(r"^\d{6}$")


@dataclass(frozen=True)
class _DismissedBundleSummary:
    """One indexed dismissed-bundle row."""

    raw_suffix: str
    bundle_path: str
    shard: str
    filename: str
    agent_type: str
    cl_name: str
    agent_name: str | None
    status: str
    start_time: str | None
    stop_time: str | None
    project_file: str | None
    model: str | None
    llm_provider: str | None
    vcs_provider: str | None
    workflow: str | None
    is_workflow_child: bool
    parent_timestamp: str | None
    step_index: int | None
    step_name: str | None
    retry_of_timestamp: str | None
    retried_as_timestamp: str | None
    retry_chain_root_timestamp: str | None
    retry_attempt: int
    meta_changespec: str | None


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


def upsert_bundle_summary(root: Path, path: Path, bundle: dict[str, Any]) -> bool:
    """Insert or update one bundle summary row."""

    try:
        summary = _summary_from_bundle(root, path, bundle)
        with _connect(root) as conn:
            _upsert_summary(conn, summary, _file_signature(path))
        return True
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return False


def delete_bundle_summaries_for_suffixes(root: Path, suffixes: set[str]) -> bool:
    """Delete all parent/child index rows for the given raw suffixes."""

    if not suffixes:
        return True
    try:
        with _connect(root) as conn:
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
        clauses.append("project_file LIKE ?")
        params.append(f"%/{project_name}/%")
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
        with _connect(root, create=False) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_summary_from_row(row) for row in rows]
    except sqlite3.Error:
        return None


def query_bundle_paths_by_suffixes(root: Path, suffixes: set[str]) -> list[Path] | None:
    """Return indexed parent and child bundle paths for *suffixes*."""

    summaries = query_summaries(root, suffixes=suffixes)
    if summaries is None:
        return None
    return [Path(summary.bundle_path) for summary in summaries]


def rebuild_index(root: Path) -> _DismissedBundleIndexRebuildResult:
    """Rebuild the entire dismissed bundle index from bundle JSON files."""

    indexed = 0
    skipped = 0
    root.mkdir(parents=True, exist_ok=True)
    with _connect(root) as conn:
        conn.execute("DELETE FROM dismissed_bundle_summaries")
        for path in _iter_bundle_paths(root):
            try:
                bundle = _read_bundle(path)
                summary = _summary_from_bundle(root, path, bundle)
                _upsert_summary(conn, summary, _file_signature(path))
                indexed += 1
            except (OSError, json.JSONDecodeError, ValueError, TypeError):
                skipped += 1
    return _DismissedBundleIndexRebuildResult(
        indexed_rows=indexed,
        skipped_corrupt=skipped,
    )


def verify_index(root: Path) -> _DismissedBundleIndexVerifyResult:
    """Compare the index to source bundle files without mutating rows."""

    indexed_paths: set[str] = set()
    stale_rows = 0
    if _index_path_for_root(root).is_file():
        try:
            with _connect(root, create=False) as conn:
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
    filename = path.name
    shard = _path_shard(root, path)
    return _DismissedBundleSummary(
        raw_suffix=raw_suffix,
        bundle_path=str(path),
        shard=shard,
        filename=filename,
        agent_type=_string_or_default(bundle.get("agent_type"), "run"),
        cl_name=_string_or_default(bundle.get("cl_name"), "unknown"),
        agent_name=_optional_str(bundle.get("agent_name")),
        status=_string_or_default(bundle.get("status"), "DONE"),
        start_time=_optional_str(bundle.get("start_time")),
        stop_time=_optional_str(bundle.get("stop_time")),
        project_file=_optional_str(bundle.get("project_file")),
        model=_optional_str(bundle.get("model")),
        llm_provider=_optional_str(bundle.get("llm_provider")),
        vcs_provider=_optional_str(bundle.get("vcs_provider")),
        workflow=_optional_str(bundle.get("workflow")),
        is_workflow_child=_is_workflow_child(bundle),
        parent_timestamp=_optional_str(bundle.get("parent_timestamp")),
        step_index=_optional_int(bundle.get("step_index")),
        step_name=_optional_str(bundle.get("step_name")),
        retry_of_timestamp=_optional_str(bundle.get("retry_of_timestamp")),
        retried_as_timestamp=_optional_str(bundle.get("retried_as_timestamp")),
        retry_chain_root_timestamp=_optional_str(
            bundle.get("retry_chain_root_timestamp")
        ),
        retry_attempt=_optional_int(bundle.get("retry_attempt")) or 0,
        meta_changespec=_meta_changespec(bundle),
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
        _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
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
                meta_changespec TEXT,
                mtime_ns INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dismissed_bundle_raw_suffix "
            "ON dismissed_bundle_summaries(raw_suffix)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dismissed_bundle_cl "
            "ON dismissed_bundle_summaries(cl_name, meta_changespec)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dismissed_bundle_project "
            "ON dismissed_bundle_summaries(project_file)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO dismissed_bundle_index_meta(key, value) "
            "VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _upsert_summary(
    conn: sqlite3.Connection,
    summary: _DismissedBundleSummary,
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
            meta_changespec, mtime_ns, size_bytes
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
            meta_changespec=excluded.meta_changespec,
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
            summary.meta_changespec,
            mtime_ns,
            size_bytes,
        ),
    )


def _summary_from_row(row: sqlite3.Row) -> _DismissedBundleSummary:
    return _DismissedBundleSummary(
        raw_suffix=str(row["raw_suffix"]),
        bundle_path=str(row["bundle_path"]),
        shard=str(row["shard"]),
        filename=str(row["filename"]),
        agent_type=str(row["agent_type"]),
        cl_name=str(row["cl_name"]),
        agent_name=_optional_str(row["agent_name"]),
        status=str(row["status"]),
        start_time=_optional_str(row["start_time"]),
        stop_time=_optional_str(row["stop_time"]),
        project_file=_optional_str(row["project_file"]),
        model=_optional_str(row["model"]),
        llm_provider=_optional_str(row["llm_provider"]),
        vcs_provider=_optional_str(row["vcs_provider"]),
        workflow=_optional_str(row["workflow"]),
        is_workflow_child=bool(row["is_workflow_child"]),
        parent_timestamp=_optional_str(row["parent_timestamp"]),
        step_index=_optional_int(row["step_index"]),
        step_name=_optional_str(row["step_name"]),
        retry_of_timestamp=_optional_str(row["retry_of_timestamp"]),
        retried_as_timestamp=_optional_str(row["retried_as_timestamp"]),
        retry_chain_root_timestamp=_optional_str(row["retry_chain_root_timestamp"]),
        retry_attempt=int(row["retry_attempt"]),
        meta_changespec=_optional_str(row["meta_changespec"]),
    )


def _iter_bundle_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    results: list[Path] = []
    for entry in root.iterdir():
        if entry.is_dir() and _SHARD_DIR_RE.match(entry.name):
            results.extend(entry.glob("*.json"))
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
