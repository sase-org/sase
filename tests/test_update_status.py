"""Tests for shared SASE update-status aggregation and caching."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
from pathlib import Path

import pytest

from sase.plugins.catalog import PluginCatalog, PluginCatalogEntry
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from sase.updates import (
    OutdatedComponent,
    UpdateStatus,
    compute_update_status,
    get_cached_update_status,
    read_update_status_snapshot,
    revalidate_update_status,
    update_status_snapshot_is_fresh,
    write_update_status_snapshot,
)
from sase.uv_tool.versions import CorePackageVersion, CoreVersions


def _core_versions(*, update: bool = True) -> CoreVersions:
    return CoreVersions(
        packages=(
            CorePackageVersion(
                name="sase",
                distribution_name="sase",
                installed_version="1.0.0",
                latest_version="1.1.0" if update else "1.0.0",
                latest_checked=True,
                update_available=update,
            ),
            CorePackageVersion(
                name="sase-core",
                distribution_name="sase-core-rs",
                installed_version="2.0.0",
                latest_version="2.0.0",
                latest_checked=True,
                update_available=False,
            ),
        )
    )


def _entry(
    name: str,
    *,
    installed: InstalledInfo,
    latest: LatestInfo,
) -> PluginCatalogEntry:
    repo = f"sase-{name}"
    return PluginCatalogEntry(
        name=name,
        repo=repo,
        full_name=f"sase-org/{repo}",
        owner="sase-org",
        description="",
        url=f"https://github.com/sase-org/{repo}",
        homepage="",
        topics=(),
        stars=0,
        archived=False,
        license="MIT",
        updated_at="2026-06-01",
        installed=installed,
        latest=latest,
    )


def _catalog(*, plugin_update: bool = True) -> PluginCatalog:
    github = _entry(
        "github",
        installed=InstalledInfo(installed=True, version="0.5.0"),
        latest=LatestInfo(
            checked=True,
            version="0.6.0" if plugin_update else "0.5.0",
            source="index",
        ),
    )
    nvim = _entry(
        "nvim",
        installed=InstalledInfo.not_installed(),
        latest=LatestInfo(checked=True, version="1.0.0", source="index"),
    )
    return PluginCatalog(
        fetched_at=1_700_000_000.0,
        entries=(github, nvim),
        from_cache=True,
        stale=False,
    )


def test_compute_update_status_reports_core_and_installed_plugins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.updates.status as status_module

    monkeypatch.setattr(
        status_module,
        "_collect_installed_core_versions",
        lambda: _core_versions(update=False),
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_core_versions_latest",
        lambda versions, **_kwargs: _core_versions(update=True),
    )
    monkeypatch.setattr(
        status_module,
        "_load_plugin_catalog",
        lambda **_kwargs: _catalog(plugin_update=False),
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_with_latest",
        lambda catalog, **_kwargs: _catalog(plugin_update=True),
    )

    result = compute_update_status(now=123.0)

    assert result.checked_at == 123.0
    assert [(c.display_name, c.role) for c in result.components] == [
        ("sase", "host"),
        ("github", "plugin"),
    ]
    assert result.count == 2


def test_compute_update_status_sources_degrade_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.updates.status as status_module

    def _raise_core() -> CoreVersions:
        raise RuntimeError("core unavailable")

    monkeypatch.setattr(status_module, "_collect_installed_core_versions", _raise_core)
    monkeypatch.setattr(
        status_module,
        "_load_plugin_catalog",
        lambda **_kwargs: _catalog(plugin_update=True),
    )
    monkeypatch.setattr(
        status_module,
        "_enrich_with_latest",
        lambda catalog, **_kwargs: catalog,
    )

    result = compute_update_status(now=123.0)

    assert [(c.display_name, c.role) for c in result.components] == [
        ("github", "plugin")
    ]


def test_update_status_snapshot_round_trip_and_freshness(tmp_path: Path) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="1.0.0",
                latest_version="1.1.0",
                distribution_name="sase",
            ),
        ),
    )

    write_update_status_snapshot(status, path=path)

    assert read_update_status_snapshot(path=path) == status
    assert update_status_snapshot_is_fresh(status, now=110.0, ttl_seconds=20)
    assert not update_status_snapshot_is_fresh(status, now=130.0, ttl_seconds=20)


def test_revalidate_update_status_drops_components_updated_locally() -> None:
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="sase",
                role="host",
                installed_version="1.0.0",
                latest_version="1.1.0",
                distribution_name="sase",
            ),
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase-github",
            ),
        ),
    )

    def _version(dist_name: str) -> str:
        if dist_name == "sase":
            return "1.1.0"
        if dist_name == "sase-github":
            return "0.5.0"
        raise importlib_metadata.PackageNotFoundError(dist_name)

    result = revalidate_update_status(status, version_fn=_version)

    assert [component.display_name for component in result.components] == ["github"]


def test_get_cached_update_status_uses_fresh_snapshot_without_compute(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(
        checked_at=100.0,
        components=(
            OutdatedComponent(
                display_name="github",
                role="plugin",
                installed_version="0.5.0",
                latest_version="0.6.0",
                distribution_name="sase-github",
            ),
        ),
    )
    write_update_status_snapshot(status, path=path)

    def _compute(**_kwargs: object) -> UpdateStatus:
        raise AssertionError("fresh cache should not compute")

    result = get_cached_update_status(
        path=path,
        now=110.0,
        ttl_seconds=20,
        compute_fn=_compute,
        version_fn=lambda _dist_name: "0.5.0",
    )

    assert result == status


def test_get_cached_update_status_falls_back_to_snapshot_on_compute_failure(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    status = UpdateStatus(checked_at=100.0, components=())
    write_update_status_snapshot(status, path=path)

    def _compute(**_kwargs: object) -> UpdateStatus:
        raise RuntimeError("offline")

    result = get_cached_update_status(
        path=path,
        now=200.0,
        ttl_seconds=20,
        compute_fn=_compute,
    )

    assert result == status
