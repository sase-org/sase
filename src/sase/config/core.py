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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from sase.content_layout import discover_project_root, resolve_project_layout


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
    results: list[tuple[str, dict[str, Any]]] = []

    # 1. Built-in default config (lowest priority)
    default = _load_default_config()
    if isinstance(default.get("xprompts"), dict):
        results.append(("default_config", default["xprompts"]))

    # 2. Plugin configs
    from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

    if not is_plugin_disabled("CONFIG"):
        for module in discover_plugin_resources("sase_config"):
            try:
                ref = importlib.resources.files(module).joinpath("default_config.yml")
                text = ref.read_text(encoding="utf-8")
                data = yaml.safe_load(text)
                if isinstance(data, dict) and isinstance(data.get("xprompts"), dict):
                    module_name = getattr(module, "__name__", str(module))
                    results.append((f"plugin_config:{module_name}", data["xprompts"]))
            except Exception:
                log.debug(
                    "Failed to load plugin xprompts from %s",
                    getattr(module, "__name__", module),
                    exc_info=True,
                )

    # 3. User config (sase.yml)
    user_base = _load_yaml_file(CONFIG_DIR / "sase.yml")
    if user_base and isinstance(user_base.get("xprompts"), dict):
        results.append(("config", user_base["xprompts"]))

    # 4. Overlay files
    for overlay_path in _get_overlay_paths():
        overlay = _load_yaml_file(overlay_path)
        if overlay and isinstance(overlay.get("xprompts"), dict):
            results.append((f"config_overlay:{overlay_path.name}", overlay["xprompts"]))

    # 5. Local config (highest priority among config sources)
    local_path = get_local_config_path()
    if local_path:
        local_config = _load_yaml_file(local_path)
        if local_config and isinstance(local_config.get("xprompts"), dict):
            results.append(("local_config", local_config["xprompts"]))

    return results


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


# Top-level config keys that were once supported but have since been removed.
# Surfaced via ``sase config layers`` so users see why their entries are ignored.
UNSUPPORTED_TOP_LEVEL_KEYS: frozenset[str] = frozenset({"workflows"})

# Top-level config keys that are still parsed for backward compatibility but have
# a canonical replacement. Mapped to the key callers should migrate to. Surfaced
# (non-fatally) via ``sase config layers`` and ``sase doctor`` so users get a
# nudge to migrate without breaking launched agents with repeated warnings.
DEPRECATED_TOP_LEVEL_KEYS: dict[str, str] = {
    "linked_repos": "repos.linked",
    "sibling_repos": "repos.linked",
}

# Placement is provider-owned. These nested keys are recognized only so old
# configuration can be ignored with an actionable cleanup diagnostic.
RETIRED_SDD_SELECTOR_KEYS: frozenset[str] = frozenset({"storage", "version_controlled"})


def without_retired_sdd_selectors(data: dict[str, Any]) -> dict[str, Any]:
    sdd = data.get("sdd")
    if not isinstance(sdd, dict) or not RETIRED_SDD_SELECTOR_KEYS.intersection(sdd):
        return data
    cleaned = dict(data)
    cleaned_sdd = dict(sdd)
    for key in RETIRED_SDD_SELECTOR_KEYS:
        cleaned_sdd.pop(key, None)
    cleaned["sdd"] = cleaned_sdd
    return cleaned


def _collect_retired_keys(data: dict[str, Any] | None) -> list[str]:
    if not data:
        return []
    sdd = data.get("sdd")
    if not isinstance(sdd, dict):
        return []
    return [f"sdd.{key}" for key in sorted(RETIRED_SDD_SELECTOR_KEYS) if key in sdd]


@dataclass
class ConfigLayer:
    """Describes a single layer in the config merge chain."""

    name: str
    path: str | None
    exists: bool
    list_strategy: str
    keys: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    unsupported_keys: list[str] = field(default_factory=list)
    deprecated_keys: list[str] = field(default_factory=list)
    retired_keys: list[str] = field(default_factory=list)
    present: bool | None = None
    error: str | None = None

    @property
    def loaded(self) -> bool:
        """Return whether this layer contributed config data."""
        return self.exists


def _collect_unsupported_keys(data: dict[str, Any] | None) -> list[str]:
    if not data:
        return []
    return sorted(key for key in data if key in UNSUPPORTED_TOP_LEVEL_KEYS)


def _collect_deprecated_keys(data: dict[str, Any] | None) -> list[str]:
    if not data:
        return []
    return sorted(key for key in data if key in DEPRECATED_TOP_LEVEL_KEYS)


