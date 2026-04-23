"""Centralized configuration loading with multi-file merge support.

Loads ``default_config.yml`` (bundled in the package) as the base layer,
then deep-merges plugin ``default_config.yml`` files, then
``~/.config/sase/sase.yml`` (with list replacement), then
deep-merges any overlay files matching ``~/.config/sase/sase_*.yml`` (sorted
alphabetically, with list concatenation) on top, then finally any local
``sase.yml`` found in the current working directory (with list concatenation),
unless local config loading has been disabled via ``set_include_local_config(False)``
(e.g. for ``sase ace`` runs where the TUI should not inherit repo-level config).
"""

import importlib.resources
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]


log = logging.getLogger(__name__)

CONFIG_DIR = Path("~/.config/sase").expanduser()
CHEZMOI_HOME = Path("~/.local/share/chezmoi/home").expanduser()

# When False, _get_local_config_path() always returns None.
# Set to False for `sase ace` so the TUI doesn't pick up a repo's sase.yml;
# agent runs are separate processes and keep the default (True).
_include_local_config: bool = True


def set_include_local_config(value: bool) -> None:
    """Enable or disable loading of the local CWD ``sase.yml``."""
    global _include_local_config
    _include_local_config = value


def get_use_chezmoi() -> bool:
    """Return whether chezmoi path remapping is enabled."""
    data = load_merged_config()
    return bool(data.get("use_chezmoi", False))


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


def _get_local_config_path() -> Path | None:
    """Return the path to a local ``sase.yml`` in the CWD, if it exists.

    Returns ``None`` when ``_include_local_config`` is ``False`` (e.g. during
    ``sase ace`` runs where the TUI shouldn't inherit repo-level config).
    """
    if not _include_local_config:
        return None
    try:
        cwd = Path.cwd()
    except FileNotFoundError:
        # The axe daemon can outlive its CWD if a workspace it was launched
        # from is wiped — in that case there cannot be a local override, so
        # degrade gracefully instead of propagating the error to every caller
        # of load_merged_config() (including get_timezone()).
        return None
    local_path = cwd / "sase.yml"
    if local_path.is_file():
        return local_path
    return None


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
    local_path = _get_local_config_path()
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
    5. ``./sase.yml`` (local CWD config — lists **concatenate**, highest priority)

    Returns at least the defaults even when no user config files exist.
    """
    result = _load_default_config()
    log.debug("Loading layer 'default' (keys: %s)", ", ".join(result.keys()))

    # 2. Plugin configs (between defaults and user config)
    for plugin_config in _load_plugin_configs():
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
    local_path = _get_local_config_path()
    if local_path:
        local_config = _load_yaml_file(local_path)
        if local_config:
            log.debug(
                "Loading layer 'local' from %s (keys: %s) [list_strategy=concatenate]",
                local_path,
                ", ".join(local_config.keys()),
            )
            result = _deep_merge(result, local_config)

    return result


@dataclass
class _ConfigLayer:
    """Describes a single layer in the config merge chain."""

    name: str
    path: str | None
    exists: bool
    list_strategy: str
    keys: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)


def load_config_layers() -> list[_ConfigLayer]:
    """Load all config layers with metadata, without merging.

    Returns a list of _ConfigLayer descriptors in merge order (lowest to highest
    priority).  Each entry records the source path, whether the file existed,
    which top-level keys it contributed, and the raw data.
    """
    from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

    layers: list[_ConfigLayer] = []

    # 1. Built-in default
    default_data = _load_default_config()
    layers.append(
        _ConfigLayer(
            name="default",
            path=None,
            exists=True,
            list_strategy="concatenate",
            keys=list(default_data.keys()),
            data=default_data,
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
                        _ConfigLayer(
                            name=f"plugin:{module_name}",
                            path=None,
                            exists=True,
                            list_strategy="concatenate",
                            keys=list(data.keys()),
                            data=data,
                        )
                    )
            except Exception:
                layers.append(
                    _ConfigLayer(
                        name=f"plugin:{module_name}",
                        path=None,
                        exists=False,
                        list_strategy="concatenate",
                    )
                )

    # 3. User config
    base_path = CONFIG_DIR / "sase.yml"
    user_data = _load_yaml_file(base_path)
    layers.append(
        _ConfigLayer(
            name="user",
            path=str(base_path),
            exists=user_data is not None,
            list_strategy="replace",
            keys=list(user_data.keys()) if user_data else [],
            data=user_data or {},
        )
    )

    # 4. Overlay files
    for overlay_path in _get_overlay_paths():
        overlay_data = _load_yaml_file(overlay_path)
        layers.append(
            _ConfigLayer(
                name=f"overlay:{overlay_path.name}",
                path=str(overlay_path),
                exists=overlay_data is not None,
                list_strategy="concatenate",
                keys=list(overlay_data.keys()) if overlay_data else [],
                data=overlay_data or {},
            )
        )

    # 5. Local config
    local_path = _get_local_config_path()
    if local_path:
        local_data = _load_yaml_file(local_path)
        layers.append(
            _ConfigLayer(
                name="local",
                path=str(local_path),
                exists=local_data is not None,
                list_strategy="concatenate",
                keys=list(local_data.keys()) if local_data else [],
                data=local_data or {},
            )
        )
    else:
        layers.append(
            _ConfigLayer(
                name="local",
                path=str(Path.cwd() / "sase.yml"),
                exists=False,
                list_strategy="concatenate",
            )
        )

    return layers
