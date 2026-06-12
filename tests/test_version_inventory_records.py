"""Tests for version inventory package records."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.version import inventory as inv
from tests._version_inventory_helpers import (
    _FakeDistribution,
    _editable_direct_url,
    _module_spec,
    _package_spec,
    _patch_distribution,
    _patch_find_spec,
)


def test_collect_package_record_uses_wheel_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_packages = tmp_path / "site-packages"
    package_dir = site_packages / "sase"
    package_dir.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "workspace"\nversion = "9.9.9"\n',
        encoding="utf-8",
    )
    dist = _FakeDistribution(
        name="sase",
        version="1.2.3",
        location=site_packages,
    )
    _patch_distribution(monkeypatch, dist)
    _patch_find_spec(monkeypatch, {"sase": _package_spec("sase", package_dir)})

    record = inv.collect_package_record(
        "sase",
        role="host",
        import_module="sase",
        source_kind="python",
        git_probe=None,
    )

    assert record.display_version == "1.2.3"
    assert record.distribution_version == "1.2.3"
    assert record.source_version is None
    assert record.install_type == "wheel"
    assert record.import_path == str(package_dir)
    assert record.code_directory == str(package_dir)
    assert record.source_root is None
    assert record.warnings == ()


def test_editable_python_prefers_source_version_when_metadata_is_stale(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "sase"
    package_dir = source_root / "src" / "sase"
    package_dir.mkdir(parents=True)
    (source_root / "pyproject.toml").write_text(
        '[project]\nname = "sase"\nversion = "2.0.0"\n',
        encoding="utf-8",
    )
    dist = _FakeDistribution(
        name="sase",
        version="1.0.0",
        location=tmp_path / "site-packages",
        direct_url=_editable_direct_url(source_root),
    )
    _patch_distribution(monkeypatch, dist)
    _patch_find_spec(monkeypatch, {"sase": _package_spec("sase", package_dir)})

    record = inv.collect_package_record(
        "sase",
        role="host",
        import_module="sase",
        source_kind="python",
        git_probe=None,
    )

    assert record.display_version == "2.0.0"
    assert record.distribution_version == "1.0.0"
    assert record.source_version == "2.0.0"
    assert record.install_type == "editable"
    assert record.source_root == str(source_root)
    assert record.code_directory == str(package_dir)


def test_editable_rust_core_reads_cargo_workspace_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "sase-core"
    source_root.mkdir()
    (source_root / "Cargo.toml").write_text(
        '[workspace]\nmembers = []\n[workspace.package]\nversion = "0.7.0"\n',
        encoding="utf-8",
    )
    extension_path = tmp_path / "site-packages" / "sase_core_rs.abi3.so"
    extension_path.parent.mkdir()
    dist = _FakeDistribution(
        name="sase-core-rs",
        version="0.0.0",
        location=extension_path.parent,
        direct_url=_editable_direct_url(source_root),
    )
    _patch_distribution(monkeypatch, dist)
    _patch_find_spec(
        monkeypatch,
        {"sase_core_rs": _module_spec("sase_core_rs", extension_path)},
    )

    record = inv.collect_package_record(
        "sase-core-rs",
        role="core",
        import_module="sase_core_rs",
        source_kind="rust",
        git_probe=None,
    )

    assert record.display_version == "0.7.0"
    assert record.distribution_version == "0.0.0"
    assert record.source_version == "0.7.0"
    assert record.source_root == str(source_root)
    assert record.code_directory == str(source_root)
    assert record.import_path == str(extension_path)


def test_derive_display_version_for_git_states() -> None:
    exact = inv.GitVersionMetadata(
        root="/repo",
        commit="abcdef123456",
        short_commit="abcdef123",
        tag="v0.2.3",
        distance=0,
        dirty=False,
    )
    ahead = inv.GitVersionMetadata(
        root="/repo",
        commit="abcdef123456",
        short_commit="abcdef123",
        tag="v0.2.3",
        distance=2,
        dirty=False,
    )
    dirty_exact = inv.GitVersionMetadata(
        root="/repo",
        commit="abcdef123456",
        short_commit="abcdef123",
        tag="v0.2.3",
        distance=0,
        dirty=True,
    )
    untagged = inv.GitVersionMetadata(
        root="/repo",
        commit="abcdef123456",
        short_commit="abcdef123",
        tag=None,
        distance=None,
        dirty=False,
    )
    unknown_distance = inv.GitVersionMetadata(
        root="/repo",
        commit="abcdef123456",
        short_commit="abcdef123",
        tag="v0.2.3",
        distance=None,
        dirty=False,
    )

    assert inv.derive_display_version("0.2.3", exact) == "0.2.3"
    assert inv.derive_display_version("0.2.3", ahead) == "0.2.3+2.gabcdef123"
    assert (
        inv.derive_display_version("0.2.3", dirty_exact) == "0.2.3+0.gabcdef123.dirty"
    )
    assert inv.derive_display_version("9.9.9", untagged) == "9.9.9+untagged.gabcdef123"
    # A failed distance probe must not be mistaken for an exact release.
    assert (
        inv.derive_display_version("0.2.3", unknown_distance)
        == "0.2.3+unknown.gabcdef123"
    )


def test_collect_package_record_falls_back_when_git_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "sase"
    package_dir = source_root / "src" / "sase"
    package_dir.mkdir(parents=True)
    (source_root / "pyproject.toml").write_text(
        '[project]\nname = "sase"\nversion = "2.0.0"\n',
        encoding="utf-8",
    )
    dist = _FakeDistribution(
        name="sase",
        version="1.0.0",
        location=tmp_path / "site-packages",
        direct_url=_editable_direct_url(source_root),
    )
    _patch_distribution(monkeypatch, dist)
    _patch_find_spec(monkeypatch, {"sase": _package_spec("sase", package_dir)})

    record = inv.collect_package_record(
        "sase",
        role="host",
        import_module="sase",
        source_kind="python",
        git_probe=lambda _root: inv.GitProbeResult(None, "git unavailable"),
    )

    assert record.display_version == "2.0.0"
    assert "git unavailable" in record.warnings


def test_missing_source_metadata_falls_back_to_distribution_version(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "sase"
    package_dir = source_root / "src" / "sase"
    package_dir.mkdir(parents=True)
    dist = _FakeDistribution(
        name="sase",
        version="1.0.0",
        location=tmp_path / "site-packages",
        direct_url=_editable_direct_url(source_root),
    )
    _patch_distribution(monkeypatch, dist)
    _patch_find_spec(monkeypatch, {"sase": _package_spec("sase", package_dir)})

    record = inv.collect_package_record(
        "sase",
        role="host",
        import_module="sase",
        source_kind="python",
        git_probe=None,
    )

    assert record.display_version == "1.0.0"
    assert record.source_version is None
    assert any("source version metadata not found" in msg for msg in record.warnings)


def test_rust_source_root_ignores_ancestor_cargo_for_wheel_installs(
    tmp_path: Path,
) -> None:
    """A wheel install must not adopt an unrelated ancestor Cargo.toml.

    Regression test: with the venv living under someone else's Rust project
    (a common layout), the ancestor climb from site-packages would report
    that project's version and git state for a wheel-installed core.
    """
    from sase.version._models import ImportResolution
    from sase.version._sources import source_root

    unrelated = tmp_path / "my_rust_project"
    site_packages = unrelated / ".venv" / "lib" / "site-packages"
    site_packages.mkdir(parents=True)
    (unrelated / "Cargo.toml").write_text(
        '[package]\nname = "unrelated"\nversion = "7.7.7"\n',
        encoding="utf-8",
    )

    resolved = source_root(
        source_kind="rust",
        direct_url=None,
        install_type="wheel",
        import_resolution=ImportResolution(
            site_packages / "sase_core_rs.so", site_packages
        ),
        distribution_location=site_packages,
    )

    assert resolved is None


def test_rust_source_root_still_climbs_for_editable_installs(
    tmp_path: Path,
) -> None:
    from sase.version._models import ImportResolution
    from sase.version._sources import source_root

    project = tmp_path / "sase-core"
    code_dir = project / "bindings" / "python"
    code_dir.mkdir(parents=True)
    (project / "Cargo.toml").write_text(
        '[package]\nname = "sase-core"\nversion = "0.1.1"\n',
        encoding="utf-8",
    )

    resolved = source_root(
        source_kind="rust",
        direct_url=None,
        install_type="editable",
        import_resolution=ImportResolution(code_dir / "mod.so", code_dir),
        distribution_location=None,
    )

    assert resolved == project
