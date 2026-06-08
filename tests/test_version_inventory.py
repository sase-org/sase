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
        entry_points: tuple[_FakeEntryPoint, ...] = (),
        top_level_text: str | None = None,
    ) -> None:
        self.metadata = {"Name": name, "Version": version}
        self.version = version
        self._location = location
        self._direct_url = direct_url
        self.entry_points = entry_points
        self._top_level_text = top_level_text

    def read_text(self, filename: str) -> str | None:
        if filename == "direct_url.json":
            return self._direct_url
        if filename == "top_level.txt":
            return self._top_level_text
        return None

    def locate_file(self, path: object) -> Path:
        return self._location / str(path)


class _FakeEntryPoint:
    def __init__(self, *, group: str, name: str, value: str) -> None:
        self.group = group
        self.name = name
        self.value = value
        self.load_calls = 0

    def load(self) -> object:
        self.load_calls += 1
        raise AssertionError("version inventory must not load plugin entry points")


def _patch_distribution(
    monkeypatch: pytest.MonkeyPatch,
    distribution: _FakeDistribution,
) -> None:
    def fake_distribution(name: str) -> _FakeDistribution:
        if name == distribution.metadata["Name"]:
            return distribution
        raise inv.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(inv.importlib.metadata, "distribution", fake_distribution)


def _patch_distribution_map(
    monkeypatch: pytest.MonkeyPatch,
    distributions: list[_FakeDistribution],
) -> None:
    by_name = {
        inv._normalize_distribution_name(dist.metadata["Name"]): dist
        for dist in distributions
    }

    def fake_distribution(name: str) -> _FakeDistribution:
        dist = by_name.get(inv._normalize_distribution_name(name))
        if dist is not None:
            return dist
        raise inv.importlib.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(inv.importlib.metadata, "distribution", fake_distribution)


def _patch_distributions(
    monkeypatch: pytest.MonkeyPatch,
    distributions: list[_FakeDistribution],
) -> None:
    monkeypatch.setattr(inv.importlib.metadata, "distributions", lambda: distributions)


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


def test_plugin_discovery_detects_sase_entry_point_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_packages = tmp_path / "site-packages"
    package_dir = site_packages / "sase_github"
    package_dir.mkdir(parents=True)
    entry_point = _FakeEntryPoint(
        group="sase_vcs",
        name="github",
        value="sase_github.plugin:GitHubPlugin",
    )
    dist = _FakeDistribution(
        name="sase-github",
        version="1.2.0",
        location=site_packages,
        entry_points=(entry_point,),
    )
    _patch_distributions(monkeypatch, [dist])
    _patch_find_spec(
        monkeypatch, {"sase_github": _package_spec("sase_github", package_dir)}
    )

    records = inv._collect_plugin_package_records(git_probe=None)

    assert len(records) == 1
    record = records[0]
    assert record.name == "sase-github"
    assert record.role == "plugin"
    assert record.import_module == "sase_github"
    assert record.code_directory == str(package_dir)
    assert "distribution_name:sase-github" in record.plugin_signals
    assert (
        "entry_point:sase_vcs:github=sase_github.plugin:GitHubPlugin"
        in record.plugin_signals
    )
    assert entry_point.load_calls == 0


def test_plugin_discovery_detects_console_script_plugin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_packages = tmp_path / "site-packages"
    package_dir = site_packages / "sase_telegram"
    package_dir.mkdir(parents=True)
    script = _FakeEntryPoint(
        group="console_scripts",
        name="sase_telegram_bot",
        value="sase_telegram.cli:main",
    )
    dist = _FakeDistribution(
        name="sase-telegram",
        version="0.5.0",
        location=site_packages,
        entry_points=(script,),
    )
    _patch_distributions(monkeypatch, [dist])
    _patch_find_spec(
        monkeypatch,
        {"sase_telegram": _package_spec("sase_telegram", package_dir)},
    )

    record = inv._collect_plugin_package_records(git_probe=None)[0]

    assert record.name == "sase-telegram"
    assert record.import_module == "sase_telegram"
    assert record.code_directory == str(package_dir)
    assert "distribution_name:sase-telegram" in record.plugin_signals
    assert "console_script:sase_telegram_bot=sase_telegram.cli:main" in (
        record.plugin_signals
    )
    assert script.load_calls == 0


def test_plugin_discovery_deduplicates_multiple_signals_for_distribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_packages = tmp_path / "site-packages"
    package_dir = site_packages / "sase_both"
    package_dir.mkdir(parents=True)
    entry_point = _FakeEntryPoint(
        group="sase_xprompts",
        name="prompts",
        value="sase_both.resources",
    )
    script = _FakeEntryPoint(
        group="console_scripts",
        name="sase_chop_both",
        value="sase_both.chops:main",
    )
    dist = _FakeDistribution(
        name="sase-both",
        version="3.0.0",
        location=site_packages,
        entry_points=(entry_point, script),
    )
    _patch_distributions(monkeypatch, [dist])
    _patch_find_spec(
        monkeypatch, {"sase_both": _package_spec("sase_both", package_dir)}
    )

    records = inv._collect_plugin_package_records(git_probe=None)

    assert len(records) == 1
    assert records[0].plugin_signals == (
        "console_script:sase_chop_both=sase_both.chops:main",
        "distribution_name:sase-both",
        "entry_point:sase_xprompts:prompts=sase_both.resources",
    )
    assert entry_point.load_calls == 0
    assert script.load_calls == 0


def test_plugin_discovery_reports_malformed_plugin_with_distribution_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_packages = tmp_path / "site-packages"
    site_packages.mkdir()
    dist = _FakeDistribution(
        name="sase-broken",
        version="9.9.9",
        location=site_packages,
    )
    _patch_distributions(monkeypatch, [dist])
    _patch_find_spec(monkeypatch, {})

    record = inv._collect_plugin_package_records(git_probe=None)[0]

    assert record.name == "sase-broken"
    assert record.import_module == "sase_broken"
    assert record.code_directory == str(site_packages)
    assert record.plugin_signals == ("distribution_name:sase-broken",)
    assert any(
        "could not resolve import module sase_broken" in msg for msg in record.warnings
    )
    assert any(
        "falling back to distribution location" in msg for msg in record.warnings
    )


def test_plugin_discovery_ignores_disabled_plugin_env_vars_for_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    site_packages = tmp_path / "site-packages"
    package_dir = site_packages / "company_plugin"
    package_dir.mkdir(parents=True)
    entry_point = _FakeEntryPoint(
        group="sase_vcs",
        name="company",
        value="company_plugin.vcs:Plugin",
    )
    dist = _FakeDistribution(
        name="company-plugin",
        version="1.0.0",
        location=site_packages,
        entry_points=(entry_point,),
    )
    _patch_distributions(monkeypatch, [dist])
    _patch_find_spec(
        monkeypatch,
        {"company_plugin": _package_spec("company_plugin", package_dir)},
    )
    monkeypatch.setenv("SASE_DISABLE_PLUGINS", "1")
    monkeypatch.setenv("SASE_DISABLE_PLUGIN_VCS", "1")

    records = inv._collect_plugin_package_records(git_probe=None)

    assert [record.name for record in records] == ["company-plugin"]
    assert records[0].code_directory == str(package_dir)
    assert entry_point.load_calls == 0


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
