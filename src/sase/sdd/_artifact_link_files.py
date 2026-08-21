"""Repository-file contract for durable artifact-link indexes and lock sentinels."""

from __future__ import annotations

from enum import StrEnum
import json
from pathlib import Path
from typing import Any

from sase.sdd._artifact_link_store_support import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    sidecar_index_path,
    validate_artifact_link_row,
)
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR


class ArtifactLinkRepoFileKind(StrEnum):
    """Classification of one path relative to a document sidecar root."""

    INDEX = "index"
    LOCK = "lock"
    REJECTED = "rejected"
    OTHER = "other"


def artifact_link_lock_path(index_path: Path) -> Path:
    """Return the ``flock`` sentinel sibling used by the link store."""

    return index_path.with_suffix(".lock")


def classify_artifact_link_repo_file(
    path: Path, repo_root: Path
) -> ArtifactLinkRepoFileKind:
    """Classify *path* against the artifact-link repository-file contract.

    Only canonical ``links/**/*.json`` indexes and their empty regular-file
    lock siblings are recognized. Malformed, mismatched, symlinked, nonempty,
    or unpaired candidates are rejected instead of auto-committed or hidden.
    """

    located = _absolute_in_repo(path, repo_root)
    if located is None:
        return ArtifactLinkRepoFileKind.OTHER
    absolute, relative = located
    if relative.parts[:1] != (REFERENCED_BY_LINKS_DIR,):
        return ArtifactLinkRepoFileKind.OTHER
    name = relative.name
    if name.endswith(".json"):
        if _is_canonical_index(absolute, repo_root):
            return ArtifactLinkRepoFileKind.INDEX
        return ArtifactLinkRepoFileKind.REJECTED
    if name.endswith(".lock"):
        if _is_canonical_lock(absolute, repo_root):
            return ArtifactLinkRepoFileKind.LOCK
        return ArtifactLinkRepoFileKind.REJECTED
    return ArtifactLinkRepoFileKind.OTHER


def is_canonical_artifact_link_index(path: Path, repo_root: Path) -> bool:
    """Return whether *path* is a valid schema-v2 per-artifact link index."""

    return (
        classify_artifact_link_repo_file(path, repo_root)
        is ArtifactLinkRepoFileKind.INDEX
    )


def _absolute_in_repo(path: Path, repo_root: Path) -> tuple[Path, Path] | None:
    """Return ``(absolute, repo-relative)`` without following the leaf symlink."""

    try:
        root = repo_root.expanduser().resolve(strict=False)
        absolute = path.expanduser()
        if not absolute.is_absolute():
            absolute = root / absolute
        parent = absolute.parent.resolve(strict=False)
        located = parent / absolute.name
        relative = located.relative_to(root)
    except (OSError, ValueError):
        return None
    if any(part in {"", ".", ".."} for part in relative.parts):
        return None
    return located, relative


def _is_canonical_index(path: Path, repo_root: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    payload = _read_index_object(path)
    if payload is None:
        return False
    if payload.get("schema_version") != ARTIFACT_LINK_ROW_SCHEMA_VERSION:
        return False
    artifact_ref = payload.get("artifact_ref")
    if not isinstance(artifact_ref, str) or not artifact_ref.strip():
        return False
    try:
        expected = sidecar_index_path(
            repo_root.expanduser().resolve(strict=False), artifact_ref
        )
    except (TypeError, ValueError, RuntimeError):
        return False
    try:
        if expected.resolve(strict=False) != path.resolve(strict=False):
            return False
    except OSError:
        return False
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return False
    for row in rows:
        if not isinstance(row, dict):
            return False
        try:
            validate_artifact_link_row(row)
        except (TypeError, ValueError, RuntimeError):
            return False
    return True


def _is_canonical_lock(path: Path, repo_root: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        if path.stat().st_size != 0:
            return False
    except OSError:
        return False
    return _is_canonical_index(path.with_suffix(".json"), repo_root)


def _read_index_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


__all__ = [
    "ArtifactLinkRepoFileKind",
    "artifact_link_lock_path",
    "classify_artifact_link_repo_file",
    "is_canonical_artifact_link_index",
]
