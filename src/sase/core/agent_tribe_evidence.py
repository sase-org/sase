"""Cached stored-tribe evidence shared by mutation and wait callers."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import RLock
from typing import Any

from sase.core.agent_artifact_paths import iter_agent_artifact_dirs
from sase.core import agent_tribe as agent_tribe_paths
from sase.core.agent_tribe import canonical_agent_tribes_path, load_raw_agent_tribes
from sase.core.paths import sase_home, sase_projects_dir
from sase.core.wait_dependency_resolution import WaitDependencyIndex, read_json_dict

_CACHE_LOCK = RLock()
# Keyed by path identity; the value carries the file-version signature the
# names were built from. A version mismatch rebuilds and replaces that key's
# entry, so one live version per key is pinned instead of one permanent entry
# per superseded version. Bounds keys, LRU.
_CACHE: OrderedDict[
    tuple[str, str, str, str],
    tuple[tuple[Any, ...], tuple[str, ...]],
] = OrderedDict()
_CACHE_MAX = 8
_CACHE_GENERATION = 0
_LEGACY_STORE_ATTR = "_".join(("legacy", "agent", "tags", "path"))


def invalidate_agent_tribe_evidence_cache() -> None:
    """Drop cached cross-project tribe evidence after metadata/store writes."""
    global _CACHE_GENERATION
    with _CACHE_LOCK:
        _CACHE_GENERATION += 1
        _CACHE.clear()


def stored_tribe_names_for_resolution(
    *,
    projects_root: Path | str | None = None,
    agent_tribes_path: Path | str | None = None,
    legacy_store_path: Path | str | None = None,
    extra_tribes: tuple[str, ...] | list[str] = (),
) -> tuple[str, ...]:
    """Return assignment, metadata, and effective-clan tribe evidence.

    The scan is cached per SASE home/projects root and assignment-store mtime.
    SASE-owned metadata and assignment writers invalidate the cache in-process;
    separate processes naturally start with an empty cache.
    """
    projects = (
        Path(projects_root).expanduser() if projects_root else sase_projects_dir()
    )
    tribes_path = (
        Path(agent_tribes_path).expanduser()
        if agent_tribes_path is not None
        else canonical_agent_tribes_path()
    )
    legacy_path = (
        Path(legacy_store_path).expanduser()
        if legacy_store_path is not None
        else getattr(agent_tribe_paths, _LEGACY_STORE_ATTR)()
    )
    key = (
        str(sase_home()),
        str(projects),
        str(tribes_path),
        str(legacy_path),
    )
    version = (
        _stat_token(tribes_path),
        _stat_token(legacy_path),
        _CACHE_GENERATION,
    )
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[0] == version:
            _CACHE.move_to_end(key)
            names = cached[1]
        else:
            names = None
    if names is None:
        names = _build_stored_tribe_names(
            projects_root=projects,
            agent_tribes_path=tribes_path,
            legacy_store_path=legacy_path,
        )
        with _CACHE_LOCK:
            _CACHE[key] = (version, names)
            _CACHE.move_to_end(key)
            while len(_CACHE) > _CACHE_MAX:
                _CACHE.popitem(last=False)
    return _merge_tribe_names(names, tuple(extra_tribes))


def _build_stored_tribe_names(
    *,
    projects_root: Path,
    agent_tribes_path: Path,
    legacy_store_path: Path,
) -> tuple[str, ...]:
    index = WaitDependencyIndex(
        named={},
        workflows={},
        agent_sessions={},
        clans={},
        tribes={},
        effective_clan_tribes={},
        agent_tribes=load_raw_agent_tribes(
            agent_tribes_path,
            legacy_path=legacy_store_path,
        ),
        global_stored_tribes=(),
        artifacts={},
        artifacts_by_dir={},
    )
    if projects_root.exists():
        artifact_rows = []
        for project_dir in projects_root.iterdir():
            if not project_dir.is_dir():
                continue
            for artifact_dir in iter_agent_artifact_dirs(
                project_dir.name,
                "ace-run",
                projects_root=projects_root,
            ):
                meta = read_json_dict(artifact_dir / "agent_meta.json")
                if meta is not None:
                    artifact_rows.append((artifact_dir, meta, project_dir.name))
        index.add_many(artifact_rows)
    return tuple(sorted(index.stored_tribe_names()))


def _merge_tribe_names(
    base: tuple[str, ...],
    extra: tuple[str, ...],
) -> tuple[str, ...]:
    return tuple(sorted({*(tribe for tribe in base if tribe), *extra}))


def _stat_token(path: Path) -> tuple[bool, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (False, 0, 0)
    return (True, stat.st_mtime_ns, stat.st_size)


__all__ = [
    "invalidate_agent_tribe_evidence_cache",
    "stored_tribe_names_for_resolution",
]
