"""ACE PNG snapshots for placeholder completion and prompt highlighting."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.placeholder_completion import (
    PLACEHOLDER_COMPLETION_KIND,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _candidate(text: str) -> CompletionCandidate:
    return CompletionCandidate(
        display=text,
        insertion=text,
        is_dir=False,
        name=text,
    )


async def _mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus,
        description="placeholder prompt-bar focus",
    )
    for text_area in bar.query(PromptTextArea):
        text_area.cursor_blink = False
    await wait_for_visual_idle(page)
    return bar


async def test_placeholder_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(
            page,
            "Reuse <release note> and <release owner>; update <rel",
        )
        bar.show_file_completions(
            "rel",
            [_candidate("release note"), _candidate("release owner")],
            selected_index=0,
            completion_kind=PLACEHOLDER_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "release owner")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "placeholder_completion_panel_120x40",
            title="ACE prompt input — placeholder completion menu",
        )


async def test_placeholder_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        await _mount_prompt_bar(
            page,
            "Update <the release plan>, then validate `<the release plan>`\n"
            "with <the release owner> before sending.",
        )
        await wait_for_svg_contains(page, "the release owner")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "placeholder_highlight_120x40",
            title="ACE prompt input — highlighted placeholders",
        )
