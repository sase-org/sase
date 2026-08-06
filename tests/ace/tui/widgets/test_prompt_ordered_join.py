"""Prompt ordered-list NORMAL-mode J (join lines) editing coverage."""

from __future__ import annotations

from sase.ace.testing import PromptPage, VimEditorPage


async def test_prompt_join_strips_ordered_marker_on_nonblank_fold() -> None:
    """J drops a folded-in ordered marker, mirroring the hyphen bullet rule."""
    async with PromptPage("hello\n1. world") as page:
        await page.press("J")
        assert page.text == "hello world"


async def test_prompt_join_keeps_ordered_marker_when_folding_onto_a_blank_line() -> (
    None
):
    """Pulling a line onto a blank one folds nothing, so the marker survives."""
    async with PromptPage("1. one\n\n2. two", cursor=(1, 0)) as page:
        await page.press("J")
        assert page.text == "1. one\n2. two"


async def test_prompt_join_drops_marker_and_renumbers_the_run() -> None:
    """Dropping ``2.`` leaves ``3.`` to renumber down to ``2.``."""
    async with PromptPage("1. one\n2. two\n3. three", cursor=(0, 3)) as page:
        await page.press("J")
        assert page.text == "1. one two\n2. three"


async def test_prompt_join_renumbers_the_run_across_a_blank_line() -> None:
    """Renumbering reaches a loose run's next item across a blank line."""
    async with PromptPage("1. one\n2. two\n\n3. three", cursor=(0, 3)) as page:
        await page.press("J")
        assert page.text == "1. one two\n\n2. three"


async def test_prompt_join_strips_marker_with_no_preceding_item_to_renumber() -> None:
    """With no preceding ordered item, the marker still drops but nothing renumbers."""
    async with PromptPage("hello\n1. a\n2. b", cursor=(0, 3)) as page:
        await page.press("J")
        assert page.text == "hello a\n2. b"


async def test_prompt_join_with_count_renumbers_once_against_the_final_text() -> None:
    """A counted J drops every folded marker and renumbers once, not per fold."""
    async with PromptPage("1. a\n2. b\n3. c\n4. d\n5. e", cursor=(0, 3)) as page:
        await page.press("4", "J")
        assert page.text == "1. a b c d\n2. e"


async def test_prompt_join_drops_marker_and_renumbers_in_one_undo_checkpoint() -> None:
    """The fold and its renumbering share one edit, so one ``u`` reverts both."""
    text = "1. one\n2. two\n3. three"
    async with PromptPage(text, cursor=(0, 3)) as page:
        await page.press("J")
        assert page.text == "1. one two\n2. three"

        await page.press("u")
        assert page.text == text


async def test_bare_vim_text_area_join_leaves_ordered_marker_verbatim() -> None:
    """A bare (non-prompt) editor keeps vanilla vim J, marker untouched."""
    async with VimEditorPage("1. a\n2. b", cursor=(0, 0)) as page:
        await page.press("J")
        assert page.text == "1. a 2. b"
