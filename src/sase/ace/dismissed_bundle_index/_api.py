"""Public operations for the dismissed bundle summary index."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ._bundle_io import (
    file_signature,
    index_path_for_root,
    iter_bundle_paths,
    read_bundle,
)
from ._models import (
    DismissedBundleIndexRebuildResult,
    DismissedBundleIndexVerifyResult,
    DismissedBundleSummary,
)
from ._schema import (
    connection,
    rebuild_rows_from_bundles,
    upsert_summary,
    write_connection,
)
from ._summary import summary_from_bundle, summary_from_row


def archive_index_exists(root: Path) -> bool:
    """Return whether a dismissed bundle SQLite index exists for *root*."""

    return index_path_for_root(root).is_file()


def index_signature(root: Path) -> tuple[int, int, int, int] | None:
    """Return a cheap signature for the dismissed bundle summary index."""

    db_path = index_path_for_root(root)
    if not db_path.is_file():
        return None

    try:
        stat = db_path.stat()
        with connection(root, create=False) as conn:
            version_row = conn.execute(
                "SELECT value FROM dismissed_bundle_index_meta "
                "WHERE key = 'schema_version'"
            ).fetchone()
            count = conn.execute(
                "SELECT COUNT(*) FROM dismissed_bundle_summaries"
            ).fetchone()[0]
    except (OSError, sqlite3.Error, TypeError, ValueError, IndexError):
        return None

    try:
        version = int(version_row["value"]) if version_row is not None else 0
    except (TypeError, ValueError):
        version = 0
    return (version, stat.st_mtime_ns, stat.st_size, int(count))


@contextmanager
def archive_index_connection(root: Path) -> Iterator[sqlite3.Connection]:
    """Open a schema-checked dismissed bundle index connection."""

    with connection(root) as conn:
        yield conn


def upsert_bundle_summary(root: Path, path: Path, bundle: dict[str, Any]) -> bool:
    """Insert or update one bundle summary row."""

    try:
        summary = summary_from_bundle(root, path, bundle)
        with write_connection(root) as conn:
            upsert_summary(conn, summary, file_signature(path))
        return True
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return False


def delete_bundle_summaries_for_suffixes(root: Path, suffixes: set[str]) -> bool:
    """Delete all parent/child index rows for the given raw suffixes."""

    if not suffixes:
        return True
    try:
        with write_connection(root) as conn:
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
    offset: int | None = None,
) -> list[DismissedBundleSummary] | None:
    """Query summaries, returning ``None`` when no usable index exists."""

    db_path = index_path_for_root(root)
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
        clauses.append("(cl_name = ? OR meta_patch = ?)")
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
    if offset is not None:
        if limit is None:
            sql += " LIMIT -1"
        sql += " OFFSET ?"
        params.append(max(0, offset))

    try:
        with connection(root) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [summary_from_row(row) for row in rows]
    except sqlite3.Error:
        return None


def query_bundle_paths_by_suffixes(
    root: Path,
    suffixes: set[str],
) -> list[Path] | None:
    """Return indexed parent and child bundle paths for *suffixes*."""

    summaries = query_summaries(root, suffixes=suffixes)
    if summaries is None:
        return None
    return [Path(summary.bundle_path) for summary in summaries]


def rebuild_index(root: Path) -> DismissedBundleIndexRebuildResult:
    """Rebuild the entire dismissed bundle index from bundle JSON files."""

    indexed = 0
    skipped = 0
    root.mkdir(parents=True, exist_ok=True)
    with write_connection(root) as conn:
        conn.execute("DELETE FROM dismissed_bundle_summaries")
        indexed = rebuild_rows_from_bundles(conn, root)
        bundle_count = len(iter_bundle_paths(root))
        skipped = max(0, bundle_count - indexed)
    return DismissedBundleIndexRebuildResult(
        indexed_rows=indexed,
        skipped_corrupt=skipped,
    )


def query_summary_identities(root: Path) -> set[tuple[str, str, str | None]] | None:
    """Return distinct ``(agent_type, cl_name, raw_suffix)`` identity rows.

    Dedicated projection query for callers that only need identities (the
    artifact-index dismissed projection), so they never materialize every
    summary object. Applies the same normalization as the summary path:
    blank ``cl_name`` becomes ``'unknown'`` and blank ``raw_suffix``
    becomes ``None``. Returns ``None`` when no usable index exists.
    """

    db_path = index_path_for_root(root)
    if not db_path.is_file():
        return None

    sql = (
        "SELECT DISTINCT agent_type, "
        "CASE WHEN cl_name = '' THEN 'unknown' ELSE cl_name END, "
        "NULLIF(raw_suffix, '') "
        "FROM dismissed_bundle_summaries"
    )
    try:
        with connection(root) as conn:
            rows = conn.execute(sql).fetchall()
    except sqlite3.Error:
        return None
    return {
        (str(row[0]), str(row[1]), None if row[2] is None else str(row[2]))
        for row in rows
    }


def verify_index(root: Path) -> DismissedBundleIndexVerifyResult:
    """Compare the index to source bundle files without mutating rows.

    Verification is signature-based: indexed rows are checked against
    ``stat()`` signatures and the on-disk path set, so the cost is one
    stat per bundle instead of a JSON parse per bundle. Only files absent
    from the index are parsed — without that, a corrupt unindexed file
    would read as permanently "missing" and trigger a full rebuild on
    every verify. JSON validity of indexed rows is rebuild's job.
    """

    indexed: dict[str, tuple[int, int]] = {}
    stale_rows = 0
    if index_path_for_root(root).is_file():
        try:
            with connection(root, create=False) as conn:
                rows = conn.execute(
                    "SELECT bundle_path, mtime_ns, size_bytes "
                    "FROM dismissed_bundle_summaries"
                ).fetchall()
            for row in rows:
                indexed[str(row["bundle_path"])] = (
                    int(row["mtime_ns"]),
                    int(row["size_bytes"]),
                )
        except sqlite3.Error:
            stale_rows = 1

    for bundle_path, signature in indexed.items():
        try:
            if file_signature(Path(bundle_path)) != signature:
                stale_rows += 1
        except OSError:
            stale_rows += 1

    disk_paths = {str(path): path for path in iter_bundle_paths(root)}
    missing = 0
    corrupt = 0
    for path_str, path in disk_paths.items():
        if path_str in indexed:
            continue
        try:
            read_bundle(path)
        except (OSError, json.JSONDecodeError, ValueError):
            corrupt += 1
            continue
        missing += 1

    ok = stale_rows == 0 and missing == 0
    return DismissedBundleIndexVerifyResult(
        ok=ok,
        indexed_rows=len(indexed),
        valid_bundles=len(disk_paths) - corrupt,
        corrupt_bundles=corrupt,
        stale_rows=stale_rows,
        missing_rows=missing,
    )
