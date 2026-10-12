"""Filesystem dependency rows for the wait_checks chop.

Owns the run-scoped ``agent_meta.json`` listing used to build wait-dependency
indexes. The wait_checks run loop and waiter processor both call these helpers,
so names here are public inside this already-private module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core.wait_dependency_resolution import (
    ScopeKeyCache,
    WaitDependencyIndex,
    read_json_dict,
    select_dirs_with_cache,
)


def clone_empty_index(source: WaitDependencyIndex) -> WaitDependencyIndex:
    """Empty index that reuses already-loaded tribe evidence from *source*."""
    cloned = WaitDependencyIndex.empty(
        global_stored_tribes=source.global_stored_tribes,
    )
    cloned.agent_tribes = dict(source.agent_tribes)
    return cloned


def filesystem_dependency_rows(
    projects_dir: Path,
    *,
    project_names: set[str] | None = None,
    meta_cache: dict[Path, dict[str, Any] | None] | None = None,
    scope_cache: ScopeKeyCache | None = None,
    scope_keys: frozenset[str] | set[str] | None = None,
    include_dirs: tuple[Path, ...] | list[Path] = (),
    seen_dirs: set[Path] | None = None,
) -> list[tuple[Path, dict[str, Any], str]]:
    """Load ace-run agent_meta.json files for wait-dependency resolution.

    When meta_cache is given, reuse metadata already loaded earlier in the run
    and only read files for artifact directories not yet seen. The directory
    listing itself is always fresh.

    When scope_cache and scope_keys are given, select rows through the
    persistent scope-key cache instead: unselected artifacts cost one
    ``stat`` instead of one JSON read, while selected rows still read their
    meta fresh. Every listed dir joins seen_dirs (when given) for the
    end-of-tick prune of vanished cache entries.
    """

    if scope_cache is None or scope_keys is None:
        rows: list[tuple[Path, dict[str, Any], str]] = []
        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue
            project_name = project_dir.name
            if project_names is not None and project_name not in project_names:
                continue
            for artifact_dir in iter_agent_artifact_dirs(
                project_name,
                "ace-run",
                projects_root=projects_dir,
            ):
                meta_path = artifact_dir / "agent_meta.json"
                if meta_cache is not None and meta_path in meta_cache:
                    meta = meta_cache[meta_path]
                else:
                    meta = read_json_dict(meta_path)
                    if meta_cache is not None:
                        meta_cache[meta_path] = meta
                if meta is not None:
                    rows.append((artifact_dir, meta, project_name))
        return rows

    def _read_meta_fresh(artifact_dir: Path) -> dict[str, Any] | None:
        meta = read_json_dict(artifact_dir / "agent_meta.json")
        if meta_cache is not None:
            meta_cache[artifact_dir / "agent_meta.json"] = meta
        return meta

    scoped_rows: list[tuple[Path, dict[str, Any], str]] = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        project_name = project_dir.name
        if project_names is not None and project_name not in project_names:
            continue
        candidates = list(
            iter_agent_artifact_dirs(
                project_name,
                "ace-run",
                projects_root=projects_dir,
            )
        )
        if seen_dirs is not None:
            seen_dirs.update(candidates)
        selected = select_dirs_with_cache(
            candidates,
            scope_keys,
            include_dirs=include_dirs,
            cache=scope_cache,
            read_meta=_read_meta_fresh,
            update_cache=True,
        )
        for artifact_dir in selected:
            meta_path = artifact_dir / "agent_meta.json"
            if meta_cache is not None and meta_path in meta_cache:
                meta = meta_cache[meta_path]
            else:
                meta = read_json_dict(meta_path)
                if meta_cache is not None:
                    meta_cache[meta_path] = meta
            if meta is not None:
                scoped_rows.append((artifact_dir, meta, project_name))
    return scoped_rows


__all__ = [
    "clone_empty_index",
    "filesystem_dependency_rows",
]
