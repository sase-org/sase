"""Tests for the runtime version inventory collector."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Any

import pytest

from sase.version import inventory as inv


class _FakeDistribution:
    def __init__(
        self,
        *,
        name: str,
        version: str,
        location: Path,
        direct_url: str | None = None,
    ) -> None:
        self.metadata = {"Name": name, "Version": version}
        self.version = version
        self._location = location
        self._direct_url = direct_url

    def read_text(self, filename: str) -> str | None:
        if filename == "direct_url.json":
            return self._direct_url
        return None

    def locate_file(self, path: object) -> Path:
        return self._location / str(path)


def _patch_distribution(
    monkeypatch: pytest.MonkeyPatch,
    distribution: _FakeDistribution,
) -> None:
    def fake_distribution(name: str) -> _FakeDistribution:
        if name == distribution.metadata["Name"]:
            return distribution
        raise inv.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(inv.importlib.metadata, "distribution", fake_distribution)


def _package_spec(name: str, package_dir: Path) -> ModuleSpec:
    spec = ModuleSpec(
        name,
        loader=None,
        origin=str(package_dir / "__init__.py"),
        is_package=True,
    )
    spec.submodule_search_locations = [str(package_dir)]
    return spec


def _module_spec(name: str, origin: Path) -> ModuleSpec:
    return ModuleSpec(name, loader=None, origin=str(origin))


def _patch_find_spec(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, ModuleSpec],
) -> None:
    def fake_find_spec(name: str, *_args: Any, **_kwargs: Any) -> ModuleSpec | None:
        return mapping.get(name)

    monkeypatch.setattr(inv.importlib.util, "find_spec", fake_find_spec)


def _editable_direct_url(source_root: Path) -> str:
    return json.dumps(
        {
            "url": source_root.as_uri(),
            "dir_info": {"editable": True},
        }
    )


def test_collect_package_record_uses_wheel_metadata_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_packages = tmp_path / "site-packages"
    package_dir = site_packages / "sase"
    package_dir.mkdir(parents=True)
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

    assert inv.derive_display_version("0.2.3", exact) == "0.2.3"
    assert inv.derive_display_version("0.2.3", ahead) == "0.2.3+2.gabcdef123"
    assert (
        inv.derive_display_version("0.2.3", dirty_exact) == "0.2.3+0.gabcdef123.dirty"
    )
    assert inv.derive_display_version("9.9.9", untagged) == "9.9.9+untagged.gabcdef123"


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


def test_probe_git_metadata_reads_real_git_states(tmp_path: Path) -> None:
    if shutil.which("git") is None:
        pytest.skip("git is not available")

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "file.txt").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "tag", "v1.0.0")

    exact = inv.probe_git_metadata(repo).metadata
    assert exact is not None
    assert inv.derive_display_version("1.0.0", exact) == "1.0.0"

    (repo / "file.txt").write_text("two\n", encoding="utf-8")
    _git(repo, "commit", "-am", "second")
    ahead = inv.probe_git_metadata(repo).metadata
    assert ahead is not None
    assert re.fullmatch(
        r"1\.0\.0\+1\.g[0-9a-f]{9}",
        inv.derive_display_version("1.0.0", ahead),
    )

    (repo / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    dirty = inv.probe_git_metadata(repo).metadata
    assert dirty is not None
    assert re.fullmatch(
        r"1\.0\.0\+1\.g[0-9a-f]{9}\.dirty",
        inv.derive_display_version("1.0.0", dirty),
    )

    untagged_repo = tmp_path / "untagged"
    untagged_repo.mkdir()
    _git(untagged_repo, "init")
    _git(untagged_repo, "config", "user.email", "test@example.com")
    _git(untagged_repo, "config", "user.name", "Test User")
    (untagged_repo / "file.txt").write_text("one\n", encoding="utf-8")
    _git(untagged_repo, "add", "file.txt")
    _git(untagged_repo, "commit", "-m", "initial")

    untagged = inv.probe_git_metadata(untagged_repo).metadata
    assert untagged is not None
    assert re.fullmatch(
        r"2\.0\.0\+untagged\.g[0-9a-f]{9}",
        inv.derive_display_version("2.0.0", untagged),
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
