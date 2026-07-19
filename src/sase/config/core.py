"""Centralized configuration loading with multi-file merge support.

Loads ``default_config.yml`` (bundled in the package) as the base layer,
then deep-merges plugin ``default_config.yml`` files, then
``~/.config/sase/sase.yml`` (with list replacement), then
deep-merges any overlay files matching ``~/.config/sase/sase_*.yml`` (sorted
alphabetically, with list concatenation) on top, then finally the current
project's ``sase/sase.yml`` (with root-level ``sase.yml`` as a read fallback),
unless local config loading has been disabled via ``set_include_local_config(False)``
(e.g. for ``sase ace`` runs where the TUI should not inherit repo-level config).

After the first config-token read, filesystem freshness checks use
stale-while-revalidate semantics so render-path callers never perform stat/glob
I/O.  Explicit cache invalidation still makes the next read synchronous, while
external file edits may take roughly two polling windows to become visible.
"""

import importlib.resources
import logging
import threading
import time
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from sase.content_layout import discover_project_root, resolve_project_layout
from sase.config.layers import (
    DEPRECATED_TOP_LEVEL_KEYS,
    RETIRED_SDD_SELECTOR_KEYS,
    UNSUPPORTED_TOP_LEVEL_KEYS,
    ConfigLayer,
    load_config_layers as _load_config_layers,
    load_yaml_file_with_metadata,
    without_retired_sdd_selectors,
)
from sase.config.xprompt_sources import (
    load_xprompts_by_source as _load_xprompts_by_source,
)


log = logging.getLogger(__name__)

CONFIG_DIR = Path("~/.config/sase").expanduser()
CHEZMOI_HOME = Path("~/.local/share/chezmoi/home").expanduser()

# When False, get_local_config_path() always returns None.
# Set to False for `sase ace` so the TUI doesn't pick up a repo's project config;
# agent runs are separate processes and keep the default (True).
_include_local_config: bool = True

# Process-wide caches.  The merged-config cache is keyed on a tuple of mtime/size
# stat tokens for every candidate config file (cheap to recompute), plus the
# include-local flag and cwd.  The bundled-default and plugin-default layers ship
# inside packages and never change in a process, so they're memoized once.  Note:
# callers must not mutate the returned dict; the cache returns the same object.
_default_config_cache: dict[str, Any] | None = None
_plugin_configs_cache: list[dict[str, Any]] | None = None
_merged_config_cache_token: tuple[Any, ...] | None = None
_merged_config_cache_value: dict[str, Any] | None = None

# Config freshness checks run from latency-sensitive render paths, so bound the
# synchronous stat/glob work to one pass per short polling window.  Explicit
# cache clears increment the generation to invalidate downstream caches keyed by
# ``current_config_token()`` even when a rapid, same-size edit happens to retain
# an otherwise-identical filesystem token.
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
    """Return ``(path, mtime_ns, size)`` for *path* or ``None`` if missing.

    Combines mtime_ns with size to defeat coarse-grained filesystem timestamps.
    """
    try:
        st = path.stat()
    except (OSError, FileNotFoundError):
        return None
    return (str(path), st.st_mtime_ns, st.st_size)


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
    parts.append(tuple(stat_token(p) for p in _get_overlay_paths()))

    project_root = discover_project_root() if _include_local_config else None
    if project_root is None:
        parts.append(None)
    else:
        project_config = resolve_project_layout(project_root).config
        parts.append(tuple(stat_token(path) for path in project_config.candidates))

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

    Includes the include-local flag, cwd (when local config is enabled), and a
    stat tuple per candidate file layer.  Bundled and plugin defaults aren't
    keyed because they ship in packages and don't change at runtime.

    The first call after process start or explicit invalidation computes the
    token synchronously.  After that, an expired token is returned stale while
    a single daemon worker revalidates it off-thread.
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

        if time.monotonic() >= _current_config_token_cache_deadline:
            if _current_config_token_refresh_thread is None:
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
    with _current_config_token_cache_lock:
        _config_cache_generation += 1
        _default_config_cache = None
        _plugin_configs_cache = None
        _merged_config_cache_token = None
        _merged_config_cache_value = None
        _reset_current_config_token_cache()


def get_use_chezmoi() -> bool:
    """Return whether chezmoi path remapping is enabled."""
    data = load_merged_config()
    return bool(data.get("use_chezmoi", False))


