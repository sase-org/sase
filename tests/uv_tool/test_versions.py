"""Tests for SASE core installed/latest version helpers."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError

from sase.uv_tool.versions import (
    collect_installed_core_versions,
    enrich_core_versions_latest,
)


def test_collect_installed_core_versions_uses_runtime_distribution_names() -> None:
    def version(name: str) -> str:
        versions = {"sase": "0.5.0", "sase-core-rs": "1.4.2"}
        return versions[name]

    result = collect_installed_core_versions(version_fn=version)

    assert [
        (p.name, p.distribution_name, p.installed_version) for p in result.packages
    ] == [
        ("sase", "sase", "0.5.0"),
        ("sase-core", "sase-core-rs", "1.4.2"),
    ]


def test_collect_installed_core_versions_tolerates_missing_distribution() -> None:
    def version(name: str) -> str:
        if name == "sase-core-rs":
            raise PackageNotFoundError(name)
        return "0.5.0"

    result = collect_installed_core_versions(version_fn=version)

    assert result.packages[0].installed_version == "0.5.0"
    assert result.packages[1].installed_version is None


def test_enrich_core_versions_latest_marks_updates_and_unknowns() -> None:
    base = collect_installed_core_versions(
        version_fn=lambda name: {"sase": "0.5.0", "sase-core-rs": "1.4.2"}[name]
    )

    result = enrich_core_versions_latest(
        base,
        fetch_fn=lambda name: {"sase": "0.6.0", "sase-core-rs": None}[name],
        is_newer=lambda latest, installed: bool(
            latest and installed and latest > installed
        ),
    )

    assert result.packages[0].latest_version == "0.6.0"
    assert result.packages[0].update_available is True
    assert result.packages[1].latest_version is None
    assert result.packages[1].update_available is False


def test_enrich_core_versions_offline_never_claims_update() -> None:
    base = collect_installed_core_versions(
        version_fn=lambda name: {"sase": "0.5.0", "sase-core-rs": "1.4.2"}[name]
    )

    result = enrich_core_versions_latest(
        base,
        offline=True,
        fetch_fn=lambda _name: "99.0.0",
        is_newer=lambda _latest, _installed: True,
    )

    assert all(package.latest_checked for package in result.packages)
    assert all(package.latest_version is None for package in result.packages)
    assert not result.update_available
