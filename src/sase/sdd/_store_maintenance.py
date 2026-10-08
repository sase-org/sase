"""Best-effort maintenance for provider-owned sidecar SDD clones."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import fcntl
import logging
from pathlib import Path

from sase.sdd._store_adoption import try_materialization_lock

_logger = logging.getLogger(__name__)

_PACK_FILE_THRESHOLD = 8
_LOOSE_OBJECT_THRESHOLD = 2_000
# Bead sidecars used to commit a ~21 MB copy of the ``issues.jsonl``
# projection on every mutation, so a clone can hold gigabytes of loose objects
# while its object *count* stays below ``_LOOSE_OBJECT_THRESHOLD`` (and below
# git's count-based ``gc.auto``). Since projection-off (sase-1h8.11) the
# export is git-ignored, but historic clones still carry the bloat. Bound the
# ``--dissociate`` repack cost of fresh workspace clones by triggering on
# loose-object *bytes* as well.
_LOOSE_OBJECT_BYTES_THRESHOLD = 256 * 1024 * 1024
_GC_TIMEOUT_SECONDS = 600.0
_HEX_DIGITS = frozenset("0123456789abcdef")


def maybe_gc_sidecar_clone(clone_dir: Path, primary: Path) -> bool:
    """Run ``git gc`` when a sidecar clone is fragmented enough to matter."""

    if not _clone_looks_fragmented(clone_dir):
        return False

    try:
        with try_materialization_lock(primary) as acquired:
            if not acquired:
                _logger.info(
                    "Skipping SDD sidecar maintenance for %s; materialization "
                    "lock is busy",
                    clone_dir,
                )
                return False
            return _run_sidecar_gc(clone_dir)
    except Exception:  # noqa: BLE001 - maintenance must never fail the caller.
        _logger.warning(
            "Failed to run SDD sidecar maintenance for %s",
            clone_dir,
            exc_info=True,
        )
        return False


def _clone_looks_fragmented(clone_dir: Path) -> bool:
    git_dir = clone_dir / ".git"
    if not git_dir.is_dir():
        return False
    if _pack_file_count(git_dir) > _PACK_FILE_THRESHOLD:
        return True
    loose_count, loose_bytes = _loose_object_stats(git_dir)
    return (
        loose_count > _LOOSE_OBJECT_THRESHOLD
        or loose_bytes > _LOOSE_OBJECT_BYTES_THRESHOLD
    )


def _pack_file_count(git_dir: Path) -> int:
    pack_dir = git_dir / "objects" / "pack"
    if not pack_dir.is_dir():
        return 0
    return sum(1 for path in pack_dir.glob("*.pack") if path.is_file())


def _loose_object_stats(git_dir: Path) -> tuple[int, int]:
    """Return ``(count, bytes)`` of loose objects under *git_dir*."""

    objects_dir = git_dir / "objects"
    if not objects_dir.is_dir():
        return (0, 0)

    count = 0
    total_bytes = 0
    for bucket in objects_dir.iterdir():
        if not bucket.is_dir() or not _is_loose_object_bucket(bucket.name):
            continue
        for path in bucket.iterdir():
            if not path.is_file():
                continue
            count += 1
            try:
                total_bytes += path.stat().st_size
            except OSError:
                continue
    return (count, total_bytes)


def _is_loose_object_bucket(name: str) -> bool:
    return len(name) == 2 and all(char in _HEX_DIGITS for char in name.casefold())


def _run_sidecar_gc(clone_dir: Path) -> bool:
    from sase.sdd._commit import SddGitCommandTimeout, run_sdd_git

    try:
        result = run_sdd_git(
            ["gc"],
            cwd=clone_dir,
            op="sdd.maintenance.gc",
            timeout=_GC_TIMEOUT_SECONDS,
            check=False,
            capture_output=True,
            text=True,
        )
    except SddGitCommandTimeout:
        _logger.warning("Timed out running SDD sidecar maintenance for %s", clone_dir)
        return False
    except Exception:  # noqa: BLE001 - maintenance must never fail the caller.
        _logger.warning(
            "Failed to run SDD sidecar maintenance for %s",
            clone_dir,
            exc_info=True,
        )
        return False

    if result.returncode == 0:
        return True

    detail = (result.stderr or result.stdout or "").strip()
    _logger.warning(
        "Failed to run SDD sidecar maintenance for %s: %s",
        clone_dir,
        detail or f"git gc exited {result.returncode}",
    )
    return False


@contextmanager
def _try_machine_event_lock(project_key: str) -> Iterator[bool]:
    """Try the machine artifact-link event lock for *project_key*.

    Machine publication commits into the hidden clones through
    ``publish_artifact_link_events``, which holds an exclusive flock on
    ``~/.sase/projects/<project_key>/artifact-link-events.lock``. A
    non-blocking attempt here keeps ``git gc`` from racing a machine commit.
    """

    from sase.sdd._artifact_link_event_canonical import (
        ARTIFACT_LINK_EVENT_LOCK_FILENAME,
    )

    from sase.core.paths import sase_projects_dir

    lock_path = sase_projects_dir() / project_key / ARTIFACT_LINK_EVENT_LOCK_FILENAME
    try:
        lock_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        yield True
        return
    try:
        with lock_path.open("a+", encoding="utf-8") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            try:
                yield True
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    except OSError:
        _logger.warning(
            "Failed to probe the machine event lock for %s",
            project_key,
            exc_info=True,
        )
        yield True


def _maybe_gc_hidden_sidecar_clone(
    clone_dir: Path,
    primary: Path,
    *,
    project_key: str,
) -> bool:
    """Run ``git gc`` on a host-owned hidden sidecar clone when fragmented.

    Uses the same try-lock semantics as :func:`maybe_gc_sidecar_clone` and
    additionally serializes with the machine artifact-link store's writer, so
    gc never races a machine commit into the same clone.
    """

    if not _clone_looks_fragmented(clone_dir):
        return False

    try:
        with try_materialization_lock(primary) as acquired:
            if not acquired:
                _logger.info(
                    "Skipping hidden sidecar maintenance for %s; "
                    "materialization lock is busy",
                    clone_dir,
                )
                return False
            with _try_machine_event_lock(project_key) as writer_free:
                if not writer_free:
                    _logger.info(
                        "Skipping hidden sidecar maintenance for %s; "
                        "machine event writer is busy",
                        clone_dir,
                    )
                    return False
                return _run_sidecar_gc(clone_dir)
    except Exception:  # noqa: BLE001 - maintenance must never fail the caller.
        _logger.warning(
            "Failed to run hidden sidecar maintenance for %s",
            clone_dir,
            exc_info=True,
        )
        return False


def _hidden_sidecar_clone_dirs(project_key: str) -> list[Path]:
    """Return the existing hidden sidecar clone dirs for *project_key*."""

    from sase.core.paths import sase_projects_dir

    repos_dir = sase_projects_dir() / project_key / "repos"
    try:
        entries = list(repos_dir.iterdir())
    except OSError:
        return []
    clones = [
        entry for entry in entries if entry.is_dir() and (entry / ".git").is_dir()
    ]
    return sorted(clones)


def maintain_hidden_sidecar_clones(project_key: str, primary: Path) -> int:
    """Gc every fragmented hidden sidecar clone of *project_key*.

    Returns the number of clones gc'd. Best-effort: one broken clone never
    blocks the rest.
    """

    collected = 0
    for clone_dir in _hidden_sidecar_clone_dirs(project_key):
        try:
            if _maybe_gc_hidden_sidecar_clone(
                clone_dir, primary, project_key=project_key
            ):
                collected += 1
        except Exception:  # noqa: BLE001 - maintenance must never fail.
            _logger.warning(
                "Failed to run hidden sidecar maintenance for %s",
                clone_dir,
                exc_info=True,
            )
    return collected


__all__ = [
    "_hidden_sidecar_clone_dirs",
    "maintain_hidden_sidecar_clones",
    "_maybe_gc_hidden_sidecar_clone",
    "maybe_gc_sidecar_clone",
]
