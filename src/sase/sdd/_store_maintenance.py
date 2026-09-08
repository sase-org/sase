"""Best-effort maintenance for provider-owned sidecar SDD clones."""

from __future__ import annotations

import logging
from pathlib import Path

from sase.sdd._store_adoption import try_materialization_lock

_logger = logging.getLogger(__name__)

_PACK_FILE_THRESHOLD = 8
_LOOSE_OBJECT_THRESHOLD = 2_000
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
    return (
        _pack_file_count(git_dir) > _PACK_FILE_THRESHOLD
        or _loose_object_count(git_dir) > _LOOSE_OBJECT_THRESHOLD
    )


def _pack_file_count(git_dir: Path) -> int:
    pack_dir = git_dir / "objects" / "pack"
    if not pack_dir.is_dir():
        return 0
    return sum(1 for path in pack_dir.glob("*.pack") if path.is_file())


def _loose_object_count(git_dir: Path) -> int:
    objects_dir = git_dir / "objects"
    if not objects_dir.is_dir():
        return 0

    count = 0
    for bucket in objects_dir.iterdir():
        if not bucket.is_dir() or not _is_loose_object_bucket(bucket.name):
            continue
        count += sum(1 for path in bucket.iterdir() if path.is_file())
    return count


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


__all__ = ["maybe_gc_sidecar_clone"]
