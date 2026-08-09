"""Patch snapshot cache keyed on (path, mtime_ns, size).

ProjectSpec files are reparsed frequently by UI and query paths. This module
caches parsed Patch lists per file in-process; an entry is reused while the
file's ``(mtime_ns, size)`` signature is unchanged.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from threading import Lock

from .discovery import iter_patch_project_file_records
from .models import Patch
from .parser import parse_project_file


class PatchSnapshotCache:
    """In-process cache of parsed Patch lists per project file."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[int, int, str | None, list[Patch]]] = {}
        self._lock = Lock()

    def get_file_specs(
        self,
        path: Path | str,
        project_display_name: str | None = None,
    ) -> list[Patch]:
        """Return parsed Patches for *path*, using the cache when fresh."""
        project_path = os.fspath(path)
        try:
            stat_result = os.stat(project_path)
        except OSError:
            with self._lock:
                self._data.pop(project_path, None)
            return []

        signature = (stat_result.st_mtime_ns, stat_result.st_size)
        with self._lock:
            cached = self._data.get(project_path)
            if (
                cached is not None
                and (cached[0], cached[1]) == signature
                and cached[2] == project_display_name
            ):
                return list(cached[3])

        patches = parse_project_file(project_path)
        for patch in patches:
            patch.project_display_name = project_display_name

        with self._lock:
            self._data[project_path] = (
                signature[0],
                signature[1],
                project_display_name,
                patches,
            )
        return list(patches)

    def find_all_patches_cached(
        self,
        include_states: Sequence[str] | str = ("enabled",),
    ) -> list[Patch]:
        """Find Patches across lifecycle-selected active and archive files."""
        seen: set[str] = set()
        patches: list[Patch] = []
        for item in iter_patch_project_file_records(include_states=include_states):
            seen.add(os.fspath(item.path))
            patches.extend(self.get_file_specs(item.path, item.project_display_name))

        with self._lock:
            for path in list(self._data.keys()):
                if path not in seen:
                    self._data.pop(path, None)

        return patches

    def find_all_changespecs_cached(  # legacy compatibility alias
        self,
        include_states: Sequence[str] | str = ("enabled",),
    ) -> list[Patch]:
        """Legacy alias for :meth:`find_all_patches_cached`."""
        return self.find_all_patches_cached(include_states=include_states)

    def invalidate(self, path: Path | str | None = None) -> None:
        """Invalidate one path or the whole cache."""
        with self._lock:
            if path is None:
                self._data.clear()
            else:
                self._data.pop(os.fspath(path), None)


ChangeSpecSnapshotCache = PatchSnapshotCache  # legacy compatibility alias
_GLOBAL_CACHE = PatchSnapshotCache()


def find_all_patches_cached(
    include_states: Sequence[str] | str = ("enabled",),
) -> list[Patch]:
    """Module-level cached variant of ``find_all_patches``."""
    return _GLOBAL_CACHE.find_all_patches_cached(include_states=include_states)


def find_all_changespecs_cached(  # legacy compatibility alias
    include_states: Sequence[str] | str = ("enabled",),
) -> list[Patch]:
    """Legacy alias for :func:`find_all_patches_cached`."""
    return find_all_patches_cached(include_states=include_states)


def get_global_snapshot_cache() -> PatchSnapshotCache:
    return _GLOBAL_CACHE
