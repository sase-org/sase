"""Aggregate installed/latest update status for SASE core and plugins."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from sase.plugins.catalog import PluginCatalogEntry, load_plugin_catalog
from sase.plugins.latest import enrich_with_latest, is_newer
from sase.plugins.pypi_source import fetch_latest_version
from sase.uv_tool.versions import (
    CorePackageVersion,
    collect_installed_core_versions,
    enrich_core_versions_latest,
)

ComponentRole = Literal["host", "core", "plugin"]


@dataclass(frozen=True)
class OutdatedComponent:
    """One installed SASE component that is behind its latest known version."""

    display_name: str
    role: ComponentRole
    installed_version: str | None
    latest_version: str | None
    distribution_name: str


@dataclass(frozen=True)
class UpdateStatus:
    """Update-status snapshot for SASE core packages and installed plugins."""

    checked_at: float
    components: tuple[OutdatedComponent, ...]

    @property
    def has_updates(self) -> bool:
        """Return whether any component is currently known to be outdated."""
        return bool(self.components)

    @property
    def count(self) -> int:
        """Return the number of known outdated components."""
        return len(self.components)


def compute_update_status(
    *,
    offline: bool = False,
    refresh: bool = False,
    now: float | None = None,
) -> UpdateStatus:
    """Compute best-effort update status for SASE core and installed plugins.

    Each source degrades independently. A PyPI, GitHub, or dev-checkout failure
    can suppress that source's entries, but it never prevents reporting updates
    found from the other source.
    """
    checked_at = time.time() if now is None else now
    components: list[OutdatedComponent] = []
    components.extend(_compute_core_components(offline=offline))
    components.extend(
        _compute_plugin_components(
            offline=offline,
            refresh=refresh,
            now=checked_at,
        )
    )
    return UpdateStatus(
        checked_at=checked_at,
        components=tuple(
            sorted(
                components,
                key=lambda item: (
                    _role_sort_key(item.role),
                    item.display_name.casefold(),
                ),
            )
        ),
    )


def _compute_core_components(*, offline: bool) -> tuple[OutdatedComponent, ...]:
    try:
        versions = _collect_installed_core_versions()
        versions = _enrich_core_versions_latest(
            versions,
            offline=offline,
            fetch_fn=_fetch_latest_version,
            is_newer=_is_newer,
        )
    except Exception:  # noqa: BLE001 - startup update hints are best effort.
        return ()
    return tuple(
        _core_component(package)
        for package in versions.packages
        if package.update_available
    )


def _core_component(package: CorePackageVersion) -> OutdatedComponent:
    name = package.name
    distribution_name = package.distribution_name
    role: ComponentRole = "host" if distribution_name == "sase" else "core"
    return OutdatedComponent(
        display_name=str(name),
        role=role,
        installed_version=package.installed_version,
        latest_version=package.latest_version,
        distribution_name=str(distribution_name),
    )


def _compute_plugin_components(
    *,
    offline: bool,
    refresh: bool,
    now: float,
) -> tuple[OutdatedComponent, ...]:
    try:
        catalog = _load_plugin_catalog(refresh=refresh, offline=offline, now=now)
    except Exception:  # noqa: BLE001 - missing gh/offline catalog degrades only.
        return ()
    try:
        catalog = _enrich_with_latest(catalog, offline=offline, refresh=refresh)
    except Exception:  # noqa: BLE001 - latest markers degrade only.
        pass
    return tuple(
        _plugin_component(entry)
        for entry in catalog.entries
        if entry.installed.installed and entry.update_available
    )


def _plugin_component(entry: PluginCatalogEntry) -> OutdatedComponent:
    latest = entry.latest
    installed = entry.installed
    installed_version = latest.current_version or installed.version
    distribution_name = entry.repo or entry.name
    return OutdatedComponent(
        display_name=str(entry.name),
        role="plugin",
        installed_version=installed_version,
        latest_version=latest.version,
        distribution_name=str(distribution_name),
    )


def _role_sort_key(role: ComponentRole) -> int:
    if role == "host":
        return 0
    if role == "core":
        return 1
    return 2


_collect_installed_core_versions = collect_installed_core_versions
_enrich_core_versions_latest = enrich_core_versions_latest
_load_plugin_catalog = load_plugin_catalog
_enrich_with_latest = enrich_with_latest
_fetch_latest_version = fetch_latest_version
_is_newer = is_newer

__all__ = [
    "ComponentRole",
    "OutdatedComponent",
    "UpdateStatus",
    "compute_update_status",
]
