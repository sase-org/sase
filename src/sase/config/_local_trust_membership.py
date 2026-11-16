"""Project identity resolution and registry-membership caches for local trust."""

from __future__ import annotations

import os
from pathlib import Path
import threading
from typing import Any

from sase.config.core import load_merged_config_for_local_path
from sase.content_layout import resolve_project_config_read_path
from sase.core.paths import sase_projects_dir

from ._local_trust_support import LocalCommandTrustManagementError, canonical_path

_project_records_cache_lock = threading.RLock()
_project_records_cache_token: tuple[Any, ...] | None = None
_project_records_cache_value: list[Any] | None = None
_project_records_cache_fingerprint: tuple[Any, ...] | None = None
_project_records_cache_generation: int | None = None
_primary_membership_cache_lock = threading.RLock()
_primary_membership_cache: dict[str, tuple[tuple[Any, ...], tuple[Any, ...]]] = {}
_primary_membership_cache_generation: int | None = None


def _stat_signature(path: Path | str | None) -> tuple[Any, ...] | None:
    """Return ``(str(path), mtime_ns, size)`` or ``None`` when missing."""
    if path is None:
        return None
    try:
        stat = Path(path).stat()
    except (OSError, ValueError):
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _projects_dir_token() -> tuple[Any, ...]:
    """Return the cheap project-records token for the membership caches."""
    from sase.config import _cache as config_cache

    generation = config_cache.config_cache_generation
    projects_dir = sase_projects_dir()
    try:
        dir_stat = projects_dir.stat()
        dir_sig: Any = (dir_stat.st_mtime_ns, dir_stat.st_size)
    except OSError:
        dir_sig = None
    try:
        with os.scandir(projects_dir) as entries:
            names = tuple(
                sorted(
                    entry.name
                    for entry in entries
                    if entry.is_dir(follow_symlinks=False)
                )
            )
    except OSError:
        names = None
    return (generation, str(projects_dir), dir_sig, names)


def _records_fingerprint(records: list[Any]) -> tuple[Any, ...]:
    """Return a value token for cached project records."""
    items: list[Any] = []
    for record in records:
        try:
            project_file = str(getattr(record, "project_file", ""))
            file_sig = _stat_signature(project_file) if project_file else None
        except Exception:
            file_sig = None
        items.append(
            (
                str(getattr(record, "project_name", "")),
                str(getattr(record, "state", "")),
                str(getattr(record, "workspace_dir", "") or ""),
                str(getattr(record, "project_dir", "")),
                project_file,
                file_sig,
            )
        )
    return tuple(sorted(items))


def _cached_project_records() -> list[Any]:
    """Return project records memoized per project-records token."""
    global _project_records_cache_token, _project_records_cache_value
    global _project_records_cache_fingerprint, _project_records_cache_generation
    global _primary_membership_cache, _primary_membership_cache_generation
    from sase.config import _cache as config_cache

    generation = config_cache.config_cache_generation
    token = _projects_dir_token()
    cached: list[Any] | None
    cached_token: tuple[Any, ...] | None = None
    cached_fingerprint: tuple[Any, ...] | None = None
    with _project_records_cache_lock:
        if (
            _project_records_cache_generation != generation
            or _project_records_cache_value is None
            or _project_records_cache_token is None
        ):
            cached = None
        else:
            cached = _project_records_cache_value
            cached_token = _project_records_cache_token
            cached_fingerprint = _project_records_cache_fingerprint
    if cached is not None and cached_token == token:
        try:
            if _records_fingerprint(cached) == cached_fingerprint:
                return cached
        except Exception:
            pass
    try:
        from sase.core.project_lifecycle_facade import list_project_records

        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except Exception:
        return cached if cached is not None else []
    try:
        fingerprint = _records_fingerprint(records)
    except Exception:
        fingerprint = None
    with _project_records_cache_lock:
        if config_cache.config_cache_generation != generation:
            return records
        _project_records_cache_token = token
        _project_records_cache_value = records
        _project_records_cache_fingerprint = fingerprint
        _project_records_cache_generation = generation
        if _primary_membership_cache_generation not in (None, generation):
            _primary_membership_cache = {}
            _primary_membership_cache_generation = generation
    return records


def _config_token_for_identity() -> tuple[Any, ...] | None:
    """Return the current config token, or ``None`` when unavailable."""
    try:
        from sase.config.core import current_config_token

        return current_config_token()
    except Exception:
        return None


