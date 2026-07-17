"""Fresh editable-root evidence from the Updates-tab loader."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sase.ace.tui.modals import plugins_browser_loading as loading
from sase.plugins.latest import LatestInfo
from sase.uv_tool.versions import CorePackageVersion, CoreVersions
from tests.ace.tui._plugins_browser_pane_helpers import _catalog, _core_versions


def test_fresh_editable_roots_include_only_successful_online_checks() -> None:
    shared = str(Path("/repo/shared").resolve(strict=False))
    plugin = str(Path("/repo/plugin").resolve(strict=False))
    core_versions = CoreVersions(
        packages=(
            CorePackageVersion(
                name="sase",
                distribution_name="sase",
                installed_version="0.5.0",
                install_type="editable",
                latest_state="current",
                git_root="/repo/shared",
            ),
            CorePackageVersion(
                name="sase-core",
                distribution_name="sase-core-rs",
                installed_version="0.3.0",
                install_type="editable",
                latest_state="fetch_failed",
                git_root="/repo/failed-core",
            ),
            CorePackageVersion(
                name="detached",
                distribution_name="detached",
                installed_version="0.1.0",
                install_type="editable",
                latest_state="detached",
                git_root="/repo/detached-core",
            ),
            CorePackageVersion(
                name="no-upstream",
                distribution_name="no-upstream",
                installed_version="0.1.0",
                install_type="editable",
                latest_state="no_upstream",
                git_root="/repo/no-upstream-core",
            ),
            CorePackageVersion(
                name="wheel",
                distribution_name="wheel",
                installed_version="0.1.0",
                install_type="wheel",
                latest_state="current",
                git_root="/repo/wheel-core",
            ),
        )
    )
    catalog = _catalog()
    states = {
        "github": LatestInfo(
            checked=True,
            source="editable",
            install_type="editable",
            state="dirty",
            git_root="/repo/shared",
        ),
        "telegram": LatestInfo(
            checked=True,
            source="editable",
            install_type="editable",
            state="update_available",
            git_root="/repo/plugin",
        ),
        "nvim": LatestInfo(
            checked=True,
            source="editable",
            install_type="editable",
            state="offline",
            git_root="/repo/offline-plugin",
        ),
        "acme": LatestInfo(
            checked=True,
            source="editable",
            install_type="editable",
            state="unavailable",
            git_root="/repo/unavailable-plugin",
        ),
    }
    catalog = replace(
        catalog,
        entries=tuple(
            replace(entry, latest=states[entry.name]) for entry in catalog.entries
        ),
    )

    assert loading._fresh_editable_roots(core_versions, catalog) == frozenset(
        {shared, plugin}
    )


def test_online_panel_load_writes_shared_update_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = _core_versions(core_latest="1.5.0")
    catalog = _catalog()
    written = []
    monkeypatch.setattr(loading, "probe_uv_tool", lambda: None)
    monkeypatch.setattr(loading, "load_merged_config", dict)
    monkeypatch.setattr(loading, "config_dev_root", lambda _config: Path("/tmp/dev"))
    monkeypatch.setattr(
        loading,
        "_collect_core_versions_for_pane",
        lambda **_kwargs: versions,
    )
    monkeypatch.setattr(loading, "load_plugin_catalog", lambda **_kwargs: catalog)
    monkeypatch.setattr(
        loading,
        "enrich_with_latest",
        lambda loaded, **_kwargs: loaded,
    )
    monkeypatch.setattr(
        loading,
        "_fetch_core_incoming_commits_for_pane",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        loading,
        "_write_update_status_snapshot",
        written.append,
    )

    result = loading.load_plugins_catalog_for_pane(
        incoming_commits_enabled=False,
        now=123.0,
    )

    assert result.update_status is not None
    assert written == [result.update_status]
    assert [
        (component.display_name, component.role) for component in written[0].components
    ] == [
        ("sase-core", "core"),
        ("github", "plugin"),
    ]
    assert written[0].has_core_update is True


def test_offline_panel_load_does_not_replace_shared_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(loading, "probe_uv_tool", lambda: None)
    monkeypatch.setattr(loading, "load_merged_config", dict)
    monkeypatch.setattr(loading, "config_dev_root", lambda _config: Path("/tmp/dev"))
    monkeypatch.setattr(
        loading,
        "_collect_core_versions_for_pane",
        lambda **_kwargs: _core_versions(),
    )
    monkeypatch.setattr(
        loading,
        "load_plugin_catalog",
        lambda **_kwargs: _catalog(),
    )
    monkeypatch.setattr(
        loading,
        "enrich_with_latest",
        lambda catalog, **_kwargs: catalog,
    )
    monkeypatch.setattr(
        loading,
        "_fetch_core_incoming_commits_for_pane",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        loading,
        "_write_update_status_snapshot",
        lambda _status: pytest.fail("offline loads must not replace the snapshot"),
    )

    result = loading.load_plugins_catalog_for_pane(offline=True, now=123.0)

    assert result.update_status is None
