"""Repository-file contract for durable artifact-link files."""

from __future__ import annotations

from enum import StrEnum
import json
from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.sdd._artifact_link_store_support import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    sidecar_index_path,
    validate_artifact_link_row,
)
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR
from sase.sdd.referenced_by_index import referenced_by_index_relpath


class _ArtifactLinkRepoFileKind(StrEnum):
    """Classification of one path relative to a document sidecar root."""

    INDEX = "index"
    EVENT = "event"
    LOCK = "lock"
    REJECTED = "rejected"
    OTHER = "other"


def artifact_link_lock_path(index_path: Path) -> Path:
    """Return the ``flock`` sentinel sibling used by the link store."""

    return index_path.with_suffix(".lock")


def _classify_artifact_link_repo_file(
    path: Path, repo_root: Path
) -> _ArtifactLinkRepoFileKind:
    """Classify *path* against the artifact-link repository-file contract.

    Only canonical ``links/**/*.json`` indexes, their empty regular-file lock
    siblings, and canonical immutable ``link-events/v1/**/*.json`` objects are
    recognized. Malformed, mismatched, symlinked, nonempty, or unpaired
    candidates are rejected instead of auto-committed or hidden.
    """

    located = _absolute_in_repo(path, repo_root)
    if located is None:
        return _ArtifactLinkRepoFileKind.OTHER
    absolute, relative = located
    if relative.parts[:2] == ("link-events", "v1"):
        if name := relative.name:
            if name.endswith(".json"):
                if _is_canonical_event(absolute, relative):
                    return _ArtifactLinkRepoFileKind.EVENT
                return _ArtifactLinkRepoFileKind.REJECTED
        return _ArtifactLinkRepoFileKind.OTHER
    if relative.parts[:1] != (REFERENCED_BY_LINKS_DIR,):
        return _ArtifactLinkRepoFileKind.OTHER
    name = relative.name
    if name.endswith(".json"):
        if _is_canonical_index(absolute, repo_root):
            return _ArtifactLinkRepoFileKind.INDEX
        return _ArtifactLinkRepoFileKind.REJECTED
    if name.endswith(".lock"):
        if _is_canonical_lock(absolute, repo_root):
            return _ArtifactLinkRepoFileKind.LOCK
        return _ArtifactLinkRepoFileKind.REJECTED
    return _ArtifactLinkRepoFileKind.OTHER


def is_canonical_artifact_link_index(path: Path, repo_root: Path) -> bool:
    """Return whether *path* is a valid schema-v2 per-artifact link index."""

    return (
        _classify_artifact_link_repo_file(path, repo_root)
        is _ArtifactLinkRepoFileKind.INDEX
    )


def is_canonical_artifact_link_index_location(path: Path, repo_root: Path) -> bool:
    """Return whether *path* is a canonical per-artifact link-index location."""

    located = _absolute_in_repo(path, repo_root)
    if located is None:
        return False
    absolute, relative = located
    if relative.parts[:1] != (REFERENCED_BY_LINKS_DIR,):
        return False
    if len(relative.parts) < 2 or not relative.name.endswith(".json"):
        return False
    if absolute.is_symlink():
        return False
    artifact_relpath = relative.as_posix()[len(f"{REFERENCED_BY_LINKS_DIR}/") :]
    artifact_relpath = artifact_relpath[: -len(".json")]
    try:
        expected = referenced_by_index_relpath(artifact_relpath)
    except (TypeError, ValueError, RuntimeError):
        return False
    return expected == relative.as_posix()


def is_canonical_artifact_link_event(path: Path, repo_root: Path) -> bool:
    """Return whether *path* is a valid immutable artifact-link event object."""

    located = _absolute_in_repo(path, repo_root)
    if located is None:
        return False
    absolute, relative = located
    return _is_canonical_event(absolute, relative)


def is_canonical_artifact_link_event_location(path: Path, repo_root: Path) -> bool:
    """Return whether *path* is a canonical immutable event-object location."""

    located = _absolute_in_repo(path, repo_root)
    if located is None:
        return False
    absolute, relative = located
    if absolute.is_symlink():
        return False
    return _is_canonical_event_relative_path(relative)


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


def _is_canonical_event(path: Path, relative: Path) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        payload = path.read_bytes()
    except OSError:
        return False
    try:
        require_rust_binding("artifact_link_event_validate_bytes")(
            payload,
            relative.as_posix(),
        )
    except (TypeError, ValueError, RuntimeError):
        return False
    return True


def _is_canonical_event_relative_path(relative: Path) -> bool:
    if relative.parts[:2] != ("link-events", "v1"):
        return False
    if len(relative.parts) != 4 or not relative.name.endswith(".json"):
        return False
    digest = relative.name[: -len(".json")]
    if not _is_sha256(digest):
        return False
    try:
        expected = require_rust_binding("artifact_link_event_validate_path")(
            relative.as_posix(),
            digest,
        )
    except (TypeError, ValueError, RuntimeError):
        return False
    return expected == relative.as_posix()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _read_index_object(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


__all__ = [
    "artifact_link_lock_path",
    "is_canonical_artifact_link_event",
    "is_canonical_artifact_link_event_location",
    "is_canonical_artifact_link_index",
    "is_canonical_artifact_link_index_location",
]
