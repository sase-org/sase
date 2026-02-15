"""Centralized configuration loading with multi-file merge support.

Loads ``~/.config/sase/sase.yml`` as the base config, then deep-merges
any overlay files matching ``~/.config/sase/sase_*.yml`` (sorted
alphabetically) on top.
"""

import logging
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

log = logging.getLogger(__name__)

CONFIG_DIR = Path("~/.config/sase").expanduser()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict.

    Merge semantics:
    - **Dicts** are merged recursively (overlay keys override base keys).
    - **Lists** are concatenated (overlay appended to base).
    - **Scalars** in *override* replace those in *base*.

    Neither *base* nor *override* is mutated.
    """
    result: dict[str, Any] = dict(base)
    for key, override_val in override.items():
        if key in result:
            base_val = result[key]
            if isinstance(base_val, dict) and isinstance(override_val, dict):
                result[key] = _deep_merge(base_val, override_val)
            elif isinstance(base_val, list) and isinstance(override_val, list):
                result[key] = base_val + override_val
            else:
                result[key] = override_val
        else:
            result[key] = override_val
    return result


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


def load_merged_config() -> dict[str, Any]:
    """Load and merge all sase config files.

    Loads ``sase.yml`` as the base, then deep-merges each
    ``sase_*.yml`` overlay (sorted alphabetically) on top.

    Returns an empty dict if no config files exist.
    """
    base_path = CONFIG_DIR / "sase.yml"
    result = _load_yaml_file(base_path) or {}

    for overlay_path in _get_overlay_paths():
        overlay = _load_yaml_file(overlay_path)
        if overlay:
            result = _deep_merge(result, overlay)

    return result
