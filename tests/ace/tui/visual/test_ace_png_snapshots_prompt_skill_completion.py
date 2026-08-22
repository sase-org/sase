"""ACE PNG snapshot for a long skill completion that keeps the editor visible."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import mount_prompt_bar
from tests.ace.tui.visual._ace_prompt_png_snapshot_xprompt_fixtures import (
    LONG_SKILL_COMPLETION_ROWS,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_prompt_skill_completion_long_description_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, "/sase_monitor")
        bar.show_file_completions(
            "/sase_monitor",
            LONG_SKILL_COMPLETION_ROWS,
            selected_index=0,
            completion_kind="xprompt",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="long skill completion visibility",
        )
        await wait_for_svg_contains(page, "sase_monitor")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_skill_completion_long_description_120x40",
            title="ACE prompt input — long skill completion keeps the editor visible",
        )
