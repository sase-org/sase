"""Cache-only (network-free) loads for the Updates-tab loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.modals import plugins_browser_loading as loading
from sase.plugins.catalog import PluginCatalogError
from sase.updates import UpdateStatus
from sase.uv_tool.versions import CorePackageVersion, CoreVersions
from tests.ace.tui._plugins_browser_pane_helpers import (
    _agent_cli_statuses,
    _catalog,
    _core_versions,
)


def _patch_cache_only_baseline(
    monkeypatch: pytest.MonkeyPatch,
    *,
    snapshot_checked_at: float | None = 90.0,
) -> dict[str, list[object]]:
    seen: dict[str, list[object]] = {
        "core": [],
        "agent_clis": [],
        "incoming": [],
        "enrich": [],
    }
    monkeypatch.setattr(loading, "probe_uv_tool", lambda: None)
    monkeypatch.setattr(loading, "load_merged_config", dict)
    monkeypatch.setattr(loading, "config_dev_root", lambda _config: Path("/tmp/dev"))
    monkeypatch.setattr(
        loading,
        "_collect_core_versions_for_pane",
        lambda **kwargs: (
            seen["core"].append(kwargs),
            _core_versions(),
        )[1],
    )
    monkeypatch.setattr(
        loading,
        "_collect_agent_clis_for_pane",
        lambda **kwargs: (
            seen["agent_clis"].append(kwargs),
            ((), None, {}),
        )[1],
    )
    monkeypatch.setattr(
        loading,
        "_fetch_core_incoming_commits_for_pane",
        lambda *_args, **kwargs: (
            seen["incoming"].append(kwargs),
            {},
        )[1],
    )
    monkeypatch.setattr(loading, "load_plugin_catalog", lambda **_kwargs: _catalog())
    monkeypatch.setattr(
        loading,
        "enrich_with_latest",
        lambda catalog, **kwargs: (
            seen["enrich"].append(kwargs),
            catalog,
        )[1],
    )
    snapshot = (
        UpdateStatus(checked_at=snapshot_checked_at, components=())
        if snapshot_checked_at is not None
        else None
    )
    monkeypatch.setattr(loading, "_read_update_status_snapshot", lambda: snapshot)
    monkeypatch.setattr(
        loading,
        "_write_update_status_snapshot",
        lambda _status: pytest.fail("cache-only loads must not write the snapshot"),
    )
    return seen


def test_cache_only_load_uses_cache_seams_and_snapshot_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen = _patch_cache_only_baseline(monkeypatch)

    result = loading.load_plugins_catalog_for_pane(
        incoming_commits_enabled=False,
        now=123.0,
        cache_only=True,
    )

    assert result.cache_only is True
    assert result.checked_at == 90.0
    assert result.update_status is None
    assert result.fresh_editable_roots == frozenset()
    assert seen["core"] == [{"cache_only": True}]
    assert seen["agent_clis"] == [
        {"refresh": False, "offline": False, "cache_only": True}
    ]
    assert seen["enrich"] == [{"cache_only": True}]


def test_cache_only_load_without_snapshot_has_unknown_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_only_baseline(monkeypatch, snapshot_checked_at=None)

    result = loading.load_plugins_catalog_for_pane(
        incoming_commits_enabled=False,
        now=123.0,
        cache_only=True,
    )

    assert result.checked_at is None
    assert result.cache_only is True


def test_cache_only_load_missing_catalog_cache_points_at_r(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_cache_only_baseline(monkeypatch)
    monkeypatch.setattr(
        loading,
        "load_plugin_catalog",
        lambda **_kwargs: (_ for _ in ()).throw(
            PluginCatalogError("plugin catalog cache is unavailable in offline mode")
        ),
    )

    result = loading.load_plugins_catalog_for_pane(
        incoming_commits_enabled=False,
        now=123.0,
        cache_only=True,
    )

    assert result.catalog is None
    assert result.error == "No cached plugin catalog yet — press r to refresh."


def test_cache_only_core_incoming_skips_github_specs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.updates import incoming_commits as incoming_mod

    versions = CoreVersions(
        packages=(
            CorePackageVersion(
                name="sase",
                distribution_name="sase",
                installed_version="0.5.0",
                latest_version="0.6.0",
                latest_checked=True,
                update_available=True,
                install_type="wheel",
            ),
        )
    )

    def fail_github(endpoint: str, *, run_fn: object = None) -> dict[str, object]:
        raise AssertionError("cache-only incoming must not hit GitHub")

    monkeypatch.setattr(incoming_mod, "_gh_api_json", fail_github)

    result = loading._fetch_core_incoming_commits_for_pane(
        versions,
        enabled=True,
        limit=7,
        offline=False,
        cache_only=True,
    )

    assert result == {}


def test_network_load_records_checked_at_and_forces_core_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loading, "probe_uv_tool", lambda: None)
    monkeypatch.setattr(loading, "load_merged_config", dict)
    monkeypatch.setattr(loading, "config_dev_root", lambda _config: Path("/tmp/dev"))
    core_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        loading,
        "_collect_core_versions_for_pane",
        lambda **kwargs: (core_calls.append(kwargs), _core_versions())[1],
    )
    monkeypatch.setattr(
        loading,
        "_collect_agent_clis_for_pane",
        lambda **_kwargs: (_agent_cli_statuses(), None, {}),
    )
    monkeypatch.setattr(
        loading,
        "_fetch_core_incoming_commits_for_pane",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(loading, "load_plugin_catalog", lambda **_kwargs: _catalog())
    monkeypatch.setattr(
        loading, "enrich_with_latest", lambda catalog, **_kwargs: catalog
    )
    monkeypatch.setattr(loading, "_read_update_status_snapshot", lambda: None)
    written: list[UpdateStatus] = []
    monkeypatch.setattr(loading, "_write_update_status_snapshot", written.append)

    result = loading.load_plugins_catalog_for_pane(
        incoming_commits_enabled=False,
        now=123.0,
    )

    assert result.cache_only is False
    assert result.checked_at == 123.0
    assert result.update_status is not None
    assert written == [result.update_status]
