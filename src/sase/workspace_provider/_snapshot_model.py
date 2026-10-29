"""Types and constants for verified checkout snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.workspace_provider._rescue_git_worktree import RESCUE_PATCH_MAX_BYTES

SNAPSHOT_KIND = "verified-snapshot"
SNAPSHOT_PACK_NAME = "snapshot.pack"
SNAPSHOT_INDEX_STAGE_NAME = "index-stage"
SNAPSHOT_MAX_BYTES = RESCUE_PATCH_MAX_BYTES

_DIR_OPERATION_MARKERS = (
    "rebase-merge",
    "rebase-apply",
    "sequencer",
)
_FILE_OPERATION_MARKERS = (
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "BISECT_LOG",
    "BISECT_EXPECTED_REV",
)

DIR_OPERATION_MARKERS = _DIR_OPERATION_MARKERS
FILE_OPERATION_MARKERS = _FILE_OPERATION_MARKERS


class PreservationError(RuntimeError):
    """A required checkout snapshot could not be completed.

    The source index, worktree, HEAD, and operation state are left unchanged.
    Incomplete capture directories are removed. Successful snapshots are kept.
    """


class NestedPreservationError(PreservationError):
    """A nested repository could not be fully preserved before removal.

    ``locations`` lists manifests captured before the failure so callers can
    surface partial proof in the operation diagnostic.
    """

    def __init__(
        self,
        message: str,
        *,
        locations: Sequence[str] = (),
        nested_root: str | Path | None = None,
        dirty_paths: Sequence[str] = (),
    ) -> None:
        super().__init__(message)
        self.locations = tuple(location for location in locations if location)
        self.nested_root = str(nested_root) if nested_root else ""
        self.dirty_paths = tuple(path for path in dirty_paths if path)


@dataclass(frozen=True)
class SnapshotRecord:
    """Verified snapshot of a checkout's recoverable bytes."""

    snapshot_id: str
    manifest_path: Path
    rescue_dir: Path
    head: str
    base_tree: str
    index_tree: str | None
    worktree_tree: str
    pack_path: Path
    unmerged: bool


@dataclass(frozen=True)
class SourceFingerprint:
    """Digest of HEAD, the index, and dirty diffs used to detect races."""

    head: str
    index_digest: str
    status_digest: str
    ls_files_digest: str
    diff_cached_digest: str
    diff_worktree_digest: str
    untracked_digest: str


@dataclass(frozen=True)
class IndexEntry:
    """One ``git ls-files --stage`` row."""

    mode: str
    sha: str
    stage: int
    path: str


@dataclass(frozen=True)
class SourceState:
    """One consistent read of the source checkout."""

    fingerprint: SourceFingerprint
    head: str
    base_tree: str
    branch: str | None
    status_z: bytes
    ls_files_z: bytes
    entries: tuple[IndexEntry, ...]
    git_dir: Path
    object_dir: Path
    index_path: Path
