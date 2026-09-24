"""sase's TUI PNG visual snapshots for prompt search and misspelling highlights."""

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
from tests.ace.tui.visual._ace_prompt_png_snapshot_prompts import (
    MISSPELLING_HIGHLIGHT_PROMPT,
    SEARCH_PROMPT,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_prompt_search_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, SEARCH_PROMPT)

        await page.press("escape", "slash", "a", "l", "p", "h", "a")
        text_area = bar.active_text_area()
        await wait_for_state(
            page,
            lambda: (
                text_area._search_active
                and text_area._search_query == "alpha"
                and bar._search_command_visible
            ),
            description="active alpha prompt search and highlights",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_search_highlight_120x40",
            title="ACE prompt input - active search highlight",
        )


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_search_count_pill_dark_120x40",
            "ACE prompt input - committed search count pill, dark theme",
        ),
        (
            "textual-light",
            "prompt_search_count_pill_light_120x40",
            "ACE prompt input - committed search count pill, light theme",
        ),
        (
            "flexoki",
            "prompt_search_count_pill_flexoki_120x40",
            "ACE prompt input - committed search count pill, flexoki theme",
        ),
    ],
)
async def test_prompt_search_count_pill_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, SEARCH_PROMPT)

        await page.press("escape", "slash", "a", "l", "p", "h", "a", "enter", "n")
        text_area = bar.active_text_area()
        await wait_for_state(
            page,
            lambda: (
                not text_area._search_active
                and text_area._search_readout is not None
                and text_area._search_readout.ordinal == 2
            ),
            description="committed alpha prompt search count pill",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_misspelling_highlight_dark_120x40",
            "ACE prompt input — sticky misspelling highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_misspelling_highlight_light_120x40",
            "ACE prompt input — sticky misspelling highlighting, light theme",
        ),
    ],
)
async def test_prompt_misspelling_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)
    # Seed the durable store directly, the same way a prior ``K`` session
    # would have left it, so the app's normal cold-start warm discovers it.
    from sase.history.prompt_misspellings import record_misspelling

    record_misspelling("recieve")
    record_misspelling("reciept")

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, MISSPELLING_HIGHLIGHT_PROMPT)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
