"""ACE PNG snapshot for prompt-local word completion."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_word_completion import PROMPT_WORD_COMPLETION_KIND
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


def _candidate(word: str) -> CompletionCandidate:
    return CompletionCandidate(
        display=word,
        insertion=word,
        is_dir=False,
        name=word,
    )


async def _mount_prompt_bar(page: AcePage) -> PromptInputBar:
    await page.app.mount(
        PromptInputBar(
            initial_value="Review and revise the revision before sending the rev",
            id="prompt-input-bar",
        )
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus,
        description="prompt-word prompt-bar focus",
    )
    await wait_for_visual_idle(page)
    return bar


async def test_prompt_word_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page)
        bar.show_file_completions(
            "rev",
            [
                _candidate("Review"),
                _candidate("revise"),
                _candidate("revision"),
            ],
            selected_index=1,
            completion_kind=PROMPT_WORD_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "revision")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_word_completion_panel_120x40",
            title="ACE prompt input — prompt-local word completion",
        )
