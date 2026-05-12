"""Public operations for the dismissed bundle summary index."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ._bundle_io import (
    agent_id_for_bundle,
    archive_maintenance_lock,
    archive_payload_hash,
    file_signature,
    index_path_for_root,
    iter_bundle_paths,
    read_bundle,
    required_str,
    shard_for_raw_suffix,
)
from ._models import (
    DEFAULT_ARCHIVE_REVISION,
    DismissedBundleIndexRebuildResult,
    DismissedBundleIndexVerifyResult,
    DismissedBundleSummary,
)
from ._schema import (
    connection,
    rebuild_rows_from_bundles,
    upsert_search_text,
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
            upsert_search_text(conn, summary.bundle_path, bundle)
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


def delete_bundle_summaries_for_paths(root: Path, bundle_paths: set[str]) -> bool:
    """Delete index rows for exact bundle paths."""

    if not bundle_paths:
        return True
    try:
        with write_connection(root) as conn:
            conn.executemany(
                "DELETE FROM dismissed_bundle_search_fts WHERE bundle_path = ?",
                [(path,) for path in sorted(bundle_paths)],
            )
            conn.executemany(
                "DELETE FROM dismissed_bundle_summaries WHERE bundle_path = ?",
                [(path,) for path in sorted(bundle_paths)],
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
        with connection(root) as conn:
            rows = conn.execute(sql, params).fetchall()
        return [summary_from_row(row) for row in rows]
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
        latest_by_agent_id: dict[str, DismissedBundleSummary] = {}
        for summary in summaries:
            current = latest_by_agent_id.get(summary.agent_id)
            if current is None or summary.archive_revision > current.archive_revision:
                latest_by_agent_id[summary.agent_id] = summary
        summaries = list(latest_by_agent_id.values())
    return [Path(summary.bundle_path) for summary in summaries]


def rebuild_index(root: Path) -> DismissedBundleIndexRebuildResult:
    """Rebuild the entire dismissed bundle index from bundle JSON files."""

    indexed = 0
    skipped = 0
    root.mkdir(parents=True, exist_ok=True)
    with archive_maintenance_lock(root):
        with write_connection(root) as conn:
            conn.execute("DELETE FROM dismissed_bundle_summaries")
            conn.execute("DELETE FROM dismissed_bundle_search_fts")
            indexed = rebuild_rows_from_bundles(conn, root)
            bundle_count = len(iter_bundle_paths(root))
            skipped = max(0, bundle_count - indexed)
    return DismissedBundleIndexRebuildResult(
        indexed_rows=indexed,
        skipped_corrupt=skipped,
    )


def next_archive_revision(root: Path, bundle: dict[str, Any]) -> int:
    """Return the next immutable archive revision for *bundle*.

    Trusts the SQLite summary index as the source of truth for the max
    revision already written for this agent_id. The caller's collision
    retry handles edge cases where the index is missing or stale.
    """

    if not index_path_for_root(root).is_file():
        return DEFAULT_ARCHIVE_REVISION
    agent_id = agent_id_for_bundle(bundle)
    try:
        with connection(root) as conn:
            row = conn.execute(
                "SELECT MAX(archive_revision) AS max_revision "
                "FROM dismissed_bundle_summaries WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()
    except (sqlite3.Error, TypeError, ValueError):
        return DEFAULT_ARCHIVE_REVISION
    if row is None or row["max_revision"] is None:
        return DEFAULT_ARCHIVE_REVISION
    try:
        max_revision = int(row["max_revision"])
    except (TypeError, ValueError):
        return DEFAULT_ARCHIVE_REVISION
    if max_revision <= 0:
        return DEFAULT_ARCHIVE_REVISION
    return max_revision + 1


def archive_bundle_path(root: Path, bundle: dict[str, Any], revision: int) -> Path:
    """Return the immutable payload path for one archive revision."""

    raw_suffix = required_str(bundle, "raw_suffix")
    shard = shard_for_raw_suffix(raw_suffix)
    return root / shard / f"{agent_id_for_bundle(bundle)}.{revision}" / "bundle.json"


def verify_index(root: Path) -> DismissedBundleIndexVerifyResult:
    """Compare the index to source bundle files without mutating rows."""

    indexed_paths: set[str] = set()
    stale_rows = 0
    payload_hash_mismatches = 0
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
                try:
                    bundle = read_bundle(path)
                except (OSError, json.JSONDecodeError, ValueError):
                    continue
                expected_hash = bundle.get("archive_payload_sha256")
                if isinstance(expected_hash, str) and expected_hash:
                    if expected_hash != archive_payload_hash(bundle):
                        payload_hash_mismatches += 1
        except sqlite3.Error:
            stale_rows = 1

    valid_paths: set[str] = set()
    valid_search_paths: set[str] = set()
    corrupt = 0
    for path in iter_bundle_paths(root):
        try:
            bundle = read_bundle(path)
            valid_paths.add(str(path))
            text = bundle.get("archive_search_text")
            if isinstance(text, str) and text:
                valid_search_paths.add(str(path))
        except (OSError, json.JSONDecodeError):
            corrupt += 1

    fts_paths: set[str] = set()
    if index_path_for_root(root).is_file():
        try:
            with connection(root, create=False) as conn:
                fts_paths = {
                    str(row["bundle_path"])
                    for row in conn.execute(
                        "SELECT bundle_path FROM dismissed_bundle_search_fts"
                    )
                }
        except sqlite3.Error:
            fts_paths = set()
            stale_rows += 1

    missing = len(valid_paths - indexed_paths)
    fts_missing = len((valid_search_paths & indexed_paths) - fts_paths)
    fts_orphan = len(fts_paths - indexed_paths)
    ok = not (
        stale_rows or missing or fts_missing or fts_orphan or payload_hash_mismatches
    )
    return DismissedBundleIndexVerifyResult(
        ok=ok,
        indexed_rows=len(indexed_paths),
        valid_bundles=len(valid_paths),
        corrupt_bundles=corrupt,
        stale_rows=stale_rows,
        missing_rows=missing,
        fts_missing_rows=fts_missing,
        fts_orphan_rows=fts_orphan,
        payload_hash_mismatches=payload_hash_mismatches,
        orphan_visibility_rows=0,
        orphan_revision_rows=0,
    )
