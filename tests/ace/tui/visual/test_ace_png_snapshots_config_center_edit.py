"""ACE TUI PNG visual snapshots for Config Center edit modal states."""

from __future__ import annotations

import pytest
from textual.widgets import Input

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_edit_modal import ConfigEditModal
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    BROAD_SCREENSHOT_MAX_DIFF_RATIO,
    _build_view,
    _config_layers,
    _config_schema,
    _open_config_modal,
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


async def _open_edit_modal(page: AcePage, path: str) -> ConfigEditModal:
    """Open the Config edit modal for the leaf at *path*."""
    _, pane = await _open_config_modal(page)
    pane._do_jump(path)
    await page.wait_for(lambda _s: pane._selected_path == path)
    pane.action_edit_field()
    await page.expect_modal("ConfigEditModal")
    modal = page.app.screen
    assert isinstance(modal, ConfigEditModal)
    await page.wait_for(lambda _s: bool(modal.query("#config-edit-scope")))
    return modal


async def test_config_center_edit_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The edit stage: scope selector + typed editor for a string field."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    monkeypatch.setattr("sase.config.edit.get_use_chezmoi", lambda: False)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await _open_edit_modal(page, "timezone")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_edit_modal_120x40",
            title="ACE SASE Admin Center — edit field (scope + editor)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_config_center_edit_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The preview stage: target file, effective merge, validation, and diff."""
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    monkeypatch.setattr("sase.config.edit.get_use_chezmoi", lambda: False)
    _patch_config_view(monkeypatch, _build_view(_config_schema(), _config_layers()))

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        modal = await _open_edit_modal(page, "timezone")
        modal.query_one("#config-edit-input", Input).value = "UTC"
        modal.action_confirm()  # plan -> preview
        await page.wait_for(lambda _s: modal._plan is not None)
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_edit_preview_120x40",
            title="ACE SASE Admin Center — edit preview (diff + validation)",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
