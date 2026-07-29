"""Inspection, backfill, and verification for the artifact-file index."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from sase.core.artifact_file_explicit import (
    artifact_file_index_lock,
    read_artifact_file_index_document_unlocked,
    write_artifact_file_index_unlocked,
)
from sase.core.artifact_file_helpers import artifact_file_mime_type, hash_file
from sase.core.artifact_file_types import (
    ARTIFACT_FILE_INDEX_SUPPORTED_SCHEMA_VERSIONS,
    ArtifactFile,
    default_artifact_files_index_path,
)


@dataclass(frozen=True)
class ArtifactFileIndexInspection:
    """A point-in-time health report for an artifact-file index."""

    total_rows: int
    supported_rows: int
    missing_enrichment_ids: tuple[str, ...]
    missing_stored_path_ids: tuple[str, ...]
    missing_source_path_ids: tuple[str, ...]
    duplicate_ids: tuple[str, ...]
    unrecognized_schema_versions: tuple[int, ...]
    malformed_rows: int

    @property
    def rows_missing_enrichment(self) -> int:
        return len(self.missing_enrichment_ids)

    @property
    def stored_paths_missing(self) -> int:
        return len(self.missing_stored_path_ids)

    @property
    def source_paths_missing(self) -> int:
        return len(self.missing_source_path_ids)

    @property
    def unrecognized_schema_version_rows(self) -> int:
        return len(self.unrecognized_schema_versions)


@dataclass(frozen=True)
class ArtifactFileBackfillReport:
    """Result of one idempotent enrichment backfill."""

    total_rows: int
    updated_ids: tuple[str, ...]
    missing_stored_path_ids: tuple[str, ...]
    unrecognized_schema_versions: tuple[int, ...]

    @property
    def changed(self) -> bool:
        return bool(self.updated_ids)


@dataclass(frozen=True)
class ArtifactFileDigestMismatch:
    """One stored artifact whose content differs from its recorded digest."""

    id: str
    path: str
    expected_sha256: str
    actual_sha256: str


@dataclass(frozen=True)
class ArtifactFileVerifyReport:
    """Result of re-hashing indexed artifact files."""

    total_rows: int
    verified_ids: tuple[str, ...]
    missing_sha256_ids: tuple[str, ...]
    missing_stored_path_ids: tuple[str, ...]
    mismatches: tuple[ArtifactFileDigestMismatch, ...]
    unrecognized_schema_versions: tuple[int, ...]


def inspect_artifact_file_index(
    index_path: Path | str | None = None,
) -> ArtifactFileIndexInspection:
    """Inspect index structure and path liveness without modifying it."""

    idx = _resolve_index_path(index_path)
    if not idx.exists():
        return ArtifactFileIndexInspection(
            total_rows=0,
            supported_rows=0,
            missing_enrichment_ids=(),
            missing_stored_path_ids=(),
            missing_source_path_ids=(),
            duplicate_ids=(),
            unrecognized_schema_versions=(),
            malformed_rows=0,
        )
    with artifact_file_index_lock(idx, exclusive=False):
        rows, preserved_lines = read_artifact_file_index_document_unlocked(idx)
    versions, malformed_rows = _preserved_line_summary(preserved_lines)
    seen: set[str] = set()
    duplicate_ids: set[str] = set()
    for row in rows:
        if row.id in seen:
            duplicate_ids.add(row.id)
        seen.add(row.id)
    return ArtifactFileIndexInspection(
        total_rows=len(rows) + len(preserved_lines),
        supported_rows=len(rows),
        missing_enrichment_ids=tuple(
            row.id for row in rows if _is_missing_enrichment(row)
        ),
        missing_stored_path_ids=tuple(row.id for row in rows if not _is_file(row.path)),
        missing_source_path_ids=tuple(
            row.id
            for row in rows
            if row.source_path is not None and not _is_file(row.source_path)
        ),
        duplicate_ids=tuple(sorted(duplicate_ids)),
        unrecognized_schema_versions=versions,
        malformed_rows=malformed_rows,
    )


def backfill_artifact_file_index(
    index_path: Path | str | None = None,
) -> ArtifactFileBackfillReport:
    """Populate missing enrichment fields for every live stored artifact."""

    idx = _resolve_index_path(index_path)
    if not idx.exists():
        return ArtifactFileBackfillReport(0, (), (), ())
    with artifact_file_index_lock(idx, exclusive=True):
        rows, preserved_lines = read_artifact_file_index_document_unlocked(idx)
        updated_rows: list[ArtifactFile] = []
        updated_ids: list[str] = []
        missing_stored_path_ids: list[str] = []
        for row in rows:
            path = Path(row.path).expanduser()
            if not _is_file(path):
                missing_stored_path_ids.append(row.id)
                updated_rows.append(row)
                continue
            updated = _backfilled_row(row, path)
            updated_rows.append(updated)
            if updated != row:
                updated_ids.append(row.id)
        if updated_ids:
            write_artifact_file_index_unlocked(
                idx,
                updated_rows,
                preserved_lines=preserved_lines,
            )
    versions, _malformed_rows = _preserved_line_summary(preserved_lines)
    return ArtifactFileBackfillReport(
        total_rows=len(rows) + len(preserved_lines),
        updated_ids=tuple(updated_ids),
        missing_stored_path_ids=tuple(missing_stored_path_ids),
        unrecognized_schema_versions=versions,
    )


def verify_artifact_file_index(
    index_path: Path | str | None = None,
) -> ArtifactFileVerifyReport:
    """Re-hash live stored artifacts and report digest mismatches."""

    idx = _resolve_index_path(index_path)
    if not idx.exists():
        return ArtifactFileVerifyReport(0, (), (), (), (), ())
    with artifact_file_index_lock(idx, exclusive=False):
        rows, preserved_lines = read_artifact_file_index_document_unlocked(idx)
        verified_ids: list[str] = []
        missing_sha256_ids: list[str] = []
        missing_stored_path_ids: list[str] = []
        mismatches: list[ArtifactFileDigestMismatch] = []
        for row in rows:
            path = Path(row.path).expanduser()
            if not _is_file(path):
                missing_stored_path_ids.append(row.id)
                continue
            if row.sha256 is None:
                missing_sha256_ids.append(row.id)
                continue
            actual_sha256 = hash_file(path)
            verified_ids.append(row.id)
            if actual_sha256 != row.sha256:
                mismatches.append(
                    ArtifactFileDigestMismatch(
                        id=row.id,
                        path=row.path,
                        expected_sha256=row.sha256,
                        actual_sha256=actual_sha256,
                    )
                )
    versions, _malformed_rows = _preserved_line_summary(preserved_lines)
    return ArtifactFileVerifyReport(
        total_rows=len(rows) + len(preserved_lines),
        verified_ids=tuple(verified_ids),
        missing_sha256_ids=tuple(missing_sha256_ids),
        missing_stored_path_ids=tuple(missing_stored_path_ids),
        mismatches=tuple(mismatches),
        unrecognized_schema_versions=versions,
    )


def _resolve_index_path(index_path: Path | str | None) -> Path:
    if index_path is None:
        return default_artifact_files_index_path()
    return Path(index_path).expanduser()


def _is_missing_enrichment(row: ArtifactFile) -> bool:
    return row.sha256 is None or row.size_bytes is None or row.mime_type is None


def _backfilled_row(row: ArtifactFile, path: Path) -> ArtifactFile:
    sha256 = row.sha256 if row.sha256 is not None else hash_file(path)
    size_bytes = row.size_bytes if row.size_bytes is not None else path.stat().st_size
    mime_type = (
        row.mime_type if row.mime_type is not None else artifact_file_mime_type(path)
    )
    return replace(
        row,
        sha256=sha256,
        size_bytes=size_bytes,
        mime_type=mime_type,
    )


def _is_file(path: Path | str) -> bool:
    try:
        return Path(path).expanduser().is_file()
    except OSError:
        return False


def _preserved_line_summary(lines: list[str]) -> tuple[tuple[int, ...], int]:
    versions: list[int] = []
    malformed_rows = 0
    for line in lines:
        try:
            value = json.loads(line)
            version = int(value["schema_version"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            malformed_rows += 1
            continue
        if version not in ARTIFACT_FILE_INDEX_SUPPORTED_SCHEMA_VERSIONS:
            versions.append(version)
        else:
            malformed_rows += 1
    return tuple(versions), malformed_rows
