"""Low-level config source loading and merge mechanics.

Runtime cache ownership and the stable public facade remain in
``sase.config.core``.  This module contains the file/resource IO and the
deterministic merge operation used by that facade.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

from sase.config.identity import AgentOwnerConfigSnapshot
from sase.config.layers import without_retired_sdd_selectors


log = logging.getLogger(__name__)


def deep_merge(
    base: dict[str, Any],
    override: dict[str, Any],
    *,
    list_strategy: Literal["concatenate", "replace"] = "concatenate",
) -> dict[str, Any]:
    """Recursively merge *override* into *base* without mutating either.

    Nested mappings merge recursively.  Lists concatenate by default or replace
    when ``list_strategy="replace"``; override scalars replace base values.
    """
    result: dict[str, Any] = dict(base)
    for key, override_val in override.items():
        if key not in result:
            result[key] = override_val
            continue

        base_val = result[key]
        if isinstance(base_val, dict) and isinstance(override_val, dict):
            result[key] = deep_merge(
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
                    "Merging key %r: list concatenate "
                    "(base=%d items, override=%d items → %d items)",
                    key,
                    len(base_val),
                    len(override_val),
                    len(base_val) + len(override_val),
                )
                result[key] = base_val + override_val
        else:
            result[key] = override_val
    return result


def load_default_config(
    resource_files: Callable[[Any], Any],
) -> dict[str, Any]:
    """Load the bundled ``default_config.yml``, returning empty on error."""
    try:
        ref = resource_files("sase").joinpath("default_config.yml")
        data = yaml.safe_load(ref.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        log.debug("Failed to load default_config.yml", exc_info=True)
    return {}


def load_yaml_file(path: Path) -> dict[str, Any] | None:
    """Load a YAML mapping, returning ``None`` on missing or invalid input."""
    try:
        with open(path, encoding="utf-8") as file:
            data = yaml.safe_load(file)
        if isinstance(data, dict):
            return data
    except Exception:
        log.debug("Failed to load YAML file: %s", path, exc_info=True)
    return None


def get_overlay_paths(config_dir: Path) -> list[Path]:
    """Return sorted overlay paths matching ``sase_*.yml``."""
    if not config_dir.is_dir():
        return []
    return sorted(config_dir.glob("sase_*.yml"))


def load_plugin_configs(
    resource_files: Callable[[Any], Any],
) -> list[dict[str, Any]]:
    """Load default config mappings from enabled config plugins."""
    from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

    if is_plugin_disabled("CONFIG"):
        return []

    configs: list[dict[str, Any]] = []
    for module in discover_plugin_resources("sase_config"):
        try:
            ref = resource_files(module).joinpath("default_config.yml")
            data = yaml.safe_load(ref.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                configs.append(data)
        except Exception:
            log.debug(
                "Failed to load plugin config from %s",
                getattr(module, "__name__", module),
                exc_info=True,
            )
    return configs


def _without_owner_identity(
    data: dict[str, Any],
    *,
    source: str,
) -> dict[str, Any]:
    """Remove identity keys from a non-authoritative merge contribution."""
    if "id" not in data and "machine_name" not in data:
        return data
    ignored = [key for key in ("id", "machine_name") if key in data]
    log.warning(
        "Ignoring owner identity key(s) %s from non-authoritative config source %s; "
        "run `sase config init` to manage identity in the selected machine overlay",
        ", ".join(ignored),
        source,
    )
    cleaned = dict(data)
    cleaned.pop("id", None)
    cleaned.pop("machine_name", None)
    return cleaned


def merge_config_sources(
    *,
    default_config: dict[str, Any],
    plugin_configs: Iterable[dict[str, Any]],
    user_base_path: Path,
    overlay_paths: Iterable[Path],
    selected_identity_snapshot: AgentOwnerConfigSnapshot,
    local_path: Path | None,
    yaml_loader: Callable[[Path], dict[str, Any] | None],
) -> dict[str, Any]:
    """Load and merge the already-discovered config source chain."""
    result = dict(_without_owner_identity(default_config, source="default"))
    log.debug("Loading layer 'default' (keys: %s)", ", ".join(result.keys()))

    for index, plugin_config in enumerate(plugin_configs, start=1):
        log.debug("Loading layer 'plugin' (keys: %s)", ", ".join(plugin_config))
        result = deep_merge(
            result,
            _without_owner_identity(plugin_config, source=f"plugin #{index}"),
        )

    user_base = yaml_loader(user_base_path)
    if user_base:
        log.debug(
            "Loading layer 'user' from %s (keys: %s) [list_strategy=replace]",
            user_base_path,
            ", ".join(user_base),
        )
        result = deep_merge(
            result,
            _without_owner_identity(user_base, source=str(user_base_path)),
            list_strategy="replace",
        )

    selected_identity: dict[str, Any] | None = None
    for overlay_path in overlay_paths:
        overlay = yaml_loader(overlay_path)
        if not overlay:
            continue
        log.debug(
            "Loading layer 'overlay:%s' from %s (keys: %s)",
            overlay_path.name,
            overlay_path,
            ", ".join(overlay),
        )
        if overlay_path == selected_identity_snapshot.selected_overlay:
            id_value = overlay.get("id")
            if isinstance(id_value, dict):
                selected_identity = dict(id_value)
            contribution = dict(overlay)
            contribution.pop("id", None)
            contribution.pop("machine_name", None)
        else:
            contribution = _without_owner_identity(overlay, source=str(overlay_path))
        result = deep_merge(result, contribution)

    if local_path:
        local_config = yaml_loader(local_path)
        if local_config:
            log.debug(
                "Loading layer 'local' from %s (keys: %s) [list_strategy=concatenate]",
                local_path,
                ", ".join(local_config),
            )
            result = deep_merge(
                result,
                _without_owner_identity(local_config, source=str(local_path)),
            )

    result = without_retired_sdd_selectors(result)
    if selected_identity is not None:
        # Restore the raw selected identity after all ordinary merge layers.
        result["id"] = selected_identity
    return result


__all__ = [
    "deep_merge",
    "get_overlay_paths",
    "load_default_config",
    "load_plugin_configs",
    "load_yaml_file",
    "merge_config_sources",
]
