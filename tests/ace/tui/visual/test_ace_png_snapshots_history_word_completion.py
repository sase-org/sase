"""ACE PNG snapshot for prompt-history word completion."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions._startup_history_words import StartupHistoryWordsMixin
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
    HistoryWordCompletionMetadata,
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


def _candidate(
    word: str,
    *,
    reason: str,
    score: float,
    related_to: str = "",
    use_count: int = 0,
    age_seconds: float = 0.0,
    relation: float = 0.0,
    recency: float = 0.0,
    frequency: float = 0.0,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=word,
        insertion=word,
        is_dir=False,
        name=word,
        metadata=HistoryWordCompletionMetadata(
            reason=reason,
            related_to=related_to,
            use_count=use_count,
            age_seconds=age_seconds,
            score=score,
            relation=relation,
            recency=recency,
            frequency=frequency,
        ),
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
                _candidate(
                    "reviewed",
                    reason="relation",
                    related_to="commit",
                    use_count=12,
                    age_seconds=18000,
                    score=0.45,
                    relation=0.35,
                    recency=0.05,
                    frequency=0.05,
                ),
                _candidate(
                    "revision",
                    reason="recency",
                    use_count=6,
                    age_seconds=600,
                    score=0.38,
                    relation=0.05,
                    recency=0.28,
                    frequency=0.05,
                ),
                _candidate(
                    "revalidate",
                    reason="frequency",
                    use_count=83,
                    age_seconds=90000,
                    score=0.20,
                    relation=0.0,
                    recency=0.02,
                    frequency=0.18,
                ),
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
