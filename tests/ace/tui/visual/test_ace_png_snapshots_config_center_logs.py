"""ACE TUI PNG visual snapshot coverage for the Admin Center Logs tab."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    _open_logs_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_xprompt_sources,
    _seed_focused_error_log,
    _seed_logs_tab_files,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_config_center_logs_tab_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)
    _seed_logs_tab_files()

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_logs_modal(page)
        assert "Launch & Fan-out Failures" in pane._last_detail_text.plain
        assert "provider exited before writing metadata" in pane._last_detail_text.plain
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_logs_tab_120x40",
            title="ACE SASE Admin Center - Logs tab",
        )


async def test_config_center_logs_tab_toasts_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)
    _seed_logs_tab_files()

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_logs_modal(page)

        await page.press("j")
        await page.wait_for(lambda _s: not pane._loading)
        await page.press("j")
        await page.wait_for(
            lambda _s: (
                not pane._loading and "TUI Toasts" in pane._last_detail_text.plain
            )
        )
        assert "This session" in pane._last_detail_text.plain
        assert "Workflow error" in pane._last_detail_text.plain
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_logs_tab_toasts_120x40",
            title="ACE SASE Admin Center - Logs tab - TUI Toasts",
        )


async def test_config_center_logs_tab_focused_error_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    _patch_xprompt_sources(monkeypatch)
    _patch_plugins_catalog(monkeypatch)
    _patch_config_view(monkeypatch, None)
    target = _seed_focused_error_log()

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        _, pane = await _open_logs_modal(page, log_error_target=target)
        assert "focused on err_260617_143000_7f3a9c" in pane._last_detail_text.plain
        assert "[err_260617_143000_7f3a9c]" in pane._last_detail_text.plain
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "config_center_logs_tab_focused_error_120x40",
            title="ACE SASE Admin Center - Logs tab - focused error",
        )
