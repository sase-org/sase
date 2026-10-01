"""ACE PNG snapshots for the next-word ghost chain."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.next_word_completion import (
    NEXT_WORD_GHOST_HINT,
    NEXT_WORD_NO_GUESS_HINT,
    NEXT_WORD_NO_GUESS_RECENT_FILES_HINT,
)
from sase.ace.tui.widgets.next_word_menu import (
    NEXT_WORD_COMPLETION_KIND,
    NextWordCompletionMetadata,
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


def _menu_candidate(
    word: str,
    *,
    probability: float,
    support: int = 3,
    order: int = 2,
    continuation: list[str] | None = None,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=word,
        insertion=word,
        is_dir=False,
        name=word,
        metadata=NextWordCompletionMetadata(
            score=probability,
            probability=probability,
            support=support,
            order=order,
            continuation=list(continuation or []),
            context_words=["help", "me"],
        ),
    )


_MENU_ROWS = [
    _menu_candidate("implement", probability=0.82, continuation=["it", "now"]),
    _menu_candidate("review", probability=0.55, continuation=["the", "plan"]),
    _menu_candidate("fix", probability=0.3),
]


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


async def test_next_word_no_guess_recent_files_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "zzz qqq ")
        bar.show_next_word_hint(NEXT_WORD_NO_GUESS_RECENT_FILES_HINT)
        await wait_for_svg_contains(page, "recent files")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "next_word_no_guess_recent_files_120x40",
            title="ACE prompt input — next-word no guess with recent files",
        )


async def test_next_word_menu_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "Can you help me")
        bar.show_file_completions(
            "",
            list(_MENU_ROWS),
            selected_index=0,
            completion_kind=NEXT_WORD_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "next word")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "next_word_menu_120x40",
            title="ACE prompt input — next-word menu",
        )


async def test_next_word_menu_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(70, 24)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "Can you help me")
        bar.show_file_completions(
            "",
            list(_MENU_ROWS),
            selected_index=0,
            completion_kind=NEXT_WORD_COMPLETION_KIND,
        )
        await wait_for_svg_contains(page, "next word")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "next_word_menu_narrow_70x24",
            title="ACE prompt input — narrow next-word menu",
        )


async def test_next_word_ghost_before_closer_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "Plan (see the)")
        ta = bar.active_text_area()
        ta.cursor_location = (0, len(ta.text) - 1)
        await wait_for_visual_idle(page)
        ta.suggestion = " parser"
        bar.show_next_word_hint(NEXT_WORD_GHOST_HINT)
        await wait_for_svg_contains(page, "parser")
        await wait_for_svg_contains(page, "word")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "next_word_ghost_before_closer_120x40",
            title="ACE prompt input — next-word ghost before a closer",
        )


async def test_next_word_peek_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(
            page, "Can you help me the parser and make sure the tests pass"
        )
        ta = bar.active_text_area()
        ta.cursor_location = (0, len("Can you help me"))
        # Flush the cursor-move messages before showing: they would
        # otherwise validate a chainless hint away after the show.
        await wait_for_visual_idle(page)
        peek = ta._build_next_word_peek_text(["review", "it", "now"])
        assert peek is not None
        bar.show_next_word_hint(peek)
        await wait_for_svg_contains(page, "⇢")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "next_word_peek_120x40",
            title="ACE prompt input — mid-sentence next-word peek",
        )


async def test_next_word_peek_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches(), size=(70, 24)) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(
            page, "Can you help me the parser and make sure the tests pass"
        )
        ta = bar.active_text_area()
        ta.cursor_location = (0, len("Can you help me"))
        # Flush the cursor-move messages before showing: they would
        # otherwise validate a chainless hint away after the show.
        await wait_for_visual_idle(page)
        peek = ta._build_next_word_peek_text(
            ["review", "the", "implementation", "plan"]
        )
        assert peek is not None
        bar.show_next_word_hint(peek)
        await wait_for_svg_contains(page, "⇢")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "next_word_peek_narrow_70x24",
            title="ACE prompt input — narrow mid-sentence peek",
        )


async def test_next_word_auto_space_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "Can you help me ")
        ta = bar.active_text_area()
        ta.cursor_location = (0, len(ta.text))
        ta.suggestion = "implement"
        bar.show_next_word_hint(NEXT_WORD_GHOST_HINT)
        await wait_for_svg_contains(page, "mplement")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "next_word_auto_space_120x40",
            title="ACE prompt input — next-word auto ghost after space",
        )
