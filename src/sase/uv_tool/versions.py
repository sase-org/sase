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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from sase.dev_update.detect import detect_dev_latest
from sase.dev_update.models import DevLatest
from sase.version.inventory import CORE_DISTRIBUTION_NAME, HOST_DISTRIBUTION_NAME
from sase.version.inventory import (
    VersionPackageRecord,
    collect_runtime_version_inventory,
)

VersionFn = Callable[[str], str | None]
FetchLatestFn = Callable[[str], str | None]
IsNewerFn = Callable[[str | None, str | None], bool]
VersionRecordsFn = Callable[[], Sequence[VersionPackageRecord]]


class _DetectDevLatestFn(Protocol):
    def __call__(self, record: VersionPackageRecord, *, offline: bool) -> DevLatest:
        """Return latest-dev metadata for one editable core package."""
        ...


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
    install_type: str | None = None
    latest_state: str | None = None
    latest_reason: str | None = None


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


def _runtime_core_records() -> Sequence[VersionPackageRecord]:
    return collect_runtime_version_inventory(include_plugins=False).packages


def enrich_core_versions_latest(
    versions: CoreVersions,
    *,
    offline: bool = False,
    fetch_fn: FetchLatestFn,
    is_newer: IsNewerFn,
    version_records_fn: VersionRecordsFn | None = _runtime_core_records,
    detect_dev_latest_fn: _DetectDevLatestFn = detect_dev_latest,
) -> CoreVersions:
    """Return *versions* with best-effort latest-version metadata attached."""
    records = _record_lookup(_safe_version_records(version_records_fn))

    enriched: list[CorePackageVersion] = []
    for package in versions.packages:
        record = records.get(package.distribution_name)
        if record is not None and record.install_type == "editable":
            enriched.append(
                _enrich_editable_core_package(
                    package,
                    record=record,
                    offline=offline,
                    detect_dev_latest_fn=detect_dev_latest_fn,
                )
            )
            continue
        if offline:
            enriched.append(
                dataclasses.replace(
                    package,
                    latest_checked=True,
                    latest_version=None,
                    update_available=False,
                    latest_error="offline",
                    install_type=_install_type(record, package.install_type),
                    latest_state="offline",
                    latest_reason="offline",
                )
            )
            continue
        latest = _safe_fetch_latest(package.distribution_name, fetch_fn)
        enriched.append(
            dataclasses.replace(
                package,
                latest_checked=True,
                latest_version=latest,
                update_available=is_newer(latest, package.installed_version),
                latest_error=None if latest else "unavailable",
                install_type=_install_type(record, package.install_type),
            )
        )
    return CoreVersions(packages=tuple(enriched))


def _safe_version_records(
    version_records_fn: VersionRecordsFn | None,
) -> Sequence[VersionPackageRecord]:
    if version_records_fn is None:
        return ()
    try:
        return version_records_fn()
    except Exception:  # noqa: BLE001 - version display must never break the UI.
        return ()


def _record_lookup(
    records: Sequence[VersionPackageRecord],
) -> dict[str, VersionPackageRecord]:
    return {
        record.name: record for record in records if record.role in {"host", "core"}
    }


def _enrich_editable_core_package(
    package: CorePackageVersion,
    *,
    record: VersionPackageRecord,
    offline: bool,
    detect_dev_latest_fn: _DetectDevLatestFn,
) -> CorePackageVersion:
    try:
        latest = detect_dev_latest_fn(record, offline=offline)
    except Exception as exc:  # noqa: BLE001 - latest hints are best effort.
        reason = f"dev version unavailable: {exc}"
        return dataclasses.replace(
            package,
            installed_version=record.display_version,
            latest_checked=True,
            latest_version=None,
            update_available=False,
            latest_error=reason,
            install_type=record.install_type,
            latest_state="unavailable",
            latest_reason=reason,
        )
    return dataclasses.replace(
        package,
        installed_version=latest.current_version,
        latest_checked=True,
        latest_version=latest.latest_version,
        update_available=latest.update_available,
        latest_error=_dev_error(latest),
        install_type=record.install_type,
        latest_state=latest.state,
        latest_reason=latest.reason,
    )


def _install_type(
    record: VersionPackageRecord | None, fallback: str | None
) -> str | None:
    if record is not None:
        return record.install_type
    return fallback


def _dev_error(latest: DevLatest) -> str | None:
    if latest.state == "fetch_failed":
        return latest.fetch_error or latest.reason
    if latest.state == "unavailable":
        return latest.reason
    return None


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
