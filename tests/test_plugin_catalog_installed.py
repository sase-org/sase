"""Tests for merging the catalog with locally-installed plugin inventory."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.plugins import installed as installed_module
from sase.plugins.installed import (
    InstalledInfo,
    _installed_plugin_distributions,
    any_plugins_installed,
    build_installed_index,
    lookup_installed,
)
from sase.plugins.inventory import (
    PluginInventory,
    _PluginDistributionRecord,
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
    assert any_plugins_installed(candidates_fn=lambda: ()) is False


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

    assert any_plugins_installed(candidates_fn=lambda: (candidate,)) is True
    assert _installed_plugin_distributions(candidates_fn=lambda: (candidate,)) == (
        "sase-github",
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

    assert _installed_plugin_distributions() == ("sase-foo",)
    assert any_plugins_installed() is True
