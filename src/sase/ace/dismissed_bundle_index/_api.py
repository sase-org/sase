"""Public operations for the Rust-backed dismissed bundle summary index."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding

from ._bundle_io import index_path_for_root
from ._models import (
    SCHEMA_VERSION,
    DismissedBundleIndexProgress,
    DismissedBundleIndexRebuildResult,
    DismissedBundleIndexVerifyResult,
    DismissedBundleSummary,
)

_BACKEND_ERRORS = (
    OSError,
    RuntimeError,
    TypeError,
    ValueError,
    IndexError,
    KeyError,
)


def dismissed_bundle_index_progress(root: Path) -> DismissedBundleIndexProgress:
    """Return rebuild state without opening the database or bundle files."""

    try:
        payload = _mapping(
            require_rust_binding("dismissed_bundle_index_progress")(str(root))
        )
        return DismissedBundleIndexProgress(
            rebuilding=bool(payload.get("rebuilding", False)),
            indexed_rows=int(payload.get("indexed_rows", 0)),
        )
    except _BACKEND_ERRORS:
        return DismissedBundleIndexProgress(rebuilding=False, indexed_rows=0)


def archive_index_exists(root: Path) -> bool:
    """Return whether a dismissed bundle index file exists for *root*."""

    return index_path_for_root(root).is_file()


def index_signature(root: Path) -> tuple[int, int, int, int] | None:
    """Return a cheap signature for the dismissed bundle summary index."""

    try:
        value = require_rust_binding("dismissed_bundle_index_signature")(str(root))
        if value is None:
            return None
        payload = _mapping(value)
        return (
            int(payload["schema_version"]),
            int(payload["mtime_ns"]),
            int(payload["size_bytes"]),
            int(payload["row_count"]),
        )
    except _BACKEND_ERRORS:
        return None


def upsert_bundle_summary(root: Path, path: Path, bundle: dict[str, Any]) -> bool:
    """Insert or update one bundle summary row."""

    try:
        bundle_json = json.dumps(
            bundle,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        result = require_rust_binding("upsert_dismissed_bundle_summary")(
            str(root), str(path), bundle_json
        )
        return bool(result)
    except _BACKEND_ERRORS:
        return False


def delete_bundle_summaries_for_suffixes(root: Path, suffixes: set[str]) -> bool:
    """Delete all parent/child index rows for the given raw suffixes."""

    if not suffixes:
        return True
    try:
        result = require_rust_binding("delete_dismissed_bundle_summaries_for_suffixes")(
            str(root), sorted(suffixes)
        )
        return bool(result)
    except _BACKEND_ERRORS:
        return False


def query_summaries(
    root: Path,
    *,
    suffixes: set[str] | None = None,
    cl_name: str | None = None,
    project_name: str | None = None,
    top_level_only: bool = False,
    visibility: str | None = "hidden",
    limit: int | None = None,
    offset: int | None = None,
) -> list[DismissedBundleSummary] | None:
    """Query summaries, returning ``None`` when no usable index exists."""

    request = {
        "suffixes": sorted(suffixes) if suffixes is not None else None,
        "cl_name": cl_name,
        "project_name": project_name,
        "top_level_only": top_level_only,
        "visibility": visibility,
        "limit": limit,
        "offset": offset,
    }
    try:
        rows = require_rust_binding("query_dismissed_bundle_summaries")(
            str(root), request
        )
        if rows is None:
            return None
        return [_summary_from_wire(_mapping(row)) for row in rows]
    except _BACKEND_ERRORS:
        return None


def query_bundle_paths_by_suffixes(
    root: Path,
    suffixes: set[str],
) -> list[Path] | None:
    """Return indexed parent and child bundle paths for *suffixes*."""

    try:
        paths = require_rust_binding("query_dismissed_bundle_paths_by_suffixes")(
            str(root), sorted(suffixes)
        )
        if paths is None:
            return None
        return [Path(path) for path in paths]
    except _BACKEND_ERRORS:
        return None


def set_archive_visibility_for_suffixes(
    root: Path,
    suffixes: set[str],
    visibility: str,
    *,
    revived_at: str | None = None,
    dismissed_at: str | None = None,
    pinned_at: str | None = None,
) -> int:
    """Set local visibility for all indexed rows matching *suffixes*."""

    try:
        changed = require_rust_binding("set_dismissed_bundle_visibility_for_suffixes")(
            str(root),
            sorted(suffixes),
            visibility,
            revived_at,
            dismissed_at,
            pinned_at,
        )
        return int(changed)
    except _BACKEND_ERRORS:
        return 0


def rebuild_index(root: Path) -> DismissedBundleIndexRebuildResult:
    """Rebuild the entire dismissed bundle index from bundle JSON files."""

    payload = _mapping(
        require_rust_binding("rebuild_dismissed_bundle_index")(str(root))
    )
    return DismissedBundleIndexRebuildResult(
        indexed_rows=int(payload["indexed_rows"]),
        skipped_corrupt=int(payload["skipped_corrupt"]),
    )


def query_summary_identities(root: Path) -> set[tuple[str, str, str | None]] | None:
    """Return hidden ``(agent_type, cl_name, raw_suffix)`` identities.

    Returns ``None`` when no usable index exists.
    """

    signature = index_signature(root)
    if signature is None or signature[0] != SCHEMA_VERSION:
        return None
    if signature[3] == 0:
        return set()

    try:
        rows = require_rust_binding("query_dismissed_bundle_summary_identities")(
            str(root)
        )
        if rows is None:
            return None
        return {
            (
                str(row["agent_type"]),
                str(row["cl_name"]),
                None if row.get("raw_suffix") is None else str(row["raw_suffix"]),
            )
            for row in (_mapping(value) for value in rows)
        }
    except _BACKEND_ERRORS:
        return None


def verify_index(root: Path) -> DismissedBundleIndexVerifyResult:
    """Compare the index to source bundle files without mutating rows."""

    try:
        payload = _mapping(
            require_rust_binding("verify_agent_archive_index")(str(root))
        )
        return DismissedBundleIndexVerifyResult(
            ok=bool(payload["ok"]),
            indexed_rows=int(payload["indexed_rows"]),
            valid_bundles=int(payload["valid_bundles"]),
            corrupt_bundles=int(payload["corrupt_bundles"]),
            stale_rows=int(payload["stale_rows"]),
            missing_rows=int(payload["missing_rows"]),
        )
    except _BACKEND_ERRORS:
        return DismissedBundleIndexVerifyResult(
            ok=False,
            indexed_rows=0,
            valid_bundles=0,
            corrupt_bundles=0,
            stale_rows=1,
            missing_rows=0,
        )


def _summary_from_wire(row: Mapping[str, Any]) -> DismissedBundleSummary:
    values: dict[str, Any] = {}
    for field in fields(DismissedBundleSummary):
        wire_name = "meta_patch" if field.name == "meta_changespec" else field.name
        value = row[wire_name]
        if field.name == "missing_requirements":
            value = tuple(value)
        elif field.name in {"times_revived", "retry_attempt"}:
            value = int(value)
        elif field.name in {
            "historically_viewable",
            "durably_revivable",
            "restartable",
            "is_workflow_child",
        }:
            value = bool(value)
        values[field.name] = value
    return DismissedBundleSummary(**values)


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError("Rust archive binding returned a non-object wire value")
    return value
