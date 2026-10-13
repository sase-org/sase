"""Shared setup for Projects-pane test modules."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import config_pane as cp
from sase.ace.tui.modals import plugins_browser_pane as pbp
from sase.ace.tui.modals.projects_pane import ProjectCountsLoadResult
from sase.repo_inventory import RepoInventory
from sase.uv_tool.versions import CorePackageVersion, CoreVersions
from sase.workspace_provider.inventory import WorkspaceInventory
from tests.ace.tui.modals.project_management_modal_test_helpers import (
    make_project_record,
)


async def focus_projects_filter(page: AcePage) -> None:
    """Open the Projects tab filter input via the pane's ``/`` binding."""
    await page.press("/")
    await page.wait_for(
        lambda _s: (
            page.app.focused is not None and page.app.focused.id == "projects-filter"
        )
    )


def patch_panes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub every Admin Center pane loader so opening the modal is cheap."""
    config_result = cp._LoadResult(view=None, error=None, token=("tok", 1))
    monkeypatch.setattr(cp, "_load_config_view", lambda **_kw: config_result)
    monkeypatch.setattr(
        "sase.ace.tui.modals.macro_browser_pane.get_all_prompts",
        lambda project=None: {},
    )
    monkeypatch.setattr(
        "sase.macro.loader.get_all_project_local_prompts",
        lambda: {},
    )
    core_versions = CoreVersions(
        packages=(
            CorePackageVersion(
                name="sase",
                distribution_name="sase",
                installed_version="0.5.0",
                latest_version="0.5.0",
                latest_checked=True,
            ),
            CorePackageVersion(
                name="sase-core",
                distribution_name="sase-core-rs",
                installed_version="1.4.2",
                latest_version="1.4.2",
                latest_checked=True,
            ),
        )
    )
    plugins_result = pbp._PluginsLoadResult(
        catalog=None, error="stub", now=0.0, core_versions=core_versions
    )
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: plugins_result)
    monkeypatch.setattr(pbp, "_collect_installed_core_versions", lambda: core_versions)
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.list_project_records",
        lambda *_a, **_kw: [
            make_project_record("alpha", state="enabled"),
            make_project_record("beta", state="enabled"),
        ],
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.collect_project_inventory_counts",
        lambda *_args: ProjectCountsLoadResult({}),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_repo_inventory",
        lambda *_args, **_kwargs: RepoInventory(()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.project_inventory_panes.collect_workspace_inventory",
        lambda *_args, **_kwargs: WorkspaceInventory((), ()),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.resolve_current_project",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.projects_pane.get_known_project_workspaces",
        lambda **_kwargs: {},
    )
