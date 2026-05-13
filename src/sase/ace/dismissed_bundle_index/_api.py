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


def verify_index(root: Path) -> DismissedBundleIndexVerifyResult:
    """Compare the index to source bundle files without mutating rows."""

    indexed_paths: set[str] = set()
    stale_rows = 0
    if index_path_for_root(root).is_file():
        try:
            with connection(root, create=False) as conn:
                rows = conn.execute(
                    "SELECT bundle_path, mtime_ns, size_bytes "
                    "FROM dismissed_bundle_summaries"
                ).fetchall()
            for row in rows:
                bundle_path = str(row["bundle_path"])
                indexed_paths.add(bundle_path)
                path = Path(bundle_path)
                try:
                    mtime_ns, size_bytes = file_signature(path)
                except OSError:
                    stale_rows += 1
                    continue
                if mtime_ns != row["mtime_ns"] or size_bytes != row["size_bytes"]:
                    stale_rows += 1
        except sqlite3.Error:
            stale_rows = 1

    valid_paths: set[str] = set()
    corrupt = 0
    for path in iter_bundle_paths(root):
        try:
            read_bundle(path)
            valid_paths.add(str(path))
        except (OSError, json.JSONDecodeError):
            corrupt += 1

    missing = len(valid_paths - indexed_paths)
    ok = stale_rows == 0 and missing == 0
    return DismissedBundleIndexVerifyResult(
        ok=ok,
        indexed_rows=len(indexed_paths),
        valid_bundles=len(valid_paths),
        corrupt_bundles=corrupt,
        stale_rows=stale_rows,
        missing_rows=missing,
    )
