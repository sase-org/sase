"""Entry-point-based plugin discovery for sase.

Provides shared utilities for discovering plugin-contributed resources
(macros, config defaults, VCS providers) via setuptools entry points.
"""

import importlib.metadata
import importlib.resources
import logging
import os
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType

from sase.legacy_xprompt_syntax import (
    CANONICAL_PLUGIN_GROUP,
    RETIRED_PLUGIN_GROUP,
    legacy_xprompt_syntax_enabled,
)

log = logging.getLogger(__name__)

#: Canonical per-group disable variable for macro plugins.
MACRO_PLUGIN_DISABLE_ENV = "SASE_DISABLE_PLUGIN_MACROS"
#: Retired per-group disable variable, accepted only while the sunset flag is on.
LEGACY_MACRO_PLUGIN_DISABLE_ENV = "SASE_DISABLE_PLUGIN_XPROMPTS"
#: Canonical packaged macro resource directory probed first on every plugin.
CANONICAL_PLUGIN_MACROS_DIR = "macros"
#: Retired packaged macro resource directory probed only while the flag is on.
LEGACY_PLUGIN_MACROS_DIR = "xprompts"


def is_plugin_disabled(group_suffix: str) -> bool:
    """Check whether plugins for *group_suffix* are disabled via env vars.

    Returns ``True`` if ``SASE_DISABLE_PLUGINS`` is set (disables all plugin
    groups) or if ``SASE_DISABLE_PLUGIN_{GROUP_SUFFIX}`` is set (disables a
    specific group, e.g. ``SASE_DISABLE_PLUGIN_MACROS``).
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
        group: Entry point group name (e.g. ``"sase_macros"``,
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


def macro_plugins_disabled(
    *,
    environ: Mapping[str, str] | None = None,
    accept_legacy: bool | None = None,
) -> bool:
    """Return whether macro plugins are disabled by public env controls.

    ``SASE_DISABLE_PLUGINS`` still disables every group. Otherwise the
    canonical ``SASE_DISABLE_PLUGIN_MACROS`` decides; the retired
    ``SASE_DISABLE_PLUGIN_XPROMPTS`` is honored only while the
    ``legacy_xprompt_syntax`` flag allows it. Supplying both public names is
    an actionable error (presence decides, so empty values still collide),
    and a retired-only setting with the flag off names its replacement.
    """
    env = os.environ if environ is None else environ
    if env.get("SASE_DISABLE_PLUGINS"):
        return True
    new_present = MACRO_PLUGIN_DISABLE_ENV in env
    old_present = LEGACY_MACRO_PLUGIN_DISABLE_ENV in env
    if new_present and old_present:
        raise ValueError(
            f"{LEGACY_MACRO_PLUGIN_DISABLE_ENV} is retired; "
            f"use {MACRO_PLUGIN_DISABLE_ENV}"
        )
    if old_present:
        if accept_legacy is None:
            accept_legacy = legacy_xprompt_syntax_enabled()
        if not accept_legacy:
            raise ValueError(
                f"{LEGACY_MACRO_PLUGIN_DISABLE_ENV} is retired; "
                f"use {MACRO_PLUGIN_DISABLE_ENV}"
            )
        return bool(env.get(LEGACY_MACRO_PLUGIN_DISABLE_ENV))
    return bool(env.get(MACRO_PLUGIN_DISABLE_ENV))


def _discover_macro_plugin_entry_points(
    *,
    accept_legacy: bool | None = None,
) -> list[importlib.metadata.EntryPoint]:
    """Return deduplicated macro plugin entry points, canonical group first.

    The canonical ``sase_macros`` group always loads; the retired
    ``sase_xprompts`` group loads only while the ``legacy_xprompt_syntax``
    flag allows it. Deduplication keys on the entry-point value
    (distribution resource identity), so a dual registration loads once with
    the canonical spelling winning.
    """
    if accept_legacy is None:
        accept_legacy = legacy_xprompt_syntax_enabled()
    groups = [CANONICAL_PLUGIN_GROUP]
    if accept_legacy:
        groups.append(RETIRED_PLUGIN_GROUP)
    entry_points: list[importlib.metadata.EntryPoint] = []
    seen: set[str] = set()
    for group in groups:
        for ep in sorted(
            importlib.metadata.entry_points(group=group),
            key=lambda item: item.name,
        ):
            if ep.value in seen:
                continue
            seen.add(ep.value)
            entry_points.append(ep)
    return entry_points


def discover_macro_plugin_modules(
    *,
    accept_legacy: bool | None = None,
) -> list[ModuleType]:
    """Load deduplicated macro plugin modules, canonical registration first.

    Modules that fail to load are silently skipped and logged at debug level.
    """
    modules: list[ModuleType] = []
    for ep in _discover_macro_plugin_entry_points(accept_legacy=accept_legacy):
        try:
            modules.append(ep.load())
        except Exception:
            log.debug(
                "Failed to load entry point %s:%s",
                ep.group,
                ep.name,
                exc_info=True,
            )
    return modules


def macro_plugin_definition_dirname(
    module: ModuleType | str,
    *,
    accept_legacy: bool | None = None,
) -> str | None:
    """Return the packaged macro resource directory name for *module*.

    Probes ``macros/`` first on every accepted plugin module, then the retired
    ``xprompts/`` directory only while the ``legacy_xprompt_syntax`` flag
    allows it. Returns ``None`` when the module ships neither, so a
    newly dual-registered plugin that still ships only ``xprompts/`` keeps
    working while enabled and is skipped (never moved, never floor-raised)
    while disabled.
    """
    if accept_legacy is None:
        accept_legacy = legacy_xprompt_syntax_enabled()
    for candidate in (
        (CANONICAL_PLUGIN_MACROS_DIR, LEGACY_PLUGIN_MACROS_DIR)
        if accept_legacy
        else (CANONICAL_PLUGIN_MACROS_DIR,)
    ):
        try:
            ref = importlib.resources.files(module).joinpath(candidate)
        except (TypeError, AttributeError):
            return None
        try:
            is_dir = ref.is_dir()  # type: ignore[union-attr]
        except (OSError, TypeError):
            continue
        if is_dir:
            return candidate
    return None
