"""ACE PNG snapshot for prompt-history word completion."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions._startup_history_words import StartupHistoryWordsMixin
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
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
            initial_value="Summarize the recent repository rev",
            id="prompt-input-bar",
        )
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus,
        description="history-word prompt-bar focus",
    )
    await wait_for_visual_idle(page)
    return bar


async def test_history_word_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        StartupHistoryWordsMixin,
        "warm_history_prompt_words",
        lambda _self: None,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page)
        bar.show_file_completions(
            "rev",
            [
                _candidate("reviewed"),
                _candidate("revision"),
                _candidate("revalidate"),
            ],
            selected_index=0,
            completion_kind=HISTORY_WORD_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "history words")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "history_word_completion_panel_120x40",
            title="ACE prompt input — prompt-history word completion",
        )