def load_yaml_file_with_metadata(
    path: Path,
) -> tuple[bool, dict[str, Any] | None, str | None]:
    """Load a YAML mapping and keep missing/invalid metadata separate."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        return False, None, None
    except Exception as exc:
        log.debug("Failed to load YAML file: %s", path, exc_info=True)
        return True, None, f"{type(exc).__name__}: {exc}"

    if data is None:
        return True, {}, None
    if isinstance(data, dict):
        return True, data, None
    return (
        True,
        None,
        f"top-level YAML value is {type(data).__name__}, expected mapping",
    )


def load_config_layers() -> list[ConfigLayer]:
    """Load all config layers with metadata, without merging.

    Returns a list of ConfigLayer descriptors in merge order (lowest to highest
    priority).  Each entry records the source path, whether the file existed,
    which top-level keys it contributed, and the raw data.
    """
    from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

    layers: list[ConfigLayer] = []

    # 1. Built-in default
    default_data = _load_default_config()
    layers.append(
        ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            keys=list(default_data.keys()),
            data=default_data,
            unsupported_keys=_collect_unsupported_keys(default_data),
            deprecated_keys=_collect_deprecated_keys(default_data),
            retired_keys=_collect_retired_keys(default_data),
            present=True,
        )
    )

    # 2. Plugin configs
    if not is_plugin_disabled("CONFIG"):
        for module in discover_plugin_resources("sase_config"):
            module_name = getattr(module, "__name__", str(module))
            try:
                ref = importlib.resources.files(module).joinpath("default_config.yml")
                text = ref.read_text(encoding="utf-8")
                data = yaml.safe_load(text)
                if isinstance(data, dict):
                    layers.append(
                        ConfigLayer(
                            name=f"plugin:{module_name}",
                            path=None,
                            exists=True,
                            list_strategy="concatenate",
                            keys=list(data.keys()),
                            data=data,
                            unsupported_keys=_collect_unsupported_keys(data),
                            deprecated_keys=_collect_deprecated_keys(data),
                            retired_keys=_collect_retired_keys(data),
                            present=True,
                        )
                    )
            except Exception:
                layers.append(
                    ConfigLayer(
                        name=f"plugin:{module_name}",
                        path=None,
                        exists=False,
                        list_strategy="concatenate",
                        present=True,
                        error="failed to load plugin default_config.yml",
                    )
                )

    # 3. User config
    base_path = CONFIG_DIR / "sase.yml"
    user_present, user_data, user_error = load_yaml_file_with_metadata(base_path)
    layers.append(
        ConfigLayer(
            name="user",
            path=str(base_path),
            exists=user_data is not None,
            list_strategy="replace",
            keys=list(user_data.keys()) if user_data else [],
            data=user_data or {},
            unsupported_keys=_collect_unsupported_keys(user_data),
            deprecated_keys=_collect_deprecated_keys(user_data),
            retired_keys=_collect_retired_keys(user_data),
            present=user_present,
            error=user_error,
        )
    )

    # 4. Overlay files
    for overlay_path in _get_overlay_paths():
        overlay_present, overlay_data, overlay_error = load_yaml_file_with_metadata(
            overlay_path
        )
        layers.append(
            ConfigLayer(
                name=f"overlay:{overlay_path.name}",
                path=str(overlay_path),
                exists=overlay_data is not None,
                list_strategy="concatenate",
                keys=list(overlay_data.keys()) if overlay_data else [],
                data=overlay_data or {},
                unsupported_keys=_collect_unsupported_keys(overlay_data),
                deprecated_keys=_collect_deprecated_keys(overlay_data),
                retired_keys=_collect_retired_keys(overlay_data),
                present=overlay_present,
                error=overlay_error,
            )
        )

    # 5. Local config
    local_path = get_local_config_path()
    if local_path:
        local_present, local_data, local_error = load_yaml_file_with_metadata(
            local_path
        )
        layers.append(
            ConfigLayer(
                name="local",
                path=str(local_path),
                exists=local_data is not None,
                list_strategy="concatenate",
                keys=list(local_data.keys()) if local_data else [],
                data=local_data or {},
                unsupported_keys=_collect_unsupported_keys(local_data),
                deprecated_keys=_collect_deprecated_keys(local_data),
                retired_keys=_collect_retired_keys(local_data),
                present=local_present,
                error=local_error,
            )
        )
    else:
        layers.append(
            ConfigLayer(
                name="local",
                path=str(
                    _get_local_config_write_path() or Path.cwd() / "sase" / "sase.yml"
                ),
                exists=False,
                list_strategy="concatenate",
                present=False,
            )
        )

    return layers
