"""Centralized configuration facade with multi-file merge support.

Loads ``default_config.yml`` (bundled in the package) as the base layer, then
plugin defaults, ``~/.config/sase/sase.yml``, machine-selected overlays, and
finally the current project's config.  Local config can be disabled with
``set_include_local_config(False)`` for processes such as ``sase ace``.

Low-level source IO and merging live in :mod:`sase.config.loading`; raw owner
selection lives in :mod:`sase.config.identity`.  This facade owns the public API
and process-wide caches, including stale-while-revalidate freshness checks that
keep stat/glob IO off latency-sensitive render paths.
"""

from __future__ import annotations

import importlib.resources
import logging
import threading
import time
from pathlib import Path
from typing import Any

from sase.config.identity import (
    AgentOwnerConfigSnapshot,
    RawOverlayIdentity,
    build_agent_owner_config_snapshot,
    is_valid_machine_name,
    read_machine_name_selector,
    read_machine_name_selector_text,
)
from sase.config.layers import (
    DEPRECATED_TOP_LEVEL_KEYS,
    RETIRED_SDD_SELECTOR_KEYS,
    UNSUPPORTED_TOP_LEVEL_KEYS,
    ConfigLayer,
    load_config_layers as _load_config_layers,
    load_yaml_file_with_metadata,
    without_retired_sdd_selectors,
)
from sase.config.loading import (
    deep_merge as _deep_merge,
    get_overlay_paths as _get_overlay_paths_from_dir,
    load_default_config as _load_default_config_resource,
    load_plugin_configs as _load_plugin_config_resources,
    load_yaml_file as _load_yaml_file_path,
    merge_config_sources,
)
from sase.config.xprompt_sources import (
    load_xprompts_by_source as _load_xprompts_by_source,
)
from sase.content_layout import discover_project_root, resolve_project_layout
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.paths import machine_name_path


log = logging.getLogger(__name__)

CONFIG_DIR = Path("~/.config/sase").expanduser()
CHEZMOI_HOME = Path("~/.local/share/chezmoi/home").expanduser()
# When false, project-local config is excluded from the source chain.
_include_local_config = True

# Bundled and plugin defaults are process-static.  The merged and identity
# values are keyed by ``current_config_token()``.  Callers must not mutate a
# returned merged dict because repeat reads intentionally return the same object.
_default_config_cache: dict[str, Any] | None = None
_plugin_configs_cache: list[dict[str, Any]] | None = None
_merged_config_cache_token: tuple[Any, ...] | None = None
_merged_config_cache_value: dict[str, Any] | None = None
_agent_owner_config_cache_token: tuple[Any, ...] | None = None
_agent_owner_config_cache_value: AgentOwnerConfigSnapshot | None = None

# Explicit clears increment the generation so rapid same-size edits cannot
# retain an otherwise-identical filesystem token.
_CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS = 0.75
_config_cache_generation = 0
_current_config_token_cache_value: tuple[Any, ...] | None = None
_current_config_token_cache_deadline = 0.0
_current_config_token_cache_epoch = 0
_current_config_token_cache_lock = threading.RLock()
_current_config_token_refresh_thread: threading.Thread | None = None


def _reset_current_config_token_cache_locked() -> None:
    """Reset the config-token cache while its lock is held."""
    global _current_config_token_cache_value, _current_config_token_cache_deadline
    global _current_config_token_cache_epoch
    _current_config_token_cache_value = None
    _current_config_token_cache_deadline = 0.0
    _current_config_token_cache_epoch += 1


def _reset_current_config_token_cache() -> None:
    """Force the next config-token lookup to inspect the filesystem."""
    with _current_config_token_cache_lock:
        _reset_current_config_token_cache_locked()


def set_include_local_config(value: bool) -> None:
    """Enable or disable loading of the current project's config."""
    global _include_local_config
    with _current_config_token_cache_lock:
        if _include_local_config == value:
            return
        _include_local_config = value
        _reset_current_config_token_cache()


def stat_token(path: Path) -> tuple[str, int, int] | None:
    """Return ``(path, mtime_ns, size)`` or ``None`` when *path* is missing.

    Combining mtime_ns with size handles coarse-grained filesystem timestamps.
    """
    try:
        stat = path.stat()
    except (OSError, FileNotFoundError):
        return None
    return (str(path), stat.st_mtime_ns, stat.st_size)


def _compute_current_config_token() -> tuple[Any, ...]:
    """Inspect config sources and return their current cache key."""
    parts: list[Any] = [_config_cache_generation, _include_local_config]
    if _include_local_config:
        try:
            parts.append(str(Path.cwd()))
        except FileNotFoundError:
            parts.append(None)
    else:
        parts.append(None)

    parts.append(stat_token(CONFIG_DIR / "sase.yml"))
    parts.append(stat_token(machine_name_path()))
    parts.append(tuple(stat_token(path) for path in _get_overlay_paths()))

    project_root = discover_project_root() if _include_local_config else None
    if project_root is None:
        parts.append(None)
    else:
        config = resolve_project_layout(project_root).config
        parts.append(tuple(stat_token(path) for path in config.candidates))
    return tuple(parts)


