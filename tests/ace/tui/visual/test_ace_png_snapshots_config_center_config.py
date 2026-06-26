"""ACE TUI PNG visual snapshots for Config Center Config/XPrompts tabs.

The Config tab is fed a deterministic fixture inventory by patching
``config_pane._load_config_view`` so no real config files are read.
XPrompts are injected deterministically by patching the pane module's prompt
loaders.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_pane import ConfigPane
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    BROAD_SCREENSHOT_MAX_DIFF_RATIO,
    _build_view,
    _config_layers,
    _config_schema,
    _open_config_modal,
    _open_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_xprompt_sources,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_config_center_config_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_config_modal(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_config_tab_120x40",
            title="ACE SASE Admin Center — Config tab (populated)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_config_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    empty_schema = {"type": "object", "additionalProperties": False, "properties": {}}
    _patch_config_view(monkeypatch, _build_view(empty_schema, _config_layers()))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#config")))
        pane = modal.query_one("#config", ConfigPane)
        await page.wait_for(lambda _s: pane._view is not None and not pane._loading)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_config_empty_120x40",
            title="ACE SASE Admin Center — Config tab (no fields)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_config_loading_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    # Suppress the worker so the pane stays in its initial loading state.
    monkeypatch.setattr(ConfigPane, "_start_load", lambda self, *, force=False: None)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_modal(page, "config")

        ace_png_visual.assert_page_png(
            page,
            "config_center_config_loading_120x40",
            title="ACE SASE Admin Center — Config tab (loading)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_config_long_value_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    view = _build_view(_config_schema(), _config_layers(long_value=True))
    _patch_config_view(monkeypatch, view)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_config_modal(page)
        # Select the field whose effective value is a long query string.
        pane._do_jump("axe.query")
        await page.wait_for(lambda _s: pane._selected_path == "axe.query")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_config_long_value_120x40",
            title="ACE SASE Admin Center — Config tab (long value)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_xprompts_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_modal(page, "xprompts")

        ace_png_visual.assert_page_png(
            page,
            "config_center_xprompts_tab_120x40",
            title="ACE SASE Admin Center — XPrompts tab (migrated browser)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
