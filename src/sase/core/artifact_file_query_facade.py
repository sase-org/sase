"""Rust-backed query facade for the tolerant artifact-file index."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from sase.core.artifact_file_types import (
    ARTIFACT_FILE_INDEX_SUPPORTED_SCHEMA_VERSIONS,
    ArtifactFile,
    artifact_file_from_dict,
    default_artifact_files_index_path,
)
from sase.core.artifact_consumption import default_artifact_consumption_log_path
from sase.core.rust import require_rust_binding


ARTIFACT_FILE_QUERY_WIRE_SCHEMA_VERSION = 3
ARTIFACT_FILE_ASSOCIATION_QUERY_WIRE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ArtifactFileSourceIdentity:
    """Identity of the index file a targeted association query actually read."""

    missing: bool
    size: int
    mtime_ns: int
    dev: int
    ino: int


def query_artifact_files(
    index_path: Path | str | None = None,
    *,
    kinds: Sequence[str] | None = None,
    project: str | None = None,
    agent: str | None = None,
    since: str | None = None,
    explicit_only: bool = False,
    unused_only: bool = False,
    query: str | None = None,
    limit: int | None = None,
) -> list[ArtifactFile]:
    """Query indexed artifacts through ``sase_core_rs`` in binding order."""

    _require_query_schema()
    resolved_index = (
        Path(default_artifact_files_index_path() if index_path is None else index_path)
        .expanduser()
        .resolve(strict=False)
    )
    filters: dict[str, object] = {
        "agent": agent,
        "explicit_only": bool(explicit_only),
        "kinds": None if kinds is None else [str(kind) for kind in kinds],
        "limit": limit,
        "project": project,
        "query": query,
        "since": since,
        "unused_only": bool(unused_only),
    }
    if unused_only:
        filters["consumption_log_path"] = str(
            default_artifact_consumption_log_path().expanduser().resolve(strict=False)
        )
    binding = require_rust_binding("artifact_files_query")
    raw_rows = binding(str(resolved_index), filters)
    if not isinstance(raw_rows, list):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file query result: "
            "expected a list"
        )
    return [
        _artifact_file_from_wire(raw_row, row_number=index)
        for index, raw_row in enumerate(raw_rows, start=1)
    ]


def query_artifact_file_associations(
    index_path: Path | str | None = None,
    *,
    agent_artifacts_dir: str,
    project: str | None = None,
    raw_timestamp: str | None = None,
    explicit_only: bool = False,
) -> tuple[list[ArtifactFile], ArtifactFileSourceIdentity]:
    """Return listing-compatible rows for one association, in file order."""

    _require_association_query_schema()
    resolved_index = (
        Path(default_artifact_files_index_path() if index_path is None else index_path)
        .expanduser()
        .resolve(strict=False)
    )
    binding = require_rust_binding("artifact_file_association_query")
    raw = binding(
        str(resolved_index),
        {
            "agent_artifacts_dir": str(agent_artifacts_dir),
            "project": project,
            "raw_timestamp": raw_timestamp,
            "explicit_only": bool(explicit_only),
        },
    )
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file association "
            "query result: expected an object"
        )
    payload = cast(Mapping[str, Any], raw)
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file association "
            "query result: expected rows to be a list"
        )
    rows = [
        _association_row_from_wire(raw_row, row_number=index)
        for index, raw_row in enumerate(raw_rows, start=1)
    ]
    return rows, _source_identity_from_wire(payload.get("source"))


def _require_query_schema() -> None:
    binding = require_rust_binding("artifact_file_query_wire_schema_version")
    version = int(binding())
    if version != ARTIFACT_FILE_QUERY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-file query wire is stale: "
            f"expected {ARTIFACT_FILE_QUERY_WIRE_SCHEMA_VERSION}, got {version}"
        )


def _require_association_query_schema() -> None:
    binding = require_rust_binding(
        "artifact_file_association_query_wire_schema_version"
    )
    version = int(binding())
    if version != ARTIFACT_FILE_ASSOCIATION_QUERY_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs artifact-file association query wire is stale: "
            f"expected {ARTIFACT_FILE_ASSOCIATION_QUERY_WIRE_SCHEMA_VERSION}, "
            f"got {version}"
        )


def _source_identity_from_wire(raw: object) -> ArtifactFileSourceIdentity:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file association "
            "query source identity: expected an object"
        )
    source = cast(Mapping[str, Any], raw)
    missing = source.get("missing", False)
    if not isinstance(missing, bool):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file association "
            "query source identity: missing must be a boolean"
        )
    return ArtifactFileSourceIdentity(
        missing=missing,
        size=_require_identity_int(source, "size"),
        mtime_ns=_require_identity_int(source, "mtime_ns"),
        dev=_require_identity_int(source, "dev"),
        ino=_require_identity_int(source, "ino"),
    )


def _require_identity_int(source: Mapping[str, Any], field: str) -> int:
    value = source.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file association "
            f"query source identity: {field} must be a non-negative integer"
        )
    return value


def _association_row_from_wire(raw: object, *, row_number: int) -> ArtifactFile:
    """Convert one association-query row with listing-reader tolerance."""

    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file association "
            f"query row {row_number}: expected an object"
        )
    try:
        return artifact_file_from_dict(dict(raw))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "sase_core_rs returned an incomplete artifact-file association "
            f"query row {row_number}: {exc}"
        ) from exc


def _artifact_file_from_wire(raw: object, *, row_number: int) -> ArtifactFile:
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file query row "
            f"{row_number}: expected an object"
        )
    row = cast(Mapping[str, Any], raw)
    try:
        schema_version = int(row["schema_version"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file query row "
            f"{row_number}: missing or invalid schema_version"
        ) from exc
    if schema_version not in ARTIFACT_FILE_INDEX_SUPPORTED_SCHEMA_VERSIONS:
        raise RuntimeError(
            "sase_core_rs returned an unsupported artifact-file index row "
            f"schema: {schema_version}"
        )
    _validate_wire_row(row, row_number=row_number)
    try:
        return artifact_file_from_dict(dict(row))
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(
            "sase_core_rs returned an incomplete artifact-file query row "
            f"{row_number}: {exc}"
        ) from exc


def _validate_wire_row(row: Mapping[str, Any], *, row_number: int) -> None:
    for field in ("id", "kind", "label"):
        value = row.get(field)
        if not isinstance(value, str) or not value:
            raise RuntimeError(
                "sase_core_rs returned an incomplete artifact-file query row "
                f"{row_number}: {field} must be a non-empty string"
            )
    path = row.get("path")
    vcs_fields = tuple(
        row.get(field) for field in ("vcs_repo", "vcs_sha", "vcs_relpath")
    )
    has_path = isinstance(path, str) and bool(path)
    has_vcs = all(isinstance(value, str) and bool(value) for value in vcs_fields)
    if not has_path and not has_vcs:
        raise RuntimeError(
            "sase_core_rs returned an incomplete artifact-file query row "
            f"{row_number}: path or complete VCS provenance is required"
        )
    for field in (
        "agent_artifacts_dir",
        "agent_name",
        "created_at",
        "mime_type",
        "project",
        "raw_timestamp",
        "sha256",
        "source_path",
        "workflow",
        "workspace_dir",
        "path",
        "vcs_relpath",
        "vcs_repo",
        "vcs_sha",
    ):
        value = row.get(field)
        if value is not None and not isinstance(value, str):
            raise RuntimeError(
                "sase_core_rs returned an incompatible artifact-file query row "
                f"{row_number}: {field} must be a string or null"
            )
    explicit = row.get("explicit", False)
    if not isinstance(explicit, bool):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file query row "
            f"{row_number}: explicit must be a boolean"
        )
    size_bytes = row.get("size_bytes")
    if size_bytes is not None and (
        not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes < 0
    ):
        raise RuntimeError(
            "sase_core_rs returned an incompatible artifact-file query row "
            f"{row_number}: size_bytes must be a non-negative integer or null"
        )


__all__ = [
    "ARTIFACT_FILE_ASSOCIATION_QUERY_WIRE_SCHEMA_VERSION",
    "ARTIFACT_FILE_QUERY_WIRE_SCHEMA_VERSION",
    "ArtifactFileSourceIdentity",
    "query_artifact_file_associations",
    "query_artifact_files",
]
