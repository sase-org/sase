"""sase's TUI PNG visual snapshots for operator + search previews."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import mount_prompt_bar
from tests.ace.tui.visual._ace_prompt_png_snapshot_prompts import SEARCH_PROMPT
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_prompt_search_operator_delete_preview_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-dark"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, SEARCH_PROMPT)

        text_area = bar.active_text_area()
        text_area.cursor_location = (0, 6)
        await page.press("escape", "d", "slash", "f", "i", "n", "a", "l")
        await wait_for_state(
            page,
            lambda: (
                text_area._search_active
                and text_area._search_query == "final"
                and text_area._search_operator is not None
                and bar._search_command_visible
            ),
            description="active d/final operator search preview",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_search_operator_delete_preview_120x40",
            title="ACE prompt input - operator delete to match preview",
        )


async def test_prompt_search_operator_yank_reverse_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, SEARCH_PROMPT)

        text_area = bar.active_text_area()
        last_row = text_area.document.line_count - 1
        text_area.cursor_location = (
            last_row,
            len(text_area.document.get_line(last_row)),
        )
        await page.press("escape", "y", "question_mark", "a", "l", "p", "h", "a")
        await wait_for_state(
            page,
            lambda: (
                text_area._search_active
                and text_area._search_query == "alpha"
                and text_area._search_operator is not None
                and bar._search_command_visible
            ),
            description="active y?alpha operator search preview",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_search_operator_yank_reverse_light_120x40",
            title="ACE prompt input - operator yank back to match preview",
        )