def get_max_running_agents() -> int:
    """Return the configured global limit for running user agents.

    ``load_merged_config()`` provides the process cache and invalidates it when
    a config source changes, so callers can poll this accessor without parsing
    unchanged YAML on every call while still observing live config edits.
    """
    value = load_merged_config().get("max_running_agents", 10)
    if type(value) is int and value >= 1:
        return value
    return 10


def _deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
    *,
    list_strategy: Literal["concatenate", "replace"] = "concatenate",
) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict.

    Merge semantics:
    - **Dicts** are merged recursively (overlay keys override base keys).
    - **Lists** behaviour depends on *list_strategy*:
      - ``"concatenate"`` (default): overlay list is appended to base list.
      - ``"replace"``: overlay list replaces base list entirely.
    - **Scalars** in *override* replace those in *base*.

    Neither *base* nor *override* is mutated.
    """
    result: dict[str, Any] = dict(base)
    for key, override_val in override.items():
        if key in result:
            base_val = result[key]
            if isinstance(base_val, dict) and isinstance(override_val, dict):
                result[key] = _deep_merge(
                    base_val, override_val, list_strategy=list_strategy
                )
            elif isinstance(base_val, list) and isinstance(override_val, list):
                if list_strategy == "replace":
                    log.debug(
                        "Merging key %r: list replace (base=%d items → override=%d items)",
                        key,
                        len(base_val),
                        len(override_val),
                    )
                    result[key] = override_val
                else:
                    log.debug(
                        "Merging key %r: list concatenate (base=%d items, override=%d items → %d items)",
                        key,
                        len(base_val),
                        len(override_val),
                        len(base_val) + len(override_val),
                    )
                    result[key] = base_val + override_val
            else:
                result[key] = override_val
        else:
            result[key] = override_val
    return result


def _load_default_config() -> dict[str, Any]:
    """Load the bundled ``default_config.yml`` from the sase package.

    Returns the parsed YAML as a dict, or an empty dict on any error.
    """
    try:
        ref = importlib.resources.files("sase").joinpath("default_config.yml")
        text = ref.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        if isinstance(data, dict):
            return data
    except Exception:
        log.debug("Failed to load default_config.yml", exc_info=True)
    return {}


def _load_yaml_file(path: Path) -> dict[str, Any] | None:
    """Load a single YAML file, returning ``None`` on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if isinstance(data, dict):
            return data
    except Exception:
        log.debug("Failed to load YAML file: %s", path, exc_info=True)
    return None


def _get_overlay_paths() -> list[Path]:
    """Return sorted overlay paths matching ``sase_*.yml``."""
    if not CONFIG_DIR.is_dir():
        return []
    return sorted(CONFIG_DIR.glob("sase_*.yml"))