def _cached_primary_membership(
    primary: Path,
    records_token: tuple[Any, ...],
    config_token: tuple[Any, ...] | None,
) -> tuple[Any, Any, Any]:
    """Return cached ``(effective, store, registry)`` for one primary.

    The result mirrors the three values the registry scan builds per primary:
    the merged config, the ``WorkspaceStore``, and the registry read. The
    cache key covers the primary path, the project-records token, the
    primary config's stat signature, the registry file's stat signature,
    and the config token.
    """
    global _primary_membership_cache_generation
    from sase.config import _cache as config_cache

    generation = config_cache.config_cache_generation
    primary_key = str(primary)
    try:
        primary_config = resolve_project_config_read_path(primary)
    except Exception:
        primary_config = None
    primary_config_stat = _stat_signature(primary_config)
    with _primary_membership_cache_lock:
        if _primary_membership_cache_generation not in (None, generation):
            _primary_membership_cache.clear()
            _primary_membership_cache_generation = generation
        entry = _primary_membership_cache.get(primary_key)
    if entry is not None:
        key, value = entry
        (
            key_records_token,
            key_config_token,
            key_primary_config_stat,
            key_registry_stat,
            key_registry_path,
            key_generation,
        ) = key
        if (
            key_generation == generation
            and key_records_token == records_token
            and key_config_token == config_token
            and key_primary_config_stat == primary_config_stat
        ):
            try:
                current_registry_stat = _stat_signature(key_registry_path)
            except Exception:
                current_registry_stat = None
            if current_registry_stat == key_registry_stat:
                _effective, _store, _registry = value
                return _effective, _store, _registry
    try:
        # The workspace root may be selected in the project's own config.
        effective = load_merged_config_for_local_path(primary_config)
        from sase.workspace_provider.registry import (
            read_registry_file,
            registry_path,
        )
        from sase.workspace_provider.store import WorkspaceStore

        store = WorkspaceStore(str(primary), config=effective)
        registry_file = registry_path(store.root_dir)
        registry = read_registry_file(registry_file, strict=True)
        registry_stat = _stat_signature(registry_file)
    except Exception:
        raise
    key = (
        records_token,
        config_token,
        primary_config_stat,
        registry_stat,
        str(registry_file) if "registry_file" in locals() else None,
        generation,
    )
    with _primary_membership_cache_lock:
        if config_cache.config_cache_generation == generation:
            _primary_membership_cache[primary_key] = (
                key,
                (effective, store, registry),
            )
            _primary_membership_cache_generation = generation
    return effective, store, registry


def _project_identity(root: Path, config_path: Path) -> str:
    """Resolve a host project record only from its primary checkout or registry."""
    records = _cached_project_records()
    try:
        records_token = (
            _project_records_cache_token
            if _project_records_cache_token is not None
            else _projects_dir_token()
        )
    except Exception:
        records_token = ()
    try:
        config_token = _config_token_for_identity()
    except Exception:
        config_token = None

    root_key = str(root)
    projects = [
        record for record in records if record.is_project and not record.system_managed
    ]

    primary_matches: list[tuple[Any, Path]] = []
    for record in projects:
        if not record.workspace_dir:
            continue
        primary = canonical_path(Path(record.workspace_dir))
        if str(primary) == root_key:
            primary_matches.append((record, primary))
    if len(primary_matches) == 1:
        record, primary = primary_matches[0]
        return _registered_identity(record.project_dir, primary)
    if primary_matches:
        return f"checkout:v1:{root}"

    registered: list[tuple[str, Path]] = []
    for record in projects:
        if not record.workspace_dir:
            continue
        primary = canonical_path(Path(record.workspace_dir))
        if not primary.is_dir():
            continue
        try:
            effective, store, registry = _cached_primary_membership(
                primary, records_token, config_token
            )
            if registry is None:
                continue
            if canonical_path(Path(registry.primary_workspace_dir)) != primary:
                continue
            if registry.project_key != store.project_key:
                continue
            if any(
                canonical_path(Path(entry.checkout_dir)) == root
                for entry in registry.workspaces.values()
            ):
                registered.append(
                    (_registered_identity(record.project_dir, primary), primary)
                )
        except Exception:
            # Missing or ambiguous host membership never inherits project trust.
            continue

    identities = {identity for identity, _primary in registered}
    if len(identities) == 1:
        return next(iter(identities))
    return f"checkout:v1:{root}"


def _registered_identity(project_dir: str, primary: Path) -> str:
    project_record = canonical_path(Path(project_dir))
    return f"project:v1:{project_record}:{primary}"


def project_identity_for_config(root: Path, config_path: Path) -> str:
    """Resolve the versioned project identity management uses for trust.

    Public accessor so runtime enforcement binds the same identity the
    human acknowledgment records; never derive a parallel identity.
    """
    return _project_identity(root, config_path)
