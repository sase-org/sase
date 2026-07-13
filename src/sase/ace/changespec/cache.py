"""ChangeSpec snapshot cache keyed on (path, mtime_ns, size).

The TUI reparses every project ``.gp`` file on every refresh. Most files are
unchanged between refreshes, so the parse work is pure waste. This module
caches parsed ChangeSpec lists per file in-process; an entry is reused when
the file's ``(mtime_ns, size)`` signature is unchanged.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path
from threading import Lock

from .discovery import iter_changespec_project_file_records
from .models import ChangeSpec
from .parser import parse_project_file


class ChangeSpecSnapshotCache:
    """In-process cache of parsed ChangeSpec lists per project file."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[int, int, str | None, list[ChangeSpec]]] = {}
        self._lock = Lock()

    def get_file_specs(
        self,
        path: Path | str,
        project_display_name: str | None = None,
    ) -> list[ChangeSpec]:
        """Return parsed ChangeSpecs for *path*, using the cache when fresh."""
        p = os.fspath(path)
        try:
            st = os.stat(p)
        except OSError:
            with self._lock:
                self._data.pop(p, None)
            return []

        sig = (st.st_mtime_ns, st.st_size)
        with self._lock:
            cached = self._data.get(p)
            if (
                cached is not None
                and (cached[0], cached[1]) == sig
                and cached[2] == project_display_name
            ):
                return list(cached[3])

        specs = parse_project_file(p)
        for spec in specs:
            spec.project_display_name = project_display_name

        with self._lock:
            self._data[p] = (sig[0], sig[1], project_display_name, specs)
        return list(specs)

    def find_all_changespecs_cached(
        self,
        include_states: Sequence[str] | str = ("enabled",),
    ) -> list[ChangeSpec]:
        """Find ChangeSpecs across lifecycle-selected project + archive files."""
        seen: set[str] = set()
        all_specs: list[ChangeSpec] = []
        for item in iter_changespec_project_file_records(include_states=include_states):
            seen.add(os.fspath(item.path))
            all_specs.extend(self.get_file_specs(item.path, item.project_display_name))

        with self._lock:
            for path in list(self._data.keys()):
                if path not in seen:
                    self._data.pop(path, None)

        return all_specs

    def invalidate(self, path: Path | str | None = None) -> None:
        """Invalidate one path or the whole cache."""
        with self._lock:
            if path is None:
                self._data.clear()
            else:
                self._data.pop(os.fspath(path), None)


_GLOBAL_CACHE = ChangeSpecSnapshotCache()


def find_all_changespecs_cached(
    include_states: Sequence[str] | str = ("enabled",),
) -> list[ChangeSpec]:
    """Module-level cached variant of ``find_all_changespecs``."""
    return _GLOBAL_CACHE.find_all_changespecs_cached(include_states=include_states)


def get_global_snapshot_cache() -> ChangeSpecSnapshotCache:
    return _GLOBAL_CACHE
