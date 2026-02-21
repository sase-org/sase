"""Centralized configuration loading with multi-file merge support.

Loads ``default_config.yml`` (bundled in the package) as the base layer,
then deep-merges ``~/.config/sase/sase.yml`` (with list replacement), then
deep-merges any overlay files matching ``~/.config/sase/sase_*.yml`` (sorted
alphabetically, with list concatenation) on top.
"""

import importlib.resources
import logging
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]

log = logging.getLogger(__name__)

CONFIG_DIR = Path("~/.config/sase").expanduser()


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
                    result[key] = override_val
                else:
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


def load_merged_config() -> dict[str, Any]:
    """Load and merge all sase config files.

    Merge chain (each layer merges on top of the previous):
    1. ``default_config.yml`` (bundled package defaults)
    2. ``sase.yml`` (user config — lists **replace** defaults)
    3. ``sase_*.yml`` overlays (sorted alphabetically — lists **concatenate**)

    Returns at least the defaults even when no user config files exist.
    """
    result = _load_default_config()

    base_path = CONFIG_DIR / "sase.yml"
    user_base = _load_yaml_file(base_path)
    if user_base:
        result = _deep_merge(result, user_base, list_strategy="replace")

    for overlay_path in _get_overlay_paths():
        overlay = _load_yaml_file(overlay_path)
        if overlay:
            result = _deep_merge(result, overlay)

    return result
