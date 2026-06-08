"""Tests for version inventory plugin discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.version import inventory as inv
from tests._version_inventory_helpers import (
    _FakeDistribution,
    _FakeEntryPoint,
    _package_spec,
    _patch_distributions,
    _patch_find_spec,
)


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
