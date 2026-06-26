"""Installed/latest version helpers for the SASE core packages.

This module is pure and injectable: it knows the SASE package names and how to
collect installed versions, but callers provide the package-index fetcher and
PEP-440 comparison function. That keeps :mod:`sase.uv_tool` independent from
the plugin catalog modules while letting the TUI reuse the same PyPI lookup
logic as ``sase plugin list``.
"""

from __future__ import annotations

import dataclasses
import importlib.metadata as importlib_metadata
from collections.abc import Callable
from dataclasses import dataclass

from sase.version.inventory import CORE_DISTRIBUTION_NAME, HOST_DISTRIBUTION_NAME

VersionFn = Callable[[str], str | None]
FetchLatestFn = Callable[[str], str | None]
IsNewerFn = Callable[[str | None, str | None], bool]

_CORE_PACKAGES: tuple[tuple[str, str], ...] = (
    ("sase", HOST_DISTRIBUTION_NAME),
    ("sase-core", CORE_DISTRIBUTION_NAME),
)


@dataclass(frozen=True)
class CorePackageVersion:
    """Installed/latest state for one SASE core package."""

    name: str
    distribution_name: str
    installed_version: str | None
    latest_version: str | None = None
    latest_checked: bool = False
    update_available: bool = False
    latest_error: str | None = None


@dataclass(frozen=True)
class CoreVersions:
    """Version state for the packages that make up SASE itself."""

    packages: tuple[CorePackageVersion, ...]

    @property
    def update_available(self) -> bool:
        return any(package.update_available for package in self.packages)


def collect_installed_core_versions(
    *, version_fn: VersionFn = importlib_metadata.version
) -> CoreVersions:
    """Collect installed versions for ``sase`` and ``sase-core-rs``.

    Version lookup is best-effort because version display must never break the
    Admin Center. Missing packages are represented with ``installed_version`` as
    ``None``.
    """
    packages = tuple(
        CorePackageVersion(
            name=display_name,
            distribution_name=dist_name,
            installed_version=_safe_version(dist_name, version_fn),
        )
        for display_name, dist_name in _CORE_PACKAGES
    )
    return CoreVersions(packages=packages)


def enrich_core_versions_latest(
    versions: CoreVersions,
    *,
    offline: bool = False,
    fetch_fn: FetchLatestFn,
    is_newer: IsNewerFn,
) -> CoreVersions:
    """Return *versions* with best-effort latest-version metadata attached."""
    if offline:
        return CoreVersions(
            packages=tuple(
                dataclasses.replace(
                    package,
                    latest_checked=True,
                    latest_version=None,
                    update_available=False,
                    latest_error="offline",
                )
                for package in versions.packages
            )
        )

    enriched: list[CorePackageVersion] = []
    for package in versions.packages:
        latest = _safe_fetch_latest(package.distribution_name, fetch_fn)
        enriched.append(
            dataclasses.replace(
                package,
                latest_checked=True,
                latest_version=latest,
                update_available=is_newer(latest, package.installed_version),
                latest_error=None if latest else "unavailable",
            )
        )
    return CoreVersions(packages=tuple(enriched))


def _safe_version(dist_name: str, version_fn: VersionFn) -> str | None:
    try:
        return version_fn(dist_name)
    except importlib_metadata.PackageNotFoundError:
        return None
    except Exception:  # noqa: BLE001 - version display must never crash the UI.
        return None


def _safe_fetch_latest(dist_name: str, fetch_fn: FetchLatestFn) -> str | None:
    try:
        return fetch_fn(dist_name)
    except Exception:  # noqa: BLE001 - one PyPI miss must not break the panel.
        return None


__all__ = [
    "CorePackageVersion",
    "CoreVersions",
    "FetchLatestFn",
    "IsNewerFn",
    "VersionFn",
    "collect_installed_core_versions",
    "enrich_core_versions_latest",
]
