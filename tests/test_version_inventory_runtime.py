"""Tests for runtime version inventory collection and git probing."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from sase.version import inventory as inv
from tests._version_inventory_helpers import (
    _FakeDistribution,
    _FakeEntryPoint,
    _editable_direct_url,
    _module_spec,
    _package_spec,
    _patch_distribution_map,
    _patch_distributions,
    _patch_find_spec,
)


def test_collect_runtime_inventory_covers_realistic_install_shapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_root = tmp_path / "venv"
    site_packages = env_root / "lib" / "python3.12" / "site-packages"
    bin_dir = env_root / "bin"
    bin_dir.mkdir(parents=True)
    site_packages.mkdir(parents=True)

    host_root = tmp_path / "sase"
    host_package = host_root / "src" / "sase"
    host_package.mkdir(parents=True)
    (host_root / "pyproject.toml").write_text(
        '[project]\nname = "sase"\nversion = "0.2.0"\n',
        encoding="utf-8",
    )

    core_root = tmp_path / "sase-core"
    core_root.mkdir()
    (core_root / "Cargo.toml").write_text(
        '[workspace]\nmembers = []\n[workspace.package]\nversion = "0.3.0"\n',
        encoding="utf-8",
    )
    core_extension = site_packages / "sase_core_rs.abi3.so"
    core_extension.touch()

    github_package = site_packages / "sase_github"
    github_package.mkdir()
    telegram_package = site_packages / "sase_telegram"
    telegram_package.mkdir()

    github_entry_point = _FakeEntryPoint(
        group="sase_vcs",
        name="github",
        value="sase_github.plugin:Plugin",
    )
    telegram_script = _FakeEntryPoint(
        group="console_scripts",
        name="sase_telegram_bot",
        value="sase_telegram.cli:main",
    )
    host_dist = _FakeDistribution(
        name="sase",
        version="0.1.0",
        location=site_packages,
        direct_url=_editable_direct_url(host_root),
    )
    core_dist = _FakeDistribution(
        name="sase-core-rs",
        version="0.0.0",
        location=site_packages,
        direct_url=_editable_direct_url(core_root),
    )
    github_dist = _FakeDistribution(
        name="sase-github",
        version="1.2.0",
        location=site_packages,
        entry_points=(github_entry_point,),
    )
    telegram_dist = _FakeDistribution(
        name="sase-telegram",
        version="1.3.0",
        location=site_packages,
        entry_points=(telegram_script,),
    )
    dists = [host_dist, core_dist, github_dist, telegram_dist]
    _patch_distribution_map(monkeypatch, dists)
    _patch_distributions(monkeypatch, dists)
    _patch_find_spec(
        monkeypatch,
        {
            "sase": _package_spec("sase", host_package),
            "sase_core_rs": _module_spec("sase_core_rs", core_extension),
            "sase_github": _package_spec("sase_github", github_package),
            "sase_telegram": _package_spec("sase_telegram", telegram_package),
        },
    )
    monkeypatch.setattr(inv.sys, "argv", [str(bin_dir / "sase")])
    monkeypatch.setattr(inv.sys, "executable", str(bin_dir / "python"))

    def fake_git_probe(source_root: Path) -> inv.GitProbeResult:
        return inv.GitProbeResult(
            inv.GitVersionMetadata(
                root=str(source_root),
                commit="abcdef123456",
                short_commit="abcdef123",
                tag=None,
                distance=None,
                dirty=False,
            )
        )

    inventory = inv.collect_runtime_version_inventory(git_probe=fake_git_probe)
    records = {record.name: record for record in inventory.packages}

    assert inventory.executable == str(bin_dir / "sase")
    assert inventory.python_executable == str(bin_dir / "python")

    assert records["sase"].install_type == "editable"
    assert records["sase"].distribution_version == "0.1.0"
    assert records["sase"].source_version == "0.2.0"
    assert records["sase"].display_version == "0.2.0+untagged.gabcdef123"
    assert records["sase"].code_directory == str(host_package)

    assert records["sase-core-rs"].install_type == "editable"
    assert records["sase-core-rs"].distribution_version == "0.0.0"
    assert records["sase-core-rs"].source_version == "0.3.0"
    assert records["sase-core-rs"].code_directory == str(core_root)
    assert records["sase-core-rs"].import_path == str(core_extension)

    assert records["sase-github"].install_type == "wheel"
    assert records["sase-github"].source_root is None
    assert records["sase-github"].code_directory == str(github_package)
    assert records["sase-github"].distribution_location == str(site_packages)
    assert (
        "entry_point:sase_vcs:github=sase_github.plugin:Plugin"
        in records["sase-github"].plugin_signals
    )

    assert records["sase-telegram"].install_type == "wheel"
    assert records["sase-telegram"].code_directory == str(telegram_package)
    assert (
        "console_script:sase_telegram_bot=sase_telegram.cli:main"
        in records["sase-telegram"].plugin_signals
    )
    assert github_entry_point.load_calls == 0
    assert telegram_script.load_calls == 0


def test_collect_runtime_inventory_caches_git_probe_by_source_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "sase"
    host_package = source_root / "src" / "sase"
    plugin_package = source_root / "src" / "sase_shared"
    host_package.mkdir(parents=True)
    plugin_package.mkdir()
    (source_root / "pyproject.toml").write_text(
        '[project]\nname = "sase"\nversion = "0.2.0"\n',
        encoding="utf-8",
    )
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()

    plugin_entry_point = _FakeEntryPoint(
        group="sase_vcs",
        name="shared",
        value="sase_shared.plugin:Plugin",
    )
    host_dist = _FakeDistribution(
        name="sase",
        version="0.1.0",
        location=site_packages,
        direct_url=_editable_direct_url(source_root),
    )
    plugin_dist = _FakeDistribution(
        name="sase-shared",
        version="0.1.0",
        location=site_packages,
        direct_url=_editable_direct_url(source_root),
        entry_points=(plugin_entry_point,),
    )
    _patch_distribution_map(monkeypatch, [host_dist, plugin_dist])
    _patch_distributions(monkeypatch, [host_dist, plugin_dist])
    _patch_find_spec(
        monkeypatch,
        {
            "sase": _package_spec("sase", host_package),
            "sase_shared": _package_spec("sase_shared", plugin_package),
        },
    )

    calls: list[Path] = []

    def fake_git_probe(root: Path) -> inv.GitProbeResult:
        calls.append(root)
        return inv.GitProbeResult(
            inv.GitVersionMetadata(
                root=str(root),
                commit="abcdef123456",
                short_commit="abcdef123",
                tag="v0.2.0",
                distance=0,
                dirty=False,
            )
        )

    inventory = inv.collect_runtime_version_inventory(git_probe=fake_git_probe)

    assert [record.name for record in inventory.packages] == [
        "sase",
        "sase-core-rs",
        "sase-shared",
    ]
    assert calls == [source_root]
    assert plugin_entry_point.load_calls == 0


def test_run_git_uses_short_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(*_args: object, **kwargs: object) -> object:
        captured.update(kwargs)

        class _Completed:
            stdout = "abcdef123\n"

        return _Completed()

    monkeypatch.setattr(inv.subprocess, "run", fake_run)

    assert inv._run_git(tmp_path, "rev-parse", "HEAD") == "abcdef123"
    assert captured["timeout"] == pytest.approx(1.0)
    assert captured["check"] is True
    assert captured["capture_output"] is True
    assert captured["text"] is True


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


def test_probe_git_metadata_reports_unexecutable_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A git binary that cannot be executed degrades to a warning, not a crash."""
    from sase.version import _git as git_mod

    def _raise(*args: object, **kwargs: object) -> None:
        raise PermissionError(13, "Permission denied", "git")

    monkeypatch.setattr(git_mod.subprocess, "run", _raise)

    result = inv.probe_git_metadata(tmp_path)

    assert result.metadata is None
    assert "git could not be executed" in (result.warning or "")
