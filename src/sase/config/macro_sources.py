"""Load config-defined macros while preserving source provenance."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sase._yaml_safe import yaml_safe_load_cached_text


log = logging.getLogger(__name__)


def _normalized_macros(
    data: dict[str, Any] | None,
    *,
    source: str,
    accept_legacy: bool,
) -> dict[str, Any] | None:
    """Normalize one raw config mapping and return its canonical macros."""
    if not isinstance(data, dict):
        return None
    from sase.legacy_xprompt_syntax import normalize_config_layer

    canonical, _ = normalize_config_layer(
        data, source=source, accept_legacy=accept_legacy
    )
    macros = canonical.get("macros")
    return macros if isinstance(macros, dict) else None


def load_macros_by_source(
    *,
    config_dir: Path,
    default_loader: Callable[[], dict[str, Any]],
    yaml_loader: Callable[[Path], dict[str, Any] | None],
    overlay_paths: list[Path],
    local_path: Path | None,
    resource_files: Callable[[Any], Any],
) -> list[tuple[str, dict[str, Any]]]:
    """Load macro entries from each config source in priority order."""
    from sase.main.plugin_discovery import discover_plugin_resources, is_plugin_disabled

    # Retired spellings are always accepted.
    accept_legacy = True
    results: list[tuple[str, dict[str, Any]]] = []

    default = default_loader()
    macros = _normalized_macros(
        default, source="default_config", accept_legacy=accept_legacy
    )
    if macros is not None:
        results.append(("default_config", macros))

    if not is_plugin_disabled("CONFIG"):
        for module in discover_plugin_resources("sase_config"):
            try:
                ref = resource_files(module).joinpath("default_config.yml")
                data = yaml_safe_load_cached_text(ref.read_text(encoding="utf-8"))
            except Exception:
                log.debug(
                    "Failed to load plugin macros from %s",
                    getattr(module, "__name__", module),
                    exc_info=True,
                )
                continue
            if not isinstance(data, dict):
                continue
            # Policy errors propagate; IO errors above stay debug-level.
            module_name = getattr(module, "__name__", str(module))
            macros = _normalized_macros(
                data,
                source=f"plugin_config:{module_name}",
                accept_legacy=accept_legacy,
            )
            if macros is not None:
                results.append((f"plugin_config:{module_name}", macros))

    user_base = yaml_loader(config_dir / "sase.yml")
    macros = _normalized_macros(user_base, source="config", accept_legacy=accept_legacy)
    if macros is not None:
        results.append(("config", macros))

    for overlay_path in overlay_paths:
        overlay = yaml_loader(overlay_path)
        macros = _normalized_macros(
            overlay,
            source=f"config_overlay:{overlay_path.name}",
            accept_legacy=accept_legacy,
        )
        if macros is not None:
            results.append((f"config_overlay:{overlay_path.name}", macros))

    if local_path:
        local_config = yaml_loader(local_path)
        macros = _normalized_macros(
            local_config, source="local_config", accept_legacy=accept_legacy
        )
        if macros is not None:
            results.append(("local_config", macros))

    return results
