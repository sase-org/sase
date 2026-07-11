"""Fresh editable-root evidence from the Updates-tab loader."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sase.ace.tui.modals import plugins_browser_loading as loading
from sase.plugins.latest import LatestInfo
from sase.uv_tool.versions import CorePackageVersion, CoreVersions
from tests.ace.tui._plugins_browser_pane_helpers import _catalog


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
