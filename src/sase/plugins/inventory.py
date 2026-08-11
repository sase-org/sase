"""SASE entry-point inventory metadata for diagnostics.

This is neutral plugin metadata shared by ``sase doctor`` resource checks, the
``sase version`` plugin-package inventory, and the ``sase plugin`` catalog's
installed-merge (see :mod:`sase.plugins.installed`). It describes the locally
installed entry-point providers, distinct from the ``sase plugin`` catalog of
plugins that *exist* in the GitHub registry.
"""

from __future__ import annotations

import importlib.metadata
import os
from dataclasses import dataclass
from typing import Literal

ENTRY_POINT_GROUPS: tuple[str, ...] = (
    "sase_artifact_refs",
    "sase_config",
    "sase_file_hooks",
    "sase_llm",
    "sase_plugin_manifest",
    "sase_vcs",
    "sase_workspace",
    "sase_xprompts",
)
RESOURCE_ENTRY_POINT_GROUPS: frozenset[str] = frozenset(
    {"sase_config", "sase_plugin_manifest", "sase_xprompts"}
)
PROVIDER_ENTRY_POINT_GROUPS: frozenset[str] = frozenset(
    group for group in ENTRY_POINT_GROUPS if group not in RESOURCE_ENTRY_POINT_GROUPS
)

EntryPointLoadStatus = Literal["not_loaded", "ok", "error", "skipped"]


@dataclass(frozen=True)
class _PluginEntryPointRecord:
    """Metadata and optional load status for one SASE entry point."""

    group: str
    name: str
    value: str
    package: str
    version: str
    load_status: EntryPointLoadStatus
    load_error: str | None = None
    disabled_by: tuple[str, ...] = ()

    @property
    def is_resource(self) -> bool:
        return self.group in RESOURCE_ENTRY_POINT_GROUPS

    @property
    def is_third_party(self) -> bool:
        return self.package.lower() != "sase"


@dataclass(frozen=True)
class _PluginDistributionRecord:
    """A package that contributes at least one SASE entry point."""

    package: str
    version: str
    entry_points: tuple[str, ...]


@dataclass(frozen=True)
class PluginInventory:
    """Installed SASE plugin entry point inventory."""

    entry_points: tuple[_PluginEntryPointRecord, ...]
    distributions: tuple[_PluginDistributionRecord, ...]
    disabled_env: tuple[str, ...]

    @property
    def third_party_entry_points(self) -> tuple[_PluginEntryPointRecord, ...]:
        return tuple(ep for ep in self.entry_points if ep.is_third_party)

    @property
    def resource_entry_points(self) -> tuple[_PluginEntryPointRecord, ...]:
        return tuple(ep for ep in self.entry_points if ep.is_resource)


def collect_plugin_inventory(
    *, load_resource_entry_points: bool = True
) -> PluginInventory:
    """Collect SASE entry point metadata from the running Python environment.

    Provider groups are inspected without importing provider classes. Resource
    groups are loaded by default because failures there otherwise only show up
    as debug logs during normal SASE startup.
    """
    records: list[_PluginEntryPointRecord] = []
    disabled_env: set[str] = set()

    for group in ENTRY_POINT_GROUPS:
        disabled_by = _disabled_env_for_group(group)
        disabled_env.update(disabled_by)
        for ep in _entry_points_for_group(group):
            load_status: EntryPointLoadStatus = "not_loaded"
            load_error: str | None = None

            if group in RESOURCE_ENTRY_POINT_GROUPS:
                if disabled_by:
                    load_status = "skipped"
                elif load_resource_entry_points:
                    try:
                        ep.load()
                    except Exception as exc:
                        load_status = "error"
                        load_error = f"{type(exc).__name__}: {exc}"
                    else:
                        load_status = "ok"

            records.append(
                _PluginEntryPointRecord(
                    group=group,
                    name=_safe_str(getattr(ep, "name", None), "<unknown>"),
                    value=_safe_str(getattr(ep, "value", None), ""),
                    package=_entry_point_package(ep),
                    version=_entry_point_version(ep),
                    load_status=load_status,
                    load_error=load_error,
                    disabled_by=disabled_by,
                )
            )

    records.sort(key=lambda ep: (ep.package.lower(), ep.group, ep.name, ep.value))
    records_tuple = tuple(records)
    return PluginInventory(
        entry_points=records_tuple,
        distributions=_distribution_records(records_tuple),
        disabled_env=tuple(sorted(disabled_env)),
    )


def _entry_points_for_group(group: str) -> list[importlib.metadata.EntryPoint]:
    eps = importlib.metadata.entry_points(group=group)
    return sorted(eps, key=lambda ep: ep.name)


def _disabled_env_for_group(group: str) -> tuple[str, ...]:
    disabled: list[str] = []
    if os.environ.get("SASE_DISABLE_PLUGINS"):
        disabled.append("SASE_DISABLE_PLUGINS")

    suffix = group.removeprefix("sase_").upper()
    env_key = f"SASE_DISABLE_PLUGIN_{suffix}"
    if os.environ.get(env_key):
        disabled.append(env_key)
    return tuple(disabled)


def _distribution_records(
    entry_points: tuple[_PluginEntryPointRecord, ...],
) -> tuple[_PluginDistributionRecord, ...]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for ep in entry_points:
        key = (ep.package, ep.version)
        grouped.setdefault(key, []).append(f"{ep.group}:{ep.name}")

    records = [
        _PluginDistributionRecord(
            package=package,
            version=version,
            entry_points=tuple(sorted(names)),
        )
        for (package, version), names in grouped.items()
    ]
    records.sort(key=lambda dist: (dist.package.lower(), dist.version))
    return tuple(records)


def _entry_point_package(ep: importlib.metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    metadata = getattr(dist, "metadata", None)
    name = _metadata_value(metadata, "Name")
    if name:
        return name

    direct_name = getattr(dist, "name", None)
    if isinstance(direct_name, str) and direct_name:
        return direct_name
    return "<unknown>"


def _entry_point_version(ep: importlib.metadata.EntryPoint) -> str:
    dist = getattr(ep, "dist", None)
    version = getattr(dist, "version", None)
    if isinstance(version, str) and version:
        return version

    metadata = getattr(dist, "metadata", None)
    metadata_version = _metadata_value(metadata, "Version")
    return metadata_version or "<unknown>"


def _metadata_value(metadata: object, key: str) -> str | None:
    getter = getattr(metadata, "get", None)
    if not callable(getter):
        return None
    value = getter(key)
    return value if isinstance(value, str) and value else None


def _safe_str(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default
