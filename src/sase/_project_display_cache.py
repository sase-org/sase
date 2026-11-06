"""Cached project-display snapshots and freshness tokens."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from pathlib import Path
import os
from threading import RLock

from sase._project_display_snapshot import (
    ProjectDisplaySnapshot,
    ProjectRefDisplaySnapshot,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records


_PROJECT_DISPLAY_NAME_CACHE: dict[str, ProjectDisplaySnapshot] | None = None
_PROJECT_DISPLAY_FRESHNESS_TOKENS: dict[str, object] | None = None
_PROJECT_DISPLAY_NAME_CACHE_LOCK = RLock()

#: Memoized ``humanize_cl_name`` results for the default (cached-map) path,
#: keyed by ``(generation, name)``. Display labels repeat heavily across
#: roster scans (every clan member shares its clan's label), so caching
#: keeps those scans off the root-key/pathlib round-trip behind the map
#: lookup. The generation bumps in :func:`invalidate_project_display_snapshot`,
#: the single funnel for map mutations, so entries never outlive their map.
_HUMANIZE_CACHE: dict[tuple[int, str], str] = {}
_HUMANIZE_CACHE_GEN = 0
_HUMANIZE_CACHE_CAP = 16384


def _projects_root(projects_root: Path | str | None) -> Path:
    if projects_root is None:
        return sase_projects_dir()
    return Path(projects_root).expanduser()


@lru_cache(maxsize=64)
def _cached_projects_root_key(
    root_arg: str | None,
    sase_home_env: str | None,
    home_env: str | None,
    cwd: str,
) -> str:
    """Return the cache key for one resolved projects root.

    The resolved root is a pure function of these four inputs
    (``SASE_HOME``/``HOME`` feed ``sase_home()``; *cwd* feeds
    :meth:`Path.absolute` for relative roots), so keying on them is exact
    and recomputes automatically after any ``chdir`` or env change instead
    of rebuilding ``Path`` objects on every display-name lookup.
    """
    return str(_projects_root(root_arg).absolute())


def _projects_root_cache_key(projects_root: Path | str | None) -> str:
    root_arg = None if projects_root is None else os.fspath(projects_root)
    return _cached_projects_root_key(
        root_arg,
        os.environ.get("SASE_HOME"),
        os.environ.get("HOME"),
        os.getcwd(),
    )


def load_project_display_snapshot(
    projects_root: Path | str | None = None,
) -> ProjectDisplaySnapshot:
    """Fresh-load a snapshot from one lifecycle inventory read.

    This entry point is intended for worker/off-thread refresh paths. Inventory
    failures degrade to an empty snapshot, whose lookups fall back to canonical
    keys.
    """
    root = _projects_root(projects_root)
    try:
        records = list_project_records(root, "all", include_home=True)
    except Exception:
        return ProjectDisplaySnapshot()
    return ProjectDisplaySnapshot.from_records(records)


def load_project_ref_display_snapshot(
    projects_root: Path | str | None = None,
) -> ProjectRefDisplaySnapshot:
    """Fresh-load key, label, and alias projections in one inventory read.

    Inventory failures degrade to an empty projection whose display lookups
    preserve the caller's ref and whose identity lookups return ``None``.
    """
    root = _projects_root(projects_root)
    try:
        records = list_project_records(root, "all", include_home=True)
        return ProjectRefDisplaySnapshot.from_records(records)
    except Exception:
        return ProjectRefDisplaySnapshot()


def _project_display_freshness_token(
    resolved_root: Path,
) -> object | None:
    """Return a cheap freshness token for one projects root, or ``None``.

    The token scans the projects root once for directory membership and records
    ``(name, mtime_ns, size)`` for each project's active ProjectSpec filenames.
    ``None`` means the root could not be scanned, so the caller treats the
    snapshot as changed and reloads.
    """
    try:
        from sase.ace.patch.project_spec_path import (
            active_project_spec_filename,
            legacy_active_project_spec_filename,
        )
    except Exception:  # noqa: BLE001 - token degrades to always-reload.
        return None
    try:
        with os.scandir(resolved_root) as iterator:
            entries = list(iterator)
    except OSError:
        return None
    top_level: list[str] = sorted(entry.name for entry in entries)
    spec_stats: list[tuple[str, int, int]] = []
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        dirname = entry.name
        for filename in (
            active_project_spec_filename(dirname),
            legacy_active_project_spec_filename(dirname),
        ):
            try:
                stat = os.stat(os.path.join(resolved_root, dirname, filename))
            except OSError:
                continue
            spec_stats.append((f"{dirname}/{filename}", stat.st_mtime_ns, stat.st_size))
    return (str(resolved_root), tuple(top_level), tuple(sorted(spec_stats)))


def _store_display_snapshot_locked(
    cache_key: str,
    snapshot: ProjectDisplaySnapshot,
    token: object | None,
) -> None:
    """Store one snapshot and its freshness token; caller holds the lock."""
    global _PROJECT_DISPLAY_NAME_CACHE  # noqa: PLW0603
    global _PROJECT_DISPLAY_FRESHNESS_TOKENS  # noqa: PLW0603
    if _PROJECT_DISPLAY_NAME_CACHE is None:
        _PROJECT_DISPLAY_NAME_CACHE = {}
    if _PROJECT_DISPLAY_FRESHNESS_TOKENS is None:
        _PROJECT_DISPLAY_FRESHNESS_TOKENS = {}
    _PROJECT_DISPLAY_NAME_CACHE[cache_key] = snapshot
    _PROJECT_DISPLAY_FRESHNESS_TOKENS[cache_key] = token


def _bump_humanize_cache() -> None:
    """Retire every memoized default-path ``humanize_cl_name`` entry."""
    global _HUMANIZE_CACHE_GEN  # noqa: PLW0603
    _HUMANIZE_CACHE_GEN += 1
    _HUMANIZE_CACHE.clear()


def humanize_cl_name_cached(name: str, compute: Callable[[], str]) -> str:
    """Return a memoized default-path ``humanize_cl_name`` result."""
    key = (_HUMANIZE_CACHE_GEN, name)
    cached = _HUMANIZE_CACHE.get(key)
    if cached is not None:
        return cached
    result = compute()
    if len(_HUMANIZE_CACHE) >= _HUMANIZE_CACHE_CAP:
        _HUMANIZE_CACHE.clear()
    _HUMANIZE_CACHE[key] = result
    return result


def refresh_project_display_snapshot(
    projects_root: Path | str | None = None,
) -> bool:
    """Revalidate the cached snapshot against cross-process changes.

    Worker and tick use only: render paths never call this. When the ProjectSpec
    freshness token is unchanged, return ``False`` without loading records.
    Otherwise load records; on failure keep the previous snapshot and token and
    return ``False`` so the next call retries. On success store the new token;
    when the label ``signature`` changed (including a first population), swap
    the snapshot first, then bump ``_HUMANIZE_CACHE_GEN``, clear
    ``_HUMANIZE_CACHE``, and invalidate the macro project identity, returning
    ``True``.
    """
    cache_key = _projects_root_cache_key(projects_root)
    resolved = _projects_root(projects_root)
    new_token = _project_display_freshness_token(resolved)
    with _PROJECT_DISPLAY_NAME_CACHE_LOCK:
        cached = (
            _PROJECT_DISPLAY_NAME_CACHE.get(cache_key)
            if _PROJECT_DISPLAY_NAME_CACHE is not None
            else None
        )
        old_token = (
            _PROJECT_DISPLAY_FRESHNESS_TOKENS.get(cache_key)
            if _PROJECT_DISPLAY_FRESHNESS_TOKENS is not None
            else None
        )
        old_signature = cached.signature if cached is not None else None
    if new_token is not None and cached is not None and new_token == old_token:
        return False
    try:
        records = list_project_records(resolved, "all", include_home=True)
    except Exception:  # noqa: BLE001 - keep labels; retry on the next call.
        return False
    fresh = ProjectDisplaySnapshot.from_records(records)
    changed = old_signature is None or fresh.signature != old_signature
    with _PROJECT_DISPLAY_NAME_CACHE_LOCK:
        _store_display_snapshot_locked(cache_key, fresh, new_token)
        if not changed:
            return False
        _bump_humanize_cache()
    from sase.macro.project_identity import invalidate_macro_project_identity

    invalidate_macro_project_identity()
    return True


def _get_project_display_snapshot(
    projects_root: Path | str | None = None,
) -> ProjectDisplaySnapshot:
    """Return the explicitly managed cached snapshot for convenience callers.

    Lookups are memory-only. Long-lived processes call
    :func:`refresh_project_display_snapshot` at their worker or tick boundaries;
    :func:`invalidate_project_display_snapshot` remains the in-process mutation
    path.
    """
    global _PROJECT_DISPLAY_NAME_CACHE  # noqa: PLW0603

    cache_key = _projects_root_cache_key(projects_root)
    with _PROJECT_DISPLAY_NAME_CACHE_LOCK:
        if _PROJECT_DISPLAY_NAME_CACHE is None:
            _PROJECT_DISPLAY_NAME_CACHE = {}
        cached = _PROJECT_DISPLAY_NAME_CACHE.get(cache_key)
        if cached is None:
            cached = load_project_display_snapshot(projects_root)
            _store_display_snapshot_locked(
                cache_key,
                cached,
                _project_display_freshness_token(_projects_root(projects_root)),
            )
        return cached


def cached_project_display_snapshot(
    projects_root: Path | str | None = None,
) -> ProjectDisplaySnapshot:
    """Return the managed display snapshot, loading it only when it is cold.

    Long-lived UI callers should invoke this from a worker when the cache may
    need its initial inventory read, then keep the returned immutable value
    for the surface they are rendering.
    """
    return _get_project_display_snapshot(projects_root)


def project_display_snapshot_is_warm(
    projects_root: Path | str | None = None,
) -> bool:
    """Return whether a display snapshot is cached for *projects_root*."""
    cache_key = _projects_root_cache_key(projects_root)
    with _PROJECT_DISPLAY_NAME_CACHE_LOCK:
        return (
            _PROJECT_DISPLAY_NAME_CACHE is not None
            and cache_key in _PROJECT_DISPLAY_NAME_CACHE
        )


def invalidate_project_display_snapshot(
    projects_root: Path | str | None = None,
) -> None:
    """Invalidate the cached snapshot for *projects_root* without disk I/O."""
    cache_key = _projects_root_cache_key(projects_root)
    with _PROJECT_DISPLAY_NAME_CACHE_LOCK:
        if _PROJECT_DISPLAY_NAME_CACHE is not None:
            _PROJECT_DISPLAY_NAME_CACHE.pop(cache_key, None)
        if _PROJECT_DISPLAY_FRESHNESS_TOKENS is not None:
            _PROJECT_DISPLAY_FRESHNESS_TOKENS.pop(cache_key, None)

    # The humanize memo keys on a generation instead of the map, so any
    # invalidation retires every entry even when only one root was popped.
    _bump_humanize_cache()

    from sase.macro.project_identity import invalidate_macro_project_identity

    invalidate_macro_project_identity()
