"""ACE PNG snapshots for the next-word ghost chain."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.next_word_completion import (
    NEXT_WORD_GHOST_HINT,
    NEXT_WORD_NO_GUESS_HINT,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def _mount_prompt_bar(page: AcePage, text: str) -> PromptInputBar:
    await page.app.mount(
        PromptInputBar(
            initial_value=text,
            id="prompt-input-bar",
        )
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus,
        description="next-word prompt-bar focus",
    )
    await wait_for_visual_idle(page)
    return bar


async def test_next_word_ghost_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "Can you help me implement")
        ta = bar.active_text_area()
        ta.cursor_location = (0, len(ta.text))
        ta.suggestion = " it now"
        bar.show_next_word_hint(NEXT_WORD_GHOST_HINT)
        await wait_for_svg_contains(page, "it now")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "next_word_ghost_120x40",
            title="ACE prompt input — next-word ghost",
        )


async def test_next_word_no_guess_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "zzz qqq")
        bar.show_next_word_hint(NEXT_WORD_NO_GUESS_HINT)
        await wait_for_svg_contains(page, "no next-word guess")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "next_word_no_guess_120x40",
            title="ACE prompt input — next-word no guess",
        )
