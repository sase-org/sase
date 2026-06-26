"""ACE TUI PNG visual snapshot coverage for the Admin Center Logs tab."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_config_center_png_snapshot_helpers import (
    BROAD_SCREENSHOT_MAX_DIFF_RATIO,
    _open_logs_modal,
    _patch_config_view,
    _patch_plugins_catalog,
    _patch_xprompt_sources,
    _seed_logs_tab_files,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
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

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        _, pane = await _open_logs_modal(page)
        assert "Launch & Fan-out Failures" in pane._last_detail_text.plain
        assert "provider exited before writing metadata" in pane._last_detail_text.plain

        ace_png_visual.assert_page_png(
            page,
            "config_center_logs_tab_120x40",
            title="ACE SASE Admin Center - Logs tab",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
