"""Config-layer metadata and diagnostic loading.

This module describes the unmerged config source stack used by Config Center,
``sase config layers``, and doctor checks. Runtime merging and caching remain in
``sase.config.core``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sase._yaml_safe import yaml_safe_load


log = logging.getLogger(__name__)

# Top-level config keys that were once supported but have since been removed.
# Surfaced via ``sase config layers`` so users see why their entries are ignored.
UNSUPPORTED_TOP_LEVEL_KEYS: frozenset[str] = frozenset({"workflows"})

# Top-level config keys that are still parsed for backward compatibility but have
# a canonical replacement. Mapped to the key callers should migrate to. Surfaced
# (non-fatally) via ``sase config layers`` and ``sase doctor`` so users get a
# nudge to migrate without breaking launched agents with repeated warnings.
DEPRECATED_TOP_LEVEL_KEYS: dict[str, str] = {
    "amd_h1_title": "memory.h1_title",
    "glossary": "memory.glossary",
    "linked_repos": "repos.linked",
    "machine_name": "id.machine_name",
    "sibling_repos": "repos.linked",
}

# Placement is provider-owned. These nested keys are recognized only so old
# configuration can be ignored with an actionable cleanup diagnostic.
RETIRED_SDD_SELECTOR_KEYS: frozenset[str] = frozenset({"storage", "version_controlled"})


def without_retired_sdd_selectors(data: dict[str, Any]) -> dict[str, Any]:
    """Return *data* without retired provider-owned SDD selector keys."""
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
            data = yaml_safe_load(f)
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


def load_config_layers(
    *,
    config_dir: Path,
    default_loader: Callable[[], dict[str, Any]],
    overlay_paths: list[Path],
    local_path: Path | None,
    local_fallback_path: Path,
    resource_files: Callable[[Any], Any],
) -> list[ConfigLayer]:
    """Load all config layers with metadata, without merging.

    Runtime-owned paths and loaders are injected by ``sase.config.core``. This
    keeps its longstanding patch points effective while isolating the layer
    inspection responsibility in this module.
    """
    from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

    layers: list[ConfigLayer] = []

    default_data = default_loader()
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

    if not is_plugin_disabled("CONFIG"):
        for module in discover_plugin_resources("sase_config"):
            module_name = getattr(module, "__name__", str(module))
            try:
                ref = resource_files(module).joinpath("default_config.yml")
                data = yaml_safe_load(ref.read_text(encoding="utf-8"))
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

    base_path = config_dir / "sase.yml"
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

    for overlay_path in overlay_paths:
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
                path=str(local_fallback_path),
                exists=False,
                list_strategy="concatenate",
                present=False,
            )
        )

    return layers