def _refresh_current_config_token(cache_epoch: int) -> None:
    """Recompute and publish a config token from the daemon worker."""
    global _current_config_token_cache_value, _current_config_token_cache_deadline
    global _current_config_token_refresh_thread
    try:
        token = _compute_current_config_token()
    except Exception:
        log.debug("Background config-token refresh failed", exc_info=True)
        token = None

    with _current_config_token_cache_lock:
        if cache_epoch == _current_config_token_cache_epoch:
            if token is not None:
                _current_config_token_cache_value = token
            _current_config_token_cache_deadline = (
                time.monotonic() + _CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS
            )
        _current_config_token_refresh_thread = None


def current_config_token() -> tuple[Any, ...]:
    """Return the cache key for the current merged-config state.

    The first lookup after process start or explicit invalidation is
    synchronous.  An expired cached token is returned stale while a single
    daemon worker revalidates it off-thread.
    """
    global _current_config_token_cache_value, _current_config_token_cache_deadline
    global _current_config_token_refresh_thread

    with _current_config_token_cache_lock:
        cached = _current_config_token_cache_value
        if cached is None:
            token = _compute_current_config_token()
            _current_config_token_cache_value = token
            _current_config_token_cache_deadline = (
                time.monotonic() + _CONFIG_TOKEN_REFRESH_INTERVAL_SECONDS
            )
            return token

        if (
            time.monotonic() >= _current_config_token_cache_deadline
            and _current_config_token_refresh_thread is None
        ):
            refresh_thread = threading.Thread(
                target=_refresh_current_config_token,
                args=(_current_config_token_cache_epoch,),
                name="sase-config-token-refresh",
                daemon=True,
            )
            _current_config_token_refresh_thread = refresh_thread
            refresh_thread.start()
        return cached


def clear_config_cache() -> None:
    """Drop cached config layers and force the next freshness inspection."""
    global _config_cache_generation
    global _default_config_cache, _plugin_configs_cache
    global _merged_config_cache_token, _merged_config_cache_value
    global _agent_owner_config_cache_token, _agent_owner_config_cache_value
    with _current_config_token_cache_lock:
        _config_cache_generation += 1
        _default_config_cache = None
        _plugin_configs_cache = None
        _merged_config_cache_token = None
        _merged_config_cache_value = None
        _agent_owner_config_cache_token = None
        _agent_owner_config_cache_value = None
        _reset_current_config_token_cache()


def get_use_chezmoi() -> bool:
    """Return whether chezmoi path remapping is enabled."""
    return bool(load_merged_config().get("use_chezmoi", False))


def get_agent_owner_identity() -> AgentOwnerIdentity | None:
    """Return the complete owner configured by the selected raw overlay.

    Identity is resolved outside the ordinary merge chain so defaults, plugins,
    the user base file, ordinary overlays, and project-local config cannot
    change its provenance.
    """
    return get_agent_owner_config_snapshot().owner


def require_agent_owner_identity() -> AgentOwnerIdentity:
    """Return the complete owner or raise with an actionable initializer hint."""
    snapshot = get_agent_owner_config_snapshot()
    if snapshot.owner is None:
        raise RuntimeError(
            "SASE agent owner identity is not configured "
            f"({snapshot.detail}); run `sase config init`."
        )
    return snapshot.owner


def get_machine_name() -> str | None:
    """Compatibility projection of a complete configured owner identity."""
    owner = get_agent_owner_identity()
    return owner.machine_name if owner is not None else None


def require_machine_name() -> str:
    """Compatibility projection requiring a complete configured owner."""
    return require_agent_owner_identity().machine_name


DEFAULT_MAX_RUNNING_AGENTS = 10
DEFAULT_TASK_HISTORY_LIMIT = 100


def get_configured_max_running_agents() -> int:
    """Return the validated configured global runner limit.

    The merged-config cache lets admission callers poll this accessor without
    reparsing unchanged YAML while still observing live edits.
    """
    value = load_merged_config().get("max_running_agents", DEFAULT_MAX_RUNNING_AGENTS)
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_MAX_RUNNING_AGENTS


def get_task_history_limit() -> int:
    """Return the validated configured finished-task retention limit."""
    tasks = load_merged_config().get("tasks", {})
    value = (
        tasks.get("history_limit", DEFAULT_TASK_HISTORY_LIMIT)
        if isinstance(tasks, dict)
        else DEFAULT_TASK_HISTORY_LIMIT
    )
    if type(value) is int and value >= 1:
        return value
    return DEFAULT_TASK_HISTORY_LIMIT


def get_max_running_agents(now: float | None = None) -> int:
    """Return the live admission limit, preferring a temporary override.

    Override state errors propagate so admission callers fail closed for that
    poll rather than silently falling back to configuration.
    """
    from sase.config.runner_limit_override import get_active_runner_limit_override

    override = get_active_runner_limit_override(now)
    return (
        override.limit if override is not None else get_configured_max_running_agents()
    )


# These wrappers preserve long-standing ``sase.config.core`` patch points while
# keeping source IO implementations out of this facade.
def _load_default_config() -> dict[str, Any]:
    return _load_default_config_resource(importlib.resources.files)


