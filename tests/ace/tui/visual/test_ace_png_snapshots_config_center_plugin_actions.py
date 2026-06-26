"""ACE TUI PNG visual snapshots for Config Center plugin action previews."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals import plugins_browser_pane as pbp
from tests.ace.tui.test_plugins_browser_pane import (
    _catalog,
    _highlight,
    _not_uv_tool,
    _ready_preview,
    _update_ready,
)
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    BROAD_SCREENSHOT_MAX_DIFF_RATIO,
    _PLUGINS_NOW,
    _build_view,
    _config_layers,
    _config_schema,
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


async def test_config_center_plugins_install_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The install confirm-preview modal: exact uv argv + source toggle."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    monkeypatch.setattr(
        pbp, "_plan_install_preview", lambda name, *, offline: _ready_preview(name)
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "nvim")  # a not-installed plugin
        await page.wait_for(lambda _s: pane._highlighted_name() == "nvim")
        pane.action_install()
        await page.expect_modal("PluginActionConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_install_preview_120x40",
            title="ACE SASE Admin Center — Plugins install (confirm preview)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_plugins_not_uv_tool_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-uv-tool install surfaces the unavailable banner; no ``i install``."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    result = pbp._PluginsLoadResult(
        catalog=_catalog(), error=None, now=_PLUGINS_NOW, uv_tool=_not_uv_tool()
    )
    monkeypatch.setattr(pbp, "_load_plugins_catalog", lambda **_kw: result)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        await page.wait_for(lambda _s: pane._detail_name == "github")
        await _wait_for_plugins_detail(page, pane)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_not_uv_tool_120x40",
            title="ACE SASE Admin Center — Plugins tab (install unavailable)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_plugins_update_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The single-plugin update confirm-preview modal: exact uv upgrade argv."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    plan = _update_ready(("github",))
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        _highlight(pane, "github")  # installed + update available
        await page.wait_for(lambda _s: pane._highlighted_name() == "github")
        pane.action_update()
        await page.expect_modal("PluginActionConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_update_preview_120x40",
            title="ACE SASE Admin Center — Plugins update (confirm preview)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_plugins_update_all_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The update-all confirm-preview modal: upgrades every installed plugin."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))
    _patch_plugins_catalog(monkeypatch)
    plan = _update_ready(("github", "telegram"), all_plugins=True)
    monkeypatch.setattr(
        pbp,
        "_plan_update_preview",
        lambda query, *, all_plugins, offline: pbp._UpdatePreview(plan=plan),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_plugins_modal(page)
        pane.action_update_all()
        await page.expect_modal("PluginActionConfirmModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_plugins_update_all_preview_120x40",
            title="ACE SASE Admin Center — Plugins update-all (confirm preview)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
