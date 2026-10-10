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
)

log = logging.getLogger(__name__)

#: Canonical per-group disable variable for macro plugins.
MACRO_PLUGIN_DISABLE_ENV = "SASE_DISABLE_PLUGIN_MACROS"
#: Retired per-group disable variable, always accepted as an alias.
LEGACY_MACRO_PLUGIN_DISABLE_ENV = "SASE_DISABLE_PLUGIN_XPROMPTS"
#: Canonical packaged macro resource directory probed first on every plugin.
CANONICAL_PLUGIN_MACROS_DIR = "macros"
#: Retired packaged macro resource directory, always probed as a fallback.
LEGACY_PLUGIN_MACROS_DIR = "xprompts"
#: Plugin-shared enum manifest probed at each macro-plugin package root.
PLUGIN_INPUT_TYPES_FILENAME = "input_types.yml"


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
    canonical ``SASE_DISABLE_PLUGIN_MACROS`` decides; the retired disable
    variable is always honored as an alias. Supplying both public names is
    an actionable error (presence decides, so empty values still collide).
    """
    # Retired switch kept for compatibility and ignored.
    _ = accept_legacy
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
        return bool(env.get(LEGACY_MACRO_PLUGIN_DISABLE_ENV))
    return bool(env.get(MACRO_PLUGIN_DISABLE_ENV))


def _discover_macro_plugin_entry_points(
    *,
    accept_legacy: bool | None = None,
) -> list[importlib.metadata.EntryPoint]:
    """Return deduplicated macro plugin entry points, canonical group first.

    The canonical ``sase_macros`` group always loads; the retired plugin
    group is always accepted as an alias. Deduplication keys on the
    entry-point value (distribution resource identity), so a dual
    registration loads once with the canonical spelling winning.
    """
    # Retired switch kept for compatibility and ignored.
    _ = accept_legacy
    groups = [CANONICAL_PLUGIN_GROUP, RETIRED_PLUGIN_GROUP]
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


def discover_macro_plugin_input_type_files(
    *,
    accept_legacy: bool | None = None,
) -> list[dict[str, str]]:
    """Return concrete ``input_types.yml`` manifests with distributions.

    Reuses the canonical-first, deduplicated ``sase_macros`` entry-point
    enumeration (plus legacy ``sase_xprompts`` while enabled). Retains
    ``ep.dist`` instead of guessing the distribution from the module name.
    Locates the manifest at the package root with ``importlib.resources``.
    Respects global/macro-plugin disable controls and logs failed imports
    without crashing. Follows concrete-path conventions: only existing files
    are returned.

    Returns:
        List of ``{"distribution", "module", "path"}`` dicts, sorted for
        determinism.
    """
    if macro_plugins_disabled(accept_legacy=accept_legacy):
        return []
    records: list[dict[str, str]] = []
    for ep in _discover_macro_plugin_entry_points(accept_legacy=accept_legacy):
        try:
            module = ep.load()
        except Exception:
            log.debug(
                "Failed to load entry point %s:%s",
                ep.group,
                ep.name,
                exc_info=True,
            )
            continue
        dist = getattr(ep, "dist", None)
        distribution = (
            getattr(dist, "metadata", {}).get("Name") if dist is not None else None
        )
        if not distribution:
            # Fall back to the entry-point name's distribution guess only
            # when metadata is unavailable; prefer ep.dist always.
            continue
        try:
            ref = importlib.resources.files(module).joinpath(
                PLUGIN_INPUT_TYPES_FILENAME
            )
        except (TypeError, AttributeError):
            continue
        try:
            path = Path(str(ref))
        except (OSError, TypeError):
            continue
        if not path.is_file():
            continue
        records.append(
            {
                "distribution": str(distribution),
                "module": getattr(module, "__name__", str(module)),
                "path": str(path),
            }
        )
    records.sort(
        key=lambda item: (
            item["distribution"].lower(),
            item["path"],
            item["module"],
        )
    )
    return records


def discover_macro_plugin_distributions(
    *,
    accept_legacy: bool | None = None,
) -> list[str]:
    """Return known macro-plugin distribution names, even without manifests.

    Uses the same enumeration as
    :func:`discover_macro_plugin_input_type_files` but keeps inventory
    independently of whether a manifest exists.
    """
    if macro_plugins_disabled(accept_legacy=accept_legacy):
        return []
    names: set[str] = set()
    for ep in _discover_macro_plugin_entry_points(accept_legacy=accept_legacy):
        dist = getattr(ep, "dist", None)
        metadata = getattr(dist, "metadata", None) if dist is not None else None
        name = None
        if metadata is not None:
            try:
                name = metadata.get("Name")
            except Exception:
                name = None
        if name:
            names.add(str(name))
    return sorted(names, key=str.lower)


def macro_plugin_definition_dirname(
    module: ModuleType | str,
    *,
    accept_legacy: bool | None = None,
) -> str | None:
    """Return the packaged macro resource directory name for *module*.

    Probes ``macros/`` first on every accepted plugin module, then the
    retired directory, which is always accepted as an alias. Returns
    ``None`` when the module ships neither.
    """
    # Retired switch kept for compatibility and ignored.
    _ = accept_legacy
    for candidate in (
        CANONICAL_PLUGIN_MACROS_DIR,
        LEGACY_PLUGIN_MACROS_DIR,
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
