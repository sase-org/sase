"""Persisted tree-size cache for the hourly ACE-run retention preview.

Every hourly ``artifact_run_prune`` preview re-measures each selected run
directory with a full recursive walk. Selected runs are terminal and older
than the kept calendar months, so their trees almost never change between
previews; this cache reuses the last measurement while the run directory's
own identity (inode and mtime) is unchanged. A preview's byte count is an
estimate that gates a notification, never what an apply frees, so a nested
edit that leaves the top directory's mtime alone costs at most a stale
estimate until that run is trashed or its directory changes.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import os
from pathlib import Path
import tempfile

_SCHEMA_VERSION = 1


class AceRunSizeCache:
    """Per-pass view of the persisted ``{artifact_dir: [ino, mtime_ns, size]}``."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries = _read_entries(path)
        self._used: dict[str, list[int]] = {}
        self.hits = 0
        self.misses = 0

    def size(self, artifact_dir: Path, measure: Callable[[Path], int]) -> int:
        """Return *artifact_dir*'s cached size, measuring it on a miss."""

        key = str(artifact_dir)
        try:
            identity = artifact_dir.stat(follow_symlinks=False)
        except OSError:
            return measure(artifact_dir)
        cached = self._entries.get(key)
        if (
            cached is not None
            and cached[0] == identity.st_ino
            and cached[1] == identity.st_mtime_ns
        ):
            self.hits += 1
            self._used[key] = cached
            return cached[2]
        self.misses += 1
        size = measure(artifact_dir)
        self._used[key] = [identity.st_ino, identity.st_mtime_ns, int(size)]
        return size

    def save(self) -> None:
        """Persist only this pass's entries, so runs no longer selected drop out."""

        if self._used == self._entries:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": _SCHEMA_VERSION, "sizes": self._used}
        fd, temporary = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, sort_keys=True)
            os.replace(temporary, self.path)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise


def _read_entries(path: Path) -> dict[str, list[int]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != _SCHEMA_VERSION
    ):
        return {}
    sizes = payload.get("sizes")
    if not isinstance(sizes, dict):
        return {}
    entries: dict[str, list[int]] = {}
    for key, value in sizes.items():
        if (
            isinstance(key, str)
            and isinstance(value, list)
            and len(value) == 3
            and all(
                isinstance(item, int) and not isinstance(item, bool) for item in value
            )
        ):
            entries[key] = list(value)
    return entries


__all__ = ["AceRunSizeCache"]
