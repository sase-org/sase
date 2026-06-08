"""Installed SASE plugin discovery helpers for version inventory."""

from __future__ import annotations

import importlib.metadata
from collections.abc import Iterable
from dataclasses import dataclass

from sase.plugins.inventory import ENTRY_POINT_GROUPS as SASE_ENTRY_POINT_GROUPS
from sase.version._models import (
    CONSOLE_SCRIPT_ENTRY_POINT_GROUP,
    CORE_DISTRIBUTION_NAME,
    HOST_DISTRIBUTION_NAME,
    SASE_CHOP_SCRIPT_PREFIX,
)
from sase.version._sources import distribution_name
from sase.version._utils import (
    IMPORT_MODULE_RE,
    normalize_distribution_name,
    safe_str,
)


@dataclass(frozen=True)
class PluginCandidate:
    distribution_name: str
    distribution: importlib.metadata.Distribution
    import_module: str | None
    plugin_signals: tuple[str, ...]


def plugin_candidates_from_distributions(
    distributions: Iterable[importlib.metadata.Distribution],
) -> tuple[PluginCandidate, ...]:
    candidates: list[PluginCandidate] = []

    for dist in distributions:
        dist_name = distribution_name(dist)
        if dist_name is None:
            continue
        if is_runtime_distribution(dist_name):
            continue

        plugin_signals: list[str] = []
        import_modules: list[str] = []

        if is_sase_plugin_distribution_name(dist_name):
            plugin_signals.append(f"distribution_name:{dist_name}")

        for ep in distribution_entry_points(dist):
            group = entry_point_group(ep)
            name = entry_point_name(ep)
            value = entry_point_value(ep)

            if group in SASE_ENTRY_POINT_GROUPS:
                plugin_signals.append(entry_point_signal(group, name, value))
                module = entry_point_import_module(ep)
                if module:
                    import_modules.append(module)
                continue

            if group == CONSOLE_SCRIPT_ENTRY_POINT_GROUP and (
                is_sase_plugin_console_script(name, dist_name)
            ):
                plugin_signals.append(console_script_signal(name, value))
                module = entry_point_import_module(ep)
                if module:
                    import_modules.append(module)

        if not plugin_signals:
            continue

        candidates.append(
            PluginCandidate(
                distribution_name=dist_name,
                distribution=dist,
                import_module=preferred_plugin_import_module(
                    import_modules,
                    dist,
                    dist_name,
                ),
                plugin_signals=tuple(sorted(set(plugin_signals))),
            )
        )

    candidates.sort(key=lambda candidate: candidate.distribution_name.lower())
    return tuple(candidates)


def distribution_entry_points(
    dist: importlib.metadata.Distribution,
) -> tuple[importlib.metadata.EntryPoint, ...]:
    try:
        entry_points = getattr(dist, "entry_points", ())
    except Exception:
        return ()
    if entry_points is None:
        return ()
    try:
        return tuple(entry_points)
    except TypeError:
        return ()


def preferred_plugin_import_module(
    import_modules: list[str],
    dist: importlib.metadata.Distribution,
    distribution_name: str,
) -> str | None:
    for module in import_modules:
        top_level = top_level_import_module(module)
        if top_level:
            return top_level

    top_level_modules = distribution_top_level_modules(dist)
    if top_level_modules:
        return top_level_modules[0]

    return module_from_distribution_name(distribution_name)


def distribution_top_level_modules(
    dist: importlib.metadata.Distribution,
) -> tuple[str, ...]:
    try:
        text = dist.read_text("top_level.txt")
    except Exception:
        return ()
    if not text:
        return ()

    modules: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        module = raw_line.strip()
        if not IMPORT_MODULE_RE.fullmatch(module) or module in seen:
            continue
        seen.add(module)
        modules.append(module)
    return tuple(modules)


def entry_point_group(ep: importlib.metadata.EntryPoint) -> str:
    return safe_str(getattr(ep, "group", None), "")


def entry_point_name(ep: importlib.metadata.EntryPoint) -> str:
    return safe_str(getattr(ep, "name", None), "<unknown>")


def entry_point_value(ep: importlib.metadata.EntryPoint) -> str:
    return safe_str(getattr(ep, "value", None), "")


def entry_point_import_module(ep: importlib.metadata.EntryPoint) -> str | None:
    module = getattr(ep, "module", None)
    if isinstance(module, str) and IMPORT_MODULE_RE.fullmatch(module):
        return module
    return module_from_entry_point_value(entry_point_value(ep))


def module_from_entry_point_value(value: str) -> str | None:
    module = value.split(":", 1)[0].split("[", 1)[0].strip()
    if IMPORT_MODULE_RE.fullmatch(module):
        return module
    return None


def top_level_import_module(module: str) -> str | None:
    top_level = module.split(".", 1)[0].strip()
    if IMPORT_MODULE_RE.fullmatch(top_level):
        return top_level
    return None


def module_from_distribution_name(distribution_name: str) -> str | None:
    module = normalize_distribution_name(distribution_name).replace("-", "_")
    if IMPORT_MODULE_RE.fullmatch(module):
        return module
    return None


def entry_point_signal(group: str, name: str, value: str) -> str:
    signal = f"entry_point:{group}:{name}"
    return f"{signal}={value}" if value else signal


def console_script_signal(name: str, value: str) -> str:
    signal = f"console_script:{name}"
    return f"{signal}={value}" if value else signal


def is_sase_plugin_console_script(name: str, distribution_name: str) -> bool:
    if name.startswith(SASE_CHOP_SCRIPT_PREFIX):
        return True
    if not is_sase_plugin_distribution_name(distribution_name):
        return False
    return name.startswith(("sase_", "sase-"))


def is_runtime_distribution(distribution_name: str) -> bool:
    normalized = normalize_distribution_name(distribution_name)
    return normalized in {
        normalize_distribution_name(HOST_DISTRIBUTION_NAME),
        normalize_distribution_name(CORE_DISTRIBUTION_NAME),
    }


def is_sase_plugin_distribution_name(distribution_name: str) -> bool:
    normalized = normalize_distribution_name(distribution_name)
    return normalized.startswith("sase-") and normalized != normalize_distribution_name(
        CORE_DISTRIBUTION_NAME
    )
