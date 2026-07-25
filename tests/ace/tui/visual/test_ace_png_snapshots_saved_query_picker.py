"""ACE TUI PNG coverage for the saved PR query chooser."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_saved_query_picker_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The picker shows syntax, slot keycaps, active state, and truncation."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"',
        size=(100, 32),
        changespecs=changespecs(),
    ) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        page.app._saved_queries = {
            "1": '"visual"',
            "2": 'PROJECT="sase" AND STATUS="Ready"',
            "4": 'MENTOR="reviewer" OR COMMENT="needs attention"',
            "9": 'PROJECT="sase" AND STATUS="Draft" AND "a deliberately long saved query that demonstrates graceful truncation"',
            "0": "!!! OR @@@",
        }

        await page.press("asterisk")
        await page.expect_modal("SavedQueryPickerModal")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Saved PR Queries")
        assert_page_svg_contains(page, "active")
        assert_page_svg_contains(page, "PROJECT")
        ace_png_visual.assert_page_png(
            page,
            "saved_query_picker_100x32",
            title="ACE saved PR query picker",
        )
