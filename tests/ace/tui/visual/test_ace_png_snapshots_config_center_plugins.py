"""ACE TUI PNG visual snapshots for Config Center Plugins tab list states."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.plugins_browser_pane import PluginsBrowserPane
from sase.plugins.catalog import PluginCatalog
from sase.plugins.installed import InstalledInfo
from sase.plugins.latest import LatestInfo
from tests.ace.tui.test_plugins_browser_pane import _entry
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    BROAD_SCREENSHOT_MAX_DIFF_RATIO,
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
            title="ACE SASE Admin Center — Plugins tab (list + built-in detail)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
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
            title="ACE SASE Admin Center — Plugins tab (community warning + detail)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
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
        topics=("sase-plugin", "sync", "integration"),
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
            title="ACE SASE Admin Center — Plugins tab (long description wraps)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
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
            title="ACE SASE Admin Center — Plugins tab (offline badge)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
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
            title="ACE SASE Admin Center — Plugins tab (verbose rows)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
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
            title="ACE SASE Admin Center — Plugins tab (empty catalog)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
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
        await _open_modal(page, "plugins")

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_loading_120x40",
            title="ACE SASE Admin Center — Plugins tab (loading)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
