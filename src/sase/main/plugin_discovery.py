"""Entry-point-based plugin discovery for sase.

Provides shared utilities for discovering plugin-contributed resources
(xprompts, config defaults, VCS providers) via setuptools entry points.
"""

import importlib.metadata
import logging
import os
from types import ModuleType

log = logging.getLogger(__name__)


def is_plugin_disabled(group_suffix: str) -> bool:
    """Check whether plugins for *group_suffix* are disabled via env vars.

    Returns ``True`` if ``SASE_DISABLE_PLUGINS`` is set (disables all plugin
    groups) or if ``SASE_DISABLE_PLUGIN_{GROUP_SUFFIX}`` is set (disables a
    specific group, e.g. ``SASE_DISABLE_PLUGIN_XPROMPTS``).
    """
    if os.environ.get("SASE_DISABLE_PLUGINS"):
        return True
    env_key = f"SASE_DISABLE_PLUGIN_{group_suffix.upper()}"
    return bool(os.environ.get(env_key))


def discover_plugin_resources(group: str) -> list[ModuleType]:
    """Load entry points for *group* and return the imported modules.

    Each entry point is expected to point at a module (not a class or
    function).  Modules that fail to load are silently skipped and logged
    at debug level.

    Args:
        group: Entry point group name (e.g. ``"sase_xprompts"``,
            ``"sase_config"``).

    Returns:
        List of imported module objects, sorted by entry-point name for
        determinism.
    """
    modules: list[ModuleType] = []
    eps = sorted(
        importlib.metadata.entry_points(group=group),
        key=lambda ep: ep.name,
    )
    for ep in eps:
        try:
            module = ep.load()
            modules.append(module)
        except Exception:
            log.debug("Failed to load entry point %s:%s", group, ep.name, exc_info=True)
    return modules
