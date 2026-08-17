"""Ctrl+T open and acceptance tests for prompt-history word completion."""

from __future__ import annotations

from textual.content import Content
from textual.widgets import Static

from sase.ace.tui.widgets.history_word_completion import (
    HISTORY_WORD_COMPLETION_KIND,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._history_word_completion_helpers import (
    HistoryCompletionTestApp,
    skip_unrelated_vcs_catalog_warm,  # noqa: F401 (registers the autouse fixture)
)


async def test_ctrl_t_opens_history_words_after_local_miss() -> None:
    app = HistoryCompletionTestApp(["alpine", "alpha"])
    async with app.run_test() as pilot:
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("al")
        ta.cursor_location = (0, 2)

        await pilot.press("ctrl+t")

        assert ta.text == "alp"
        assert ta._completion_kind == HISTORY_WORD_COMPLETION_KIND
        assert [
            candidate.insertion for candidate in ta._file_completion_candidates
        ] == ["alpine", "alpha"]
        panel = bar.query_one("#prompt-completion", Static)
        rendered = panel.render()
        assert isinstance(rendered, Content)
        assert panel.border_title == "history words"
        assert panel.border_subtitle == "[^L] accept  [^D] delete"
        assert "📁" not in rendered.plain
        assert "📄" not in rendered.plain


async def test_short_local_match_does_not_block_history_fallback() -> None:
    app = HistoryCompletionTestApp(["tiger"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("tiny ti")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta.text == "tiny tiger"
        assert ta._file_completion_active is False


async def test_history_ctrl_t_mid_word_matches_goal_example() -> None:
    """The plan's motivating example: ``foo<cursor>baz`` -> ``foobar<cursor> baz``."""
    app = HistoryCompletionTestApp(["foobar"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("foobaz")
        ta.cursor_location = (0, len("foo"))

        await pilot.press("ctrl+t")

        assert ta.text == "foobar baz"
        assert ta.cursor_location == (0, len("foobar"))
        assert ta._file_completion_active is False


async def test_history_single_match_auto_accepts_and_preserves_suffix() -> None:
    app = HistoryCompletionTestApp(["publish"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("pubZZZ")
        ta.cursor_location = (0, len("pub"))

        await pilot.press("ctrl+t")

        assert ta.text == "publish ZZZ"
        assert ta.cursor_location == (0, len("publish"))
        assert ta._file_completion_active is False


async def test_history_hyphenated_prefix_auto_accepts_from_prompt_history() -> None:
    app = HistoryCompletionTestApp(["bob-mac-capture"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("bob-ma")
        ta.cursor_location = (0, len("bob-ma"))

        await pilot.press("ctrl+t")

        assert ta.text == "bob-mac-capture"
        assert ta._file_completion_active is False


async def test_history_hyphenated_acceptance_preserves_right_hand_suffix() -> None:
    app = HistoryCompletionTestApp(["bob-mac-capture"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("bob-maZZZ")
        ta.cursor_location = (0, len("bob-ma"))

        await pilot.press("ctrl+t")

        assert ta.text == "bob-mac-capture ZZZ"
        assert ta.cursor_location == (0, len("bob-mac-capture"))
        assert ta._file_completion_active is False


async def test_history_navigation_enter_accept_preserves_suffix() -> None:
    app = HistoryCompletionTestApp(["review", "revise"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("revZZZ")
        ta.cursor_location = (0, len("rev"))

        await pilot.press("ctrl+t", "down", "enter")

        assert ta.text == "revise ZZZ"
        assert ta.cursor_location == (0, len("revise"))
        assert ta._file_completion_active is False


async def test_history_navigation_ctrl_l_accept_preserves_suffix() -> None:
    app = HistoryCompletionTestApp(["review", "revise"])
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("revZZZ")
        ta.cursor_location = (0, len("rev"))

        await pilot.press("ctrl+t", "ctrl+l")

        assert ta.text == "review ZZZ"
        assert ta.cursor_location == (0, len("review"))
        assert ta._file_completion_active is False
