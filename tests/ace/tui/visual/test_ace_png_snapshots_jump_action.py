"""ACE TUI PNG visual snapshot for the prompt jump action chooser."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.jump_action_modal import JumpActionModal
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_jump_action_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")

        page.app.push_screen(
            JumpActionModal(
                title="#review",
                kind_label="xprompt",
                icon="#",
                source_display="/home/visual/.config/sase/xprompts/review.md:4:1",
                choices=["tmux", "editor", "load"],
            )
        )
        await page.expect_modal("JumpActionModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "jump_action_modal_120x40",
            title="ACE prompt jump action chooser",
        )
