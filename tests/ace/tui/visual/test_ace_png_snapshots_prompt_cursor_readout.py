"""ACE TUI PNG visual snapshots for the prompt cursor line/column readout."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import mount_prompt_bar
from tests.ace.tui.visual._ace_prompt_png_snapshot_prompts import (
    CURSOR_READOUT_SOLO_PROMPT,
    CURSOR_READOUT_STACK_PROMPT,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_prompt_cursor_readout_solo_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, CURSOR_READOUT_SOLO_PROMPT)
        text_area = bar.active_text_area()
        text_area.cursor_location = (2, 10)
        text_area._enter_normal_mode()
        await wait_for_state(
            page,
            lambda: (
                text_area._vim_mode == "normal"
                and text_area.cursor_location == (2, 10)
                and text_area.has_focus
            ),
            description="NORMAL-mode prompt cursor mid-document for readout snapshot",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_cursor_readout_solo_120x40",
            title="ACE prompt input — cursor readout mid-document",
        )


async def test_prompt_cursor_readout_stack_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, CURSOR_READOUT_STACK_PROMPT)

        items = bar._stack.items
        pane_0 = page.app.query_one(f"#{bar._pane_id(items[0])}", PromptTextArea)
        pane_1 = page.app.query_one(f"#{bar._pane_id(items[1])}", PromptTextArea)
        pane_0.cursor_location = (0, 5)
        pane_1.cursor_location = (1, 10)
        await wait_for_state(
            page,
            lambda: (
                pane_0.cursor_location == (0, 5) and pane_1.cursor_location == (1, 10)
            ),
            description="parked panes carry distinct cursor positions",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_cursor_readout_stack_120x40",
            title="ACE prompt stack — cursor readout on every rule",
        )
