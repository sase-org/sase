"""Config identity memo, resolution, local config, and path helpers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
import os
import threading
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from sase._yaml_safe import yaml_safe_load
from sase.content_layout import resolve_project_config_read_path


@dataclass(frozen=True)
class RepoConfigCacheKey:
    """Hash a config by value while retaining the original mapping on misses."""

    token: tuple[Any, ...]
    config: Mapping[str, Any] = field(compare=False, hash=False, repr=False)


def resolution_config(
    primary_workspace_dir: str,
    config: Mapping[str, Any] | None,
) -> Mapping[str, Any]:
    if config is not None:
        return config

    primary = str(Path(primary_workspace_dir).expanduser().resolve(strict=False))
    return _resolution_config_cached(primary)


@lru_cache(maxsize=256)
def _resolution_config_cached(primary_workspace_dir: str) -> Mapping[str, Any]:
    """Resolve config once per primary workspace until explicitly reset."""

    from sase.config.core import load_merged_config

    merged = load_merged_config()
    local_config = read_project_local_config(primary_workspace_dir)
    if local_config:
        return _merge_resolution_config(merged, local_config)
    return merged


def _merge_resolution_config(
    base: Mapping[str, Any], override: Mapping[str, Any]
) -> dict[str, Any]:
    result: dict[str, Any] = dict(base)
    for key, override_value in override.items():
        base_value = result.get(key)
        if isinstance(base_value, Mapping) and isinstance(override_value, Mapping):
            result[key] = _merge_resolution_config(base_value, override_value)
        elif isinstance(base_value, list) and isinstance(override_value, list):
            result[key] = [*base_value, *override_value]
        else:
            result[key] = override_value
    return result


#: Bound for the config-identity memo in :func:`repo_config_cache_key`. The
#: map holds the returned keys, which retain their config mapping, so an id
#: cannot be recycled while its entry is cached.
_CONFIG_KEY_MEMO_MAXSIZE = 64
_CONFIG_KEY_MEMO_LOCK = threading.Lock()
_CONFIG_KEY_MEMO: dict[int, RepoConfigCacheKey] = {}


def repo_config_cache_key(config: Mapping[str, Any]) -> RepoConfigCacheKey:
    """Return a hashable value token retaining the source config mapping.

    Memoized by config object identity: repeated calls with the same mapping
    object (for example one inventory build freezing per sidecar) pay the
    freeze once. Distinct objects with equal contents still freeze
    independently, so value semantics are unchanged.
    """

    config_id = id(config)
    with _CONFIG_KEY_MEMO_LOCK:
        cached = _CONFIG_KEY_MEMO.get(config_id)
        if cached is not None and cached.config is config:
            return cached
    fresh = RepoConfigCacheKey(_freeze_config_value(config), config)
    with _CONFIG_KEY_MEMO_LOCK:
        existing = _CONFIG_KEY_MEMO.get(config_id)
        if existing is not None and existing.config is config:
            return existing
        if len(_CONFIG_KEY_MEMO) >= _CONFIG_KEY_MEMO_MAXSIZE:
            _CONFIG_KEY_MEMO.pop(next(iter(_CONFIG_KEY_MEMO)))
        _CONFIG_KEY_MEMO[config_id] = fresh
        return fresh


def _freeze_config_value(value: Any) -> tuple[Any, ...]:
    """Return a stable, type-aware token for JSON-shaped config values."""

    if isinstance(value, Mapping):
        items = (
            (
                type(key).__module__,
                type(key).__qualname__,
                repr(key),
                _freeze_config_value(item),
            )
            for key, item in value.items()
        )
        return ("mapping", *sorted(items))
    if isinstance(value, list):
        return ("list", *(_freeze_config_value(item) for item in value))
    if isinstance(value, tuple):
        return ("tuple", *(_freeze_config_value(item) for item in value))
    if isinstance(value, (set, frozenset)):
        return (
            type(value).__qualname__,
            *sorted(_freeze_config_value(item) for item in value),
        )
    try:
        hash(value)
    except TypeError:
        return (type(value).__module__, type(value).__qualname__, repr(value))
    return (type(value).__module__, type(value).__qualname__, value)


def reset_state_caches() -> None:
    """Clear resolution and config-key memos owned by this module."""

    _resolution_config_cached.cache_clear()
    with _CONFIG_KEY_MEMO_LOCK:
        _CONFIG_KEY_MEMO.clear()


def read_project_local_config(primary_workspace_dir: str) -> dict[str, Any]:
    path = resolve_project_config_read_path(primary_workspace_dir)
    if path is None:
        return {}
    try:
        loaded = yaml_safe_load(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return {}
    if isinstance(loaded, dict):
        return loaded
    return {}


def resolve_config_path(path: str, *, relative_to: str) -> str:
    expanded = os.path.expandvars(os.path.expanduser(path))
    candidate = Path(expanded)
    if not candidate.is_absolute():
        candidate = Path(relative_to) / candidate
    return normalize_path(str(candidate))


def normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))
