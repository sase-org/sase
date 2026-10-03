"""Load config-defined xprompts while preserving source provenance."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase._yaml_safe import yaml_safe_load_cached_text


log = logging.getLogger(__name__)


def load_xprompts_by_source(
    *,
    config_dir: Path,
    default_loader: Callable[[], dict[str, Any]],
    yaml_loader: Callable[[Path], dict[str, Any] | None],
    overlay_paths: list[Path],
    local_path: Path | None,
    resource_files: Callable[[Any], Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Load xprompt entries from each config source in priority order."""
    from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

    results: list[tuple[str, dict[str, Any]]] = []

    default = default_loader()
    if isinstance(default.get("xprompts"), dict):
        results.append(("default_config", default["xprompts"]))

    if not is_plugin_disabled("CONFIG"):
        for module in discover_plugin_resources("sase_config"):
            try:
                ref = resource_files(module).joinpath("default_config.yml")
                data = yaml_safe_load_cached_text(ref.read_text(encoding="utf-8"))
                if isinstance(data, dict) and isinstance(data.get("xprompts"), dict):
                    module_name = getattr(module, "__name__", str(module))
                    results.append((f"plugin_config:{module_name}", data["xprompts"]))
            except Exception:
                log.debug(
                    "Failed to load plugin xprompts from %s",
                    getattr(module, "__name__", module),
                    exc_info=True,
                )

    user_base = yaml_loader(config_dir / "sase.yml")
    if user_base and isinstance(user_base.get("xprompts"), dict):
        results.append(("config", user_base["xprompts"]))

    for overlay_path in overlay_paths:
        overlay = yaml_loader(overlay_path)
        if overlay and isinstance(overlay.get("xprompts"), dict):
            results.append((f"config_overlay:{overlay_path.name}", overlay["xprompts"]))

    if local_path:
        local_config = yaml_loader(local_path)
        if local_config and isinstance(local_config.get("xprompts"), dict):
            results.append(("local_config", local_config["xprompts"]))

    return results
