"""Lifecycle-aware ProjectSpec file discovery for ChangeSpec scans."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import PROJECT_LIFECYCLE_STATES

_ALL_STATES = tuple(PROJECT_LIFECYCLE_STATES)


def _normalize_project_lifecycle_states(
    include_states: Sequence[str] | str,
) -> list[str]:
    """Return concrete lifecycle states for a ChangeSpec project scan."""
    if include_states == "all":
        return list(_ALL_STATES)
    states = (
        [include_states] if isinstance(include_states, str) else list(include_states)
    )
    invalid = [state for state in states if state not in _ALL_STATES]
    if invalid:
        raise ValueError(f"invalid project lifecycle state: {invalid[0]}")
    return states


def iter_changespec_project_files(
    projects_dir: Path | None = None,
    include_states: Sequence[str] | str = ("active",),
    *,
    include_home: bool = True,
) -> list[Path]:
    """Return active/archive ProjectSpec files for lifecycle-selected projects."""
    projects_root = projects_dir or sase_projects_dir()
    if not projects_root.exists():
        return []

    records = list_project_records(
        projects_root,
        _normalize_project_lifecycle_states(include_states),
        include_home=include_home,
    )
    paths: list[Path] = []
    seen: set[str] = set()
    for record in records:
        for raw_path in (record.project_file, record.archive_file):
            if not raw_path:
                continue
            path = Path(raw_path)
            if not path.exists():
                continue
            path_key = os.fspath(path)
            if path_key in seen:
                continue
            seen.add(path_key)
            paths.append(path)
    return paths


__all__ = ["iter_changespec_project_files"]
