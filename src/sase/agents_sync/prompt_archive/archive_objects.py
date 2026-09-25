"""Pending content-addressed objects in the agents-sidecar prompt archive.

``files/objects`` is append-only: an object's pool copy lives in an ephemeral
workspace, so a discarded object cannot be regenerated. Nothing here resets,
restores, or deletes under it. A file that is not a canonical, hash-valid object
is moved into a quarantine directory under the sidecar's git dir instead, so it
can never wedge the worktree and stays recoverable.
"""

from __future__ import annotations

from datetime import UTC, datetime
import logging
import os
from pathlib import Path
import re

from sase.agents_sync.git import GitRunner
from sase.agents_sync.git_sync_ops import agents_git_dir
from sase.core.artifact_file_helpers import hash_file

log = logging.getLogger(__name__)

ARCHIVE_OBJECT_ROOT = "files/objects"
_OBJECT_PATH_RE = re.compile(
    rf"^{re.escape(ARCHIVE_OBJECT_ROOT)}/sha256/([0-9a-f]{{2}})/([0-9a-f]{{64}})$"
)


def is_valid_archive_object(repo: Path, relpath: str) -> bool:
    """Whether ``relpath`` is a canonical object whose bytes match its name."""

    match = _OBJECT_PATH_RE.match(relpath)
    if match is None or not match.group(2).startswith(match.group(1)):
        return False
    path = repo / relpath
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return hash_file(path) == match.group(2)
    except OSError:
        return False


def _pending_archive_objects(
    repo: Path, git_runner: GitRunner
) -> tuple[str, ...] | str:
    """Return untracked paths under ``files/objects``, or a git error message."""

    listed = git_runner(
        repo,
        ["ls-files", "-z", "--others", "--exclude-standard", "--", ARCHIVE_OBJECT_ROOT],
        op="agents_sync.prompt_archive_pending_objects",
    )
    if listed.returncode != 0:
        detail = (listed.stderr or listed.stdout or "unknown git error").strip()
        return f"could not list pending prompt archive objects: {detail}"
    return tuple(path for path in listed.stdout.split("\0") if path)


def quarantine_invalid_pending_objects(
    repo: Path,
    git_runner: GitRunner,
) -> tuple[str, ...] | str:
    """Move non-canonical or hash-mismatched pending objects out of the worktree.

    Returns the remaining hash-valid pending object paths, or a git/filesystem
    error message.
    """

    pending = _pending_archive_objects(repo, git_runner)
    if isinstance(pending, str):
        return pending
    valid = tuple(path for path in pending if is_valid_archive_object(repo, path))
    if len(valid) == len(pending):
        return valid
    valid_set = frozenset(valid)
    invalid = tuple(path for path in pending if path not in valid_set)
    quarantine = (
        agents_git_dir(repo, git_runner)
        / "sase-quarantine"
        / "objects"
        / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    )
    for relpath in invalid:
        destination = _unused_destination(quarantine / relpath)
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(repo / relpath, destination)
        except OSError as exc:
            return (
                f"could not quarantine invalid prompt archive object {relpath}: {exc}"
            )
        log.warning(
            "Quarantined invalid prompt archive object %s to %s", relpath, destination
        )
    return valid


def _unused_destination(destination: Path) -> Path:
    candidate = destination
    suffix = 0
    while os.path.lexists(candidate):
        suffix += 1
        candidate = destination.with_name(f"{destination.name}.{suffix}")
    return candidate
