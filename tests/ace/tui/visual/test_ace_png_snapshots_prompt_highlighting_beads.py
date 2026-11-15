"""sase's TUI PNG visual snapshots for prompt bead-mention highlights."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_bead_mention_fixtures import (
    patch_visual_bead_mentions,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import mount_prompt_bar
from tests.ace.tui.visual._ace_prompt_png_snapshot_prompts import (
    BEAD_MENTION_HIGHLIGHT_PROMPT,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_bead_mention_highlight_dark_120x40",
            "ACE prompt input — bead mention highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_bead_mention_highlight_light_120x40",
            "ACE prompt input — bead mention highlighting, light theme",
        ),
    ],
)
async def test_prompt_bead_mention_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    patch_visual_bead_mentions(monkeypatch, tmp_path)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, BEAD_MENTION_HIGHLIGHT_PROMPT)
        text_area = bar.active_text_area()
        text_area._build_highlight_map()
        await wait_for_visual_idle(page)

        names = [
            name for row in text_area._highlights.values() for *_range, name in row
        ]
        assert "bead.mention.in_progress" in names
        assert "bead.mention.closed" in names

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
