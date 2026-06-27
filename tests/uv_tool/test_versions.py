"""Tests for SASE core installed/latest version helpers."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from typing import Literal

from sase.dev_update.models import DevLatest
from sase.uv_tool.versions import (
    CoreVersions,
    collect_installed_core_versions,
    enrich_core_versions_latest,
)
from sase.version._models import VersionPackageRecord


def _record(
    name: str,
    *,
    role: Literal["host", "core", "plugin"],
    display_version: str,
) -> VersionPackageRecord:
    return VersionPackageRecord(
        name=name,
        role=role,
        display_version=display_version,
        distribution_version="0.5.0",
        source_version="0.5.0",
        import_module=name.replace("-", "_"),
        import_path=None,
        code_directory="/src/pkg",
        source_root="/src/pkg",
        distribution_location=None,
        install_type="editable",
        git=None,
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
        version_records_fn=lambda: (),
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
        version_records_fn=lambda: (),
    )

    assert all(package.latest_checked for package in result.packages)
    assert all(package.latest_version is None for package in result.packages)
    assert not result.update_available


def test_enrich_core_versions_latest_uses_dev_detection_for_editables() -> None:
    base = CoreVersions(
        packages=(
            collect_installed_core_versions(
                version_fn=lambda name: {
                    "sase": "0.5.0",
                    "sase-core-rs": "1.4.2",
                }[name]
            ).packages[0],
        )
    )
    record = _record(
        "sase",
        role="host",
        display_version="0.5.0+1.gabc123def",
    )
    seen: list[tuple[str, bool]] = []

    def _detect(package: VersionPackageRecord, *, offline: bool) -> DevLatest:
        seen.append((package.name, offline))
        return DevLatest(
            record=package,
            state="dirty",
            reason="checkout has local changes",
            current_version=package.display_version,
            latest_version="0.5.0+3.gdef456abc",
            update_available=False,
        )

    result = enrich_core_versions_latest(
        base,
        offline=True,
        fetch_fn=lambda _name: "99.0.0",
        is_newer=lambda _latest, _installed: True,
        version_records_fn=lambda: (record,),
        detect_dev_latest_fn=_detect,
    )

    package = result.packages[0]
    assert seen == [("sase", True)]
    assert package.installed_version == "0.5.0+1.gabc123def"
    assert package.latest_version == "0.5.0+3.gdef456abc"
    assert package.install_type == "editable"
    assert package.latest_state == "dirty"
    assert package.latest_reason == "checkout has local changes"
    assert package.update_available is False