def get_local_config_path() -> Path | None:
    """Return the selected project-local config path, if one exists.

    Returns ``None`` when ``_include_local_config`` is ``False`` (e.g. during
    ``sase ace`` runs where the TUI shouldn't inherit repo-level config).
    Canonical ``sase/sase.yml`` is preferred, root-level ``sase.yml`` remains
    readable for compatibility, and coexistence raises a collision diagnostic.
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


def _load_plugin_configs() -> list[dict[str, Any]]:
    """Load ``default_config.yml`` from each plugin in the ``sase_config`` group.

    Returns config dicts sorted by entry-point name for determinism.
    """
    from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

    if is_plugin_disabled("CONFIG"):
        return []

    configs: list[dict[str, Any]] = []
    for module in discover_plugin_resources("sase_config"):
        try:
            ref = importlib.resources.files(module).joinpath("default_config.yml")
            text = ref.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
            if isinstance(data, dict):
                configs.append(data)
        except Exception:
            log.debug(
                "Failed to load plugin config from %s",
                getattr(module, "__name__", module),
                exc_info=True,
            )
    return configs


def load_xprompts_by_source() -> list[tuple[str, dict[str, Any]]]:
    """Load xprompt entries from each config source with provenance tracking.

    Instead of merging all configs and extracting xprompts (which loses source
    information), this returns xprompt dicts from each source separately so the
    xprompt loader can assign proper source attribution.

    Returns:
        List of ``(source_label, xprompts_dict)`` tuples in priority order
        (lowest priority first).  Source labels:

        - ``"default_config"`` — built-in package defaults
        - ``"plugin_config:{module_name}"`` — plugin default configs
        - ``"config"`` — user ``sase.yml``
        - ``"config_overlay:{filename}"`` — ``sase_*.yml`` overlays
    """
    return _load_xprompts_by_source(
        config_dir=CONFIG_DIR,
        default_loader=_load_default_config,
        yaml_loader=_load_yaml_file,
        overlay_paths=_get_overlay_paths(),
        local_path=get_local_config_path(),
        resource_files=importlib.resources.files,
    )


def load_merged_config() -> dict[str, Any]:
    """Load and merge all sase config files.

    Merge chain (each layer merges on top of the previous):
    1. ``default_config.yml`` (bundled package defaults)
    2. Plugin ``default_config.yml`` files (sorted by EP name, lists concatenate)
    3. ``sase.yml`` (user config — lists **replace** defaults)
    4. ``sase_*.yml`` overlays (sorted alphabetically — lists **concatenate**)
    5. project ``sase/sase.yml`` (legacy ``sase.yml`` is read-compatible;
       lists **concatenate**, highest priority)

    Returns at least the defaults even when no user config files exist.

    The result is memoized; cache invalidates automatically when any candidate
    file's mtime/size changes, when ``set_include_local_config`` toggles, or when
    cwd changes (and local config is enabled).  Callers must not mutate the
    returned dict — every call site today reads via ``.get()`` or key access.
    Use :func:`clear_config_cache` to force a reload.
    """
    global _default_config_cache, _plugin_configs_cache
    global _merged_config_cache_token, _merged_config_cache_value

    token = current_config_token()
    if _merged_config_cache_value is not None and _merged_config_cache_token == token:
        return _merged_config_cache_value

    if _default_config_cache is None:
        _default_config_cache = _load_default_config()
    result = dict(_default_config_cache)
    log.debug("Loading layer 'default' (keys: %s)", ", ".join(result.keys()))

    # 2. Plugin configs (between defaults and user config)
    if _plugin_configs_cache is None:
        _plugin_configs_cache = _load_plugin_configs()
    for plugin_config in _plugin_configs_cache:
        log.debug("Loading layer 'plugin' (keys: %s)", ", ".join(plugin_config.keys()))
        result = _deep_merge(result, plugin_config)

    base_path = CONFIG_DIR / "sase.yml"
    user_base = _load_yaml_file(base_path)
    if user_base:
        log.debug(
            "Loading layer 'user' from %s (keys: %s) [list_strategy=replace]",
            base_path,
            ", ".join(user_base.keys()),
        )
        result = _deep_merge(result, user_base, list_strategy="replace")

    for overlay_path in _get_overlay_paths():
        overlay = _load_yaml_file(overlay_path)
        if overlay:
            log.debug(
                "Loading layer 'overlay:%s' from %s (keys: %s)",
                overlay_path.name,
                overlay_path,
                ", ".join(overlay.keys()),
            )
            result = _deep_merge(result, overlay)

    # 5. Local config (highest priority, lists concatenate so that
    #    project-specific entries *add to* rather than replace plugin/user lists
    #    — e.g. a repo's mentor_profiles should extend, not wipe, plugin profiles)
    local_path = get_local_config_path()
    if local_path:
        local_config = _load_yaml_file(local_path)
        if local_config:
            log.debug(
                "Loading layer 'local' from %s (keys: %s) [list_strategy=concatenate]",
                local_path,
                ", ".join(local_config.keys()),
            )
            result = _deep_merge(result, local_config)

    result = without_retired_sdd_selectors(result)
    _merged_config_cache_token = token
    _merged_config_cache_value = result
    return result


def load_config_layers() -> list[ConfigLayer]:
    """Load all config layers with metadata, without merging.

    Returns a list of ConfigLayer descriptors in merge order (lowest to highest
    priority).  Each entry records the source path, whether the file existed,
    which top-level keys it contributed, and the raw data.
    """
    local_path = get_local_config_path()
    local_fallback_path = (
        local_path or _get_local_config_write_path() or Path.cwd() / "sase" / "sase.yml"
    )
    return _load_config_layers(
        config_dir=CONFIG_DIR,
        default_loader=_load_default_config,
        overlay_paths=_get_overlay_paths(),
        local_path=local_path,
        local_fallback_path=local_fallback_path,
        resource_files=importlib.resources.files,
    )
