"""Tests for merging the catalog with locally-installed plugin inventory."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.plugins.catalog import load_plugin_catalog
from sase.plugins import installed as installed_module
from sase.plugins.installed import (
    InstalledInfo,
    _ReceiptOwnedPlugin,
    _installed_plugin_distributions,
    _receipt_owned_plugins,
    any_plugins_installed,
    build_installed_index,
    lookup_installed,
)
from sase.plugins.inventory import (
    PluginInventory,
    _PluginDistributionRecord,
)
from sase.uv_tool import (
    NotUvToolInstall,
    NotUvToolReason,
    Requirement,
    ToolReceipt,
    UvToolInstall,
)
from sase.version._plugins import PluginCandidate, plugin_candidates_from_distributions
from tests._version_inventory_helpers import _FakeDistribution, _FakeEntryPoint


def _inventory(
    distributions: list[_PluginDistributionRecord],
) -> PluginInventory:
    return PluginInventory(
        entry_points=(),
        distributions=tuple(distributions),
        disabled_env=(),
    )


def _uv_install(tmp_path: Path) -> UvToolInstall:
    sase_dir = tmp_path / "tools" / "sase"
    return UvToolInstall(
        uv_path="/usr/bin/uv",
        tool_dir=sase_dir.parent,
        sase_dir=sase_dir,
        receipt_path=sase_dir / "uv-receipt.toml",
    )


def _not_uv_install(tmp_path: Path) -> NotUvToolInstall:
    sase_dir = tmp_path / "tools" / "sase"
    return NotUvToolInstall(
        reason=NotUvToolReason.WRONG_PREFIX,
        sys_prefix=tmp_path / ".venv",
        expected_sase_dir=sase_dir,
        receipt_path=sase_dir / "uv-receipt.toml",
        uv_path="/usr/bin/uv",
    )


def _receipt(*plugins: Requirement) -> ToolReceipt:
    primary = Requirement(name="sase")
    return ToolReceipt(
        primary=primary,
        plugins=plugins,
        requirements=(primary, *plugins),
    )


def test_build_index_distribution_match_carries_groups_and_version() -> None:
    dist = _PluginDistributionRecord(
        package="sase-github",
        version="0.4.1",
        entry_points=("sase_vcs:github", "sase_workspace:github"),
    )

    index = build_installed_index(
        inventory_fn=lambda **_kwargs: _inventory([dist]),
        candidates_fn=lambda: (),
    )

    info = index["sase-github"]
    assert info.installed is True
    assert info.version == "0.4.1"
    assert info.entry_point_groups == ("sase_vcs", "sase_workspace")


def test_build_index_detects_console_script_only_plugin(tmp_path: Path) -> None:
    script = _FakeEntryPoint(
        group="console_scripts",
        name="sase_telegram_bot",
        value="sase_telegram.cli:main",
    )
    dist = _FakeDistribution(
        name="sase-telegram",
        version="0.5.0",
        location=tmp_path,
        entry_points=(script,),
    )
    candidates = plugin_candidates_from_distributions([dist])

    index = build_installed_index(
        inventory_fn=lambda **_kwargs: _inventory([]),
        candidates_fn=lambda: candidates,
    )

    info = index["sase-telegram"]
    assert info.installed is True
    assert info.version == "0.5.0"
    # Console-script-only plugins contribute no ``sase_*`` entry-point groups.
    assert info.entry_point_groups == ()


def test_bugyi_chops_requires_receipt_membership(tmp_path: Path) -> None:
    scripts = tuple(
        _FakeEntryPoint(
            group="console_scripts",
            name=name,
            value=f"bugyi_chops.{name}:main",
        )
        for name in (
            "bugyi_chop_gh_open",
            "bugyi_chop_smart_gemini",
            "bugyi_chop_youtrack",
        )
    )
    dist = _FakeDistribution(
        name="bugyi-chops",
        version="0.2.0",
        location=tmp_path,
        entry_points=scripts,
    )

    assert plugin_candidates_from_distributions([dist]) == ()

    receipt_plugins = _receipt_owned_plugins(
        probe_fn=lambda: _uv_install(tmp_path),
        receipt_loader_fn=lambda _path: _receipt(
            Requirement(name="bugyi-chops", git="https://example.com/bugyi-chops")
        ),
        distribution_fn=lambda _name: dist,  # type: ignore[arg-type]
    )
    index = build_installed_index(
        inventory_fn=lambda **_kwargs: _inventory([]),
        candidates_fn=lambda: (),
        receipt_plugins_fn=lambda: receipt_plugins,
    )

    assert index["bugyi-chops"] == InstalledInfo(
        installed=True,
        version="0.2.0",
        entry_point_groups=(),
    )


def test_build_index_prefers_entry_point_inventory_over_receipt() -> None:
    dist = _PluginDistributionRecord(
        package="sase-github",
        version="0.4.1",
        entry_points=("sase_vcs:github",),
    )

    index = build_installed_index(
        inventory_fn=lambda **_kwargs: _inventory([dist]),
        candidates_fn=lambda: (),
        receipt_plugins_fn=lambda: (_ReceiptOwnedPlugin("sase-github", "9.9.9"),),
    )

    assert index["sase-github"] == InstalledInfo(
        installed=True,
        version="0.4.1",
        entry_point_groups=("sase_vcs",),
    )


def test_receipt_reader_dedupes_and_skips_missing_distribution(
    tmp_path: Path,
) -> None:
    dist = _FakeDistribution(
        name="bugyi-chops",
        version="0.2.0",
        location=tmp_path,
    )
    lookups: list[str] = []

    def distribution_fn(name: str) -> _FakeDistribution:
        lookups.append(name)
        if name == "missing-plugin":
            raise installed_module.importlib.metadata.PackageNotFoundError(name)
        return dist

    plugins = _receipt_owned_plugins(
        probe_fn=lambda: _uv_install(tmp_path),
        receipt_loader_fn=lambda _path: _receipt(
            Requirement(name="Bugyi_Chops"),
            Requirement(name="bugyi-chops"),
            Requirement(name="missing-plugin"),
        ),
        distribution_fn=distribution_fn,  # type: ignore[arg-type]
    )

    assert plugins == (_ReceiptOwnedPlugin("bugyi-chops", "0.2.0"),)
    assert lookups == ["Bugyi_Chops", "missing-plugin"]


def test_receipt_reader_ignores_non_uv_runtime(tmp_path: Path) -> None:
    def load_receipt(_path: Path) -> ToolReceipt:
        raise AssertionError("non-uv runtime must not read a receipt")

    assert (
        _receipt_owned_plugins(
            probe_fn=lambda: _not_uv_install(tmp_path),
            receipt_loader_fn=load_receipt,
        )
        == ()
    )


@pytest.mark.parametrize("failure", ["probe", "receipt"])
def test_receipt_reader_falls_back_on_probe_or_receipt_failure(
    failure: str,
    tmp_path: Path,
) -> None:
    def probe() -> UvToolInstall:
        if failure == "probe":
            raise OSError("probe failed")
        return _uv_install(tmp_path)

    def load_receipt(_path: Path) -> ToolReceipt:
        if failure == "receipt":
            raise OSError("receipt failed")
        return _receipt(Requirement(name="bugyi-chops"))

    assert (
        _receipt_owned_plugins(
            probe_fn=probe,
            receipt_loader_fn=load_receipt,
        )
        == ()
    )


def test_receipt_only_plugin_merges_into_community_catalog(tmp_path: Path) -> None:
    dist = _FakeDistribution(
        name="bugyi-chops",
        version="0.2.0",
        location=tmp_path,
    )
    receipt_plugins = _receipt_owned_plugins(
        probe_fn=lambda: _uv_install(tmp_path),
        receipt_loader_fn=lambda _path: _receipt(
            Requirement(name="bugyi-chops", git="https://example.com/bugyi-chops")
        ),
        distribution_fn=lambda _name: dist,  # type: ignore[arg-type]
    )

    catalog = load_plugin_catalog(
        now=1000.0,
        fetch_fn=lambda: [
            {
                "name": "bugyi-chops",
                "repo": "bugyi-chops",
                "full_name": "bbugyi200/bugyi-chops",
                "owner": "bbugyi200",
                "description": "",
                "url": "",
                "homepage": "",
                "topics": ["sase--plugin"],
                "stars": 0,
                "archived": False,
                "license": "",
                "updated_at": "",
            }
        ],
        read_cache_fn=lambda: None,
        write_cache_fn=lambda *_args, **_kwargs: None,
        installed_index_fn=lambda: build_installed_index(
            inventory_fn=lambda **_kwargs: _inventory([]),
            candidates_fn=lambda: (),
            receipt_plugins_fn=lambda: receipt_plugins,
        ),
    )

    entry = catalog.entries[0]
    assert entry.kind == "community"
    assert entry.installed == InstalledInfo(
        installed=True,
        version="0.2.0",
        entry_point_groups=(),
    )
    assert catalog.installed_count == 1


def test_build_index_prefers_entry_point_distribution_over_console_script(
    tmp_path: Path,
) -> None:
    dist_record = _PluginDistributionRecord(
        package="sase-github",
        version="0.4.1",
        entry_points=("sase_vcs:github",),
    )
    script = _FakeEntryPoint(
        group="console_scripts",
        name="sase_github_helper",
        value="sase_github.cli:main",
    )
    candidate_dist = _FakeDistribution(
        name="sase-github",
        version="9.9.9",
        location=tmp_path,
        entry_points=(script,),
    )
    candidates = plugin_candidates_from_distributions([candidate_dist])

    index = build_installed_index(
        inventory_fn=lambda **_kwargs: _inventory([dist_record]),
        candidates_fn=lambda: candidates,
    )

    # The inventory entry (with real groups) wins over the console-script entry.
    info = index["sase-github"]
    assert info.version == "0.4.1"
    assert info.entry_point_groups == ("sase_vcs",)


def test_build_index_drops_unknown_version_sentinel() -> None:
    dist = _PluginDistributionRecord(
        package="sase-mystery",
        version="<unknown>",
        entry_points=("sase_config:mystery",),
    )

    index = build_installed_index(
        inventory_fn=lambda **_kwargs: _inventory([dist]),
        candidates_fn=lambda: (),
    )

    assert index["sase-mystery"].version is None


def test_lookup_installed_matches_repo() -> None:
    index = {
        "sase-github": InstalledInfo(installed=True, version="0.4.1"),
    }
    info = lookup_installed(index, repo="sase-github", name="github")
    assert info.version == "0.4.1"


def test_lookup_installed_missing_is_not_installed() -> None:
    info = lookup_installed({}, repo="sase-telegram", name="telegram")
    assert info == InstalledInfo.not_installed()
    assert info.installed is False
    assert info.version is None
    assert info.entry_point_groups == ()


def test_any_plugins_installed_false_for_empty_candidates() -> None:
    assert (
        any_plugins_installed(
            candidates_fn=lambda: (),
            receipt_plugins_fn=lambda: (),
        )
        is False
    )


def test_any_plugins_installed_true_for_plugin_candidate(tmp_path: Path) -> None:
    dist = _FakeDistribution(
        name="sase-github",
        version="0.4.1",
        location=tmp_path,
    )
    candidate = PluginCandidate(
        distribution_name="sase-github",
        distribution=dist,
        import_module="sase_github",
        plugin_signals=("distribution_name:sase-github",),
    )

    assert (
        any_plugins_installed(
            candidates_fn=lambda: (candidate,),
            receipt_plugins_fn=lambda: (),
        )
        is True
    )
    assert _installed_plugin_distributions(
        candidates_fn=lambda: (candidate,),
        receipt_plugins_fn=lambda: (),
    ) == ("sase-github",)


def test_any_plugins_installed_true_for_receipt_only_plugin() -> None:
    receipt_plugin = _ReceiptOwnedPlugin("bugyi-chops", "0.2.0")

    assert (
        any_plugins_installed(
            candidates_fn=lambda: (),
            receipt_plugins_fn=lambda: (receipt_plugin,),
        )
        is True
    )


def test_installed_plugin_distributions_excludes_runtime_distributions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    host_ep = _FakeEntryPoint(
        group="sase_config",
        name="host",
        value="sase.config:load",
    )
    host_dist = _FakeDistribution(
        name="sase",
        version="1.2.3",
        location=tmp_path,
        entry_points=(host_ep,),
    )
    core_dist = _FakeDistribution(
        name="sase-core-rs",
        version="1.2.3",
        location=tmp_path,
    )
    plugin_dist = _FakeDistribution(
        name="sase-foo",
        version="0.1.0",
        location=tmp_path,
    )
    monkeypatch.setattr(
        installed_module.importlib.metadata,
        "distributions",
        lambda: [host_dist, core_dist, plugin_dist],
    )

    assert _installed_plugin_distributions(receipt_plugins_fn=lambda: ()) == (
        "sase-foo",
    )
    assert any_plugins_installed(receipt_plugins_fn=lambda: ()) is True
