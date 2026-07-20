"""ACE TUI PNG visual snapshots for Config Center Updates tab list states."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.plugins.catalog import PluginCatalog
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from tests.ace.tui.test_plugins_browser_pane import _all_current_catalog
from tests.ace.tui.test_plugins_browser_pane import _entry
from tests.ace.tui.test_plugins_browser_pane import _core_versions
from tests.ace.tui.test_plugins_browser_pane import _uv_tool
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _PLUGINS_NOW,
    _build_view,
    _config_layers,
    _config_schema,
    _open_modal,
    _open_plugins_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_xprompt_sources,
    _wait_for_plugins_detail,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_config_center_plugins_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Populated list + the built-in plugin's ``show``-equivalent detail panel."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        await page.wait_for(lambda _s: pane._detail_name == "github")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_tab_120x40",
            title="ACE SASE Admin Center — Updates tab (list + built-in detail)",
        )


async def test_config_center_updates_core_update_available_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Core panel highlights an available SASE update above the plugin browser."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(
        monkeypatch,
        core_versions=_core_versions(sase_latest="0.6.0"),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        pane._switch_to_subtab("core")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_core_update_available_120x40",
            title="ACE SASE Admin Center — Updates tab (core update available)",
        )


async def test_config_center_updates_all_current_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-current banner renders above the SASE Core panel."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(
        monkeypatch,
        catalog=_all_current_catalog(),
        uv_tool=_uv_tool(),
        agent_cli_statuses=(),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        pane._switch_to_subtab("core")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_updates_all_current_120x40",
            title="ACE SASE Admin Center — Updates tab (all current)",
        )


async def test_config_center_agent_clis_marked_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent CLIs master/detail browser shows provider colors and update marks."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        pane._switch_to_subtab("agent-clis")
        await page.wait_for(lambda _s: pane._agent_cli_detail_name == "claude")
        pane.action_toggle_mark()
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_agent_clis_marked_120x40",
            title="ACE SASE Admin Center — Agent CLIs sub-tab (marked update)",
        )


async def test_config_center_agent_clis_update_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Agent CLI update confirmation previews exact commands and all skips."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        pane._switch_to_subtab("agent-clis")
        pane.action_update_agent_clis()
        await page.expect_modal("PluginActionConfirmModal")

        ace_png_visual.assert_page_png(
            page,
            "config_center_agent_clis_update_preview_120x40",
            title="ACE SASE Admin Center — Agent CLI update preview",
        )


async def test_config_center_plugins_dev_update_available_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Editable installs show current/latest dev versions and update state."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    github = _entry(
        "github",
        owner="sase-org",
        description="GitHub VCS and workspace provider.",
        installed=InstalledInfo(installed=True, version="0.5.0+12.gabc123def"),
        latest=LatestInfo(
            checked=True,
            version="0.5.0+14.gdef456abc",
            source="editable",
            install_type="editable",
            current_version="0.5.0+12.gabc123def",
            update_available=True,
            state="update_available",
            reason="behind upstream by 2 commit(s)",
            git_root="/repo/sase-github",
            upstream_ref="origin/main",
        ),
    )
    catalog = PluginCatalog(
        fetched_at=_PLUGINS_NOW,
        entries=(github,),
        from_cache=True,
        stale=False,
    )
    _patch_plugins_catalog(monkeypatch, catalog=catalog)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        await page.wait_for(lambda _s: pane._detail_name == "github")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_dev_update_available_120x40",
            title="ACE SASE Admin Center — Updates tab (dev update available)",
        )


async def test_config_center_plugins_community_detail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A highlighted community plugin leads its detail with the warning panel."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        # Walk down to the lone community plugin (acme).
        pane.action_next_option()
        pane.action_next_option()
        pane.action_next_option()
        await page.wait_for(lambda _s: pane._detail_name == "acme")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_community_detail_120x40",
            title="ACE SASE Admin Center — Updates tab (community warning + detail)",
        )


async def test_config_center_plugins_long_description_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A long plugin description wraps cleanly in the detail panel."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    long_description = (
        "A comprehensive integration that synchronizes issues, pull requests, "
        "CI status, deployment events, and release notes across multiple forges, "
        "then mirrors them into SASE ChangeSpecs with configurable field "
        "mappings, automatic retries, and rate-limit-aware exponential backoff."
    )
    megasync = _entry(
        "megasync",
        owner="sase-org",
        description=long_description,
        installed=InstalledInfo(installed=True, version="1.0.0"),
        latest=LatestInfo(checked=True, version="1.0.0", source="index"),
        topics=("sase--plugin", "sync", "integration"),
    )
    catalog = PluginCatalog(
        fetched_at=_PLUGINS_NOW,
        entries=(megasync,),
        from_cache=True,
        stale=False,
    )
    _patch_plugins_catalog(monkeypatch, catalog=catalog)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        await page.wait_for(lambda _s: pane._detail_name == "megasync")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_long_description_120x40",
            title="ACE SASE Admin Center — Updates tab (long description wraps)",
        )


async def test_config_center_plugins_offline_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Offline toggle surfaces the header OFFLINE badge; detail still renders."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        pane.action_toggle_offline()
        await page.wait_for(lambda _s: pane._offline and not pane._loading)
        await page.wait_for(lambda _s: pane._detail_name == "github")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_offline_120x40",
            title="ACE SASE Admin Center — Updates tab (offline badge)",
        )


async def test_config_center_plugins_verbose_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verbose toggle adds the stars / updated columns to the list rows."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        pane.action_toggle_verbose()
        await page.wait_for(
            lambda _s: any(
                "★" in pane._row_text(entry).plain
                for _, _, entries in pane._grouped
                for entry in entries
            )
        )
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_verbose_120x40",
            title="ACE SASE Admin Center — Updates tab (verbose rows)",
        )


async def test_config_center_plugins_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty catalog shows the no-plugins placeholder."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    empty = PluginCatalog(
        fetched_at=_PLUGINS_NOW, entries=(), from_cache=True, stale=False
    )
    _patch_plugins_catalog(monkeypatch, catalog=empty)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_plugins_modal(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_empty_120x40",
            title="ACE SASE Admin Center — Updates tab (empty catalog)",
        )


async def test_config_center_plugins_loading_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Suppressing the worker keeps the pane in its initial loading state."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    monkeypatch.setattr(
        PluginsBrowserPane, "_start_load", lambda self, *, force=False: None
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_modal(page, "updates")

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_loading_120x40",
            title="ACE SASE Admin Center — Updates tab (loading)",
        )