def _load_yaml_file(path: Path) -> dict[str, Any] | None:
    return _load_yaml_file_path(path)


def _get_overlay_paths() -> list[Path]:
    return _get_overlay_paths_from_dir(CONFIG_DIR)


def _load_plugin_configs() -> list[dict[str, Any]]:
    return _load_plugin_config_resources(importlib.resources.files)


def _build_agent_owner_config_snapshot() -> AgentOwnerConfigSnapshot:
    selector_path = machine_name_path()
    return build_agent_owner_config_snapshot(
        config_dir=CONFIG_DIR,
        overlay_paths=_get_overlay_paths(),
        yaml_loader=_load_yaml_file,
        selector_path=selector_path,
        selector_text=read_machine_name_selector_text(selector_path),
        selector=read_machine_name_selector(selector_path),
    )


def get_agent_owner_config_snapshot() -> AgentOwnerConfigSnapshot:
    """Return the cached selected-overlay identity state used by init/doctor."""
    global _agent_owner_config_cache_token, _agent_owner_config_cache_value
    token = current_config_token()
    if (
        _agent_owner_config_cache_value is not None
        and _agent_owner_config_cache_token == token
    ):
        return _agent_owner_config_cache_value
    snapshot = _build_agent_owner_config_snapshot()
    _agent_owner_config_cache_token = token
    _agent_owner_config_cache_value = snapshot
    return snapshot


def discover_machine_names() -> tuple[str, ...]:
    """Return valid nested-first machine discriminators from raw overlays."""
    return tuple(
        sorted(
            {
                name
                for overlay in get_agent_owner_config_snapshot().overlays
                if (name := overlay.discriminator) is not None
                and is_valid_machine_name(name)
            }
        )
    )


def _get_selected_overlay_paths() -> list[Path]:
    """Return ordinary overlays plus the overlay selected for this machine.

    Freshness tokens still stat all overlays, so edits to foreign overlays
    invalidate the cached view without parsing them on render-path reads.
    """
    snapshot = get_agent_owner_config_snapshot()
    selected: list[Path] = []
    for overlay in snapshot.overlays:
        if not overlay.declares_machine_overlay:
            selected.append(overlay.path)
        elif overlay.discriminator == snapshot.selector:
            selected.append(overlay.path)
    return selected


def get_local_config_path() -> Path | None:
    """Return the selected project-local config path, if one exists.

    Canonical ``sase/sase.yml`` is preferred, while root-level ``sase.yml``
    remains readable for compatibility.
    """
    if not _include_local_config:
        return None
    project_root = discover_project_root()
    if project_root is None:
        return None
    return resolve_project_layout(project_root).config.resolve_read("project config")


def _get_local_config_write_path() -> Path | None:
    """Return the canonical destination for the current project's config."""
    if not _include_local_config:
        return None
    project_root = discover_project_root()
    if project_root is None:
        return None
    return resolve_project_layout(project_root).config.write_path


def load_xprompts_by_source() -> list[tuple[str, dict[str, Any]]]:
    """Load config-defined xprompts with source provenance."""
    return _load_xprompts_by_source(
        config_dir=CONFIG_DIR,
        default_loader=_load_default_config,
        yaml_loader=_load_yaml_file,
        overlay_paths=_get_selected_overlay_paths(),
        local_path=get_local_config_path(),
        resource_files=importlib.resources.files,
    )


def load_merged_config() -> dict[str, Any]:
    """Load and cache the effective config from all source layers.

    The merge order is bundled defaults, plugin defaults, user config (lists
    replace), selected overlays (lists concatenate), and project-local config
    (lists concatenate).  The cache invalidates when candidate files, cwd, or
    local-config inclusion changes.
    """
    global _default_config_cache, _plugin_configs_cache
    global _merged_config_cache_token, _merged_config_cache_value

    token = current_config_token()
    if _merged_config_cache_value is not None and _merged_config_cache_token == token:
        return _merged_config_cache_value
    if _default_config_cache is None:
        _default_config_cache = _load_default_config()
    if _plugin_configs_cache is None:
        _plugin_configs_cache = _load_plugin_configs()

    result = merge_config_sources(
        default_config=_default_config_cache,
        plugin_configs=_plugin_configs_cache,
        user_base_path=CONFIG_DIR / "sase.yml",
        overlay_paths=_get_selected_overlay_paths(),
        selected_identity_snapshot=get_agent_owner_config_snapshot(),
        local_path=get_local_config_path(),
        yaml_loader=_load_yaml_file,
    )
    _merged_config_cache_token = token
    _merged_config_cache_value = result
    return result


def load_config_layers() -> list[ConfigLayer]:
    """Load config-layer metadata without merging the layers."""
    local_path = get_local_config_path()
    fallback = (
        local_path or _get_local_config_write_path() or Path.cwd() / "sase" / "sase.yml"
    )
    return _load_config_layers(
        config_dir=CONFIG_DIR,
        default_loader=_load_default_config,
        overlay_paths=_get_selected_overlay_paths(),
        local_path=local_path,
        local_fallback_path=fallback,
        resource_files=importlib.resources.files,
    )
