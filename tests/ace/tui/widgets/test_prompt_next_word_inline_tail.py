"""Pilot tests for before-closer inline ghosts and the ghost display layer."""

from __future__ import annotations

import pytest
from textual.app import ComposeResult
from textual.widgets.text_area import Selection

from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui.widgets.test_prompt_next_word import NextWordTestApp, _bar_hint

from ._completion_helpers import CompletionTestApp


def _auto_app() -> NextWordTestApp:
    from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings

    return NextWordTestApp(settings=PromptCompletionSettings(next_word="auto"))


def _confident_result(words: list[str]):  # type: ignore[no-untyped-def]
    from sase.core.prompt_prediction_wire import PromptPredictionResult

    return PromptPredictionResult(
        schema_version=1,
        blocked_reason=None,
        context_words=["see", "the"],
        confident=True,
        ghost=list(words),
        candidates=[],
    )


def _patch_confident(
    monkeypatch: pytest.MonkeyPatch, area: PromptTextArea, words: list[str]
) -> None:
    result = _confident_result(words)
    monkeypatch.setattr(area, "_predict_next_words", lambda *args, **kwargs: result)


async def test_tail_ghost_before_closer_shows_hint_immediately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Plan (see the)")
        ta.cursor_location = (0, len(ta.text) - 1)
        _patch_confident(monkeypatch, ta, ["parser"])
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        assert ta.suggestion == " parser"
        # Explicit arms show the hint in the same keystroke.
        assert "[^T] word" in _bar_hint(bar)
        assert "[^L] all" in _bar_hint(bar)


async def test_ctrl_l_accepts_tail_ghost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Plan (see the)")
        ta.cursor_location = (0, len(ta.text) - 1)
        _patch_confident(monkeypatch, ta, ["parser"])
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        await pilot.press("ctrl+l")
        assert ta.text == "Plan (see the parser)"


async def test_right_before_closer_is_plain_motion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Plan (see the)")
        ta.cursor_location = (0, len(ta.text) - 1)
        _patch_confident(monkeypatch, ta, ["parser"])
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        await pilot.press("right")
        # Plain motion steps past ")" instead of taking the ghost.
        assert ta.text == "Plan (see the)"
        assert ta.cursor_location == (0, len(ta.text))
        assert ta._next_word_ghost_visible() is False
        assert ta.suggestion == ""


async def test_right_at_eol_takes_whole_ghost() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        ghost = ta.suggestion
        assert ghost
        before = ta.text
        await pilot.press("right")
        assert ta.text == before + ghost
        assert ta._next_word_chain_is_armed() is True


async def test_typing_space_inside_parens_shows_tail_ghost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Plan (see the)")
        ta.cursor_location = (0, len(ta.text) - 1)
        _patch_confident(monkeypatch, ta, ["parser"])
        await pilot.press("space")
        await pilot.pause()
        assert ta.text == "Plan (see the )"
        assert ta._next_word_ghost_visible() is True
        # The typed space is the separator, so the ghost has none.
        assert ta.suggestion == "parser"
        assert ta._next_word_chain_is_armed() is True
        # Typing-triggered hints wait out the reveal beat.
        assert "[^T] word" not in _bar_hint(bar)
        await pilot.pause(0.6)
        assert "[^T] word" in _bar_hint(bar)


async def test_explicit_ctrl_t_shows_hint_immediately() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Can you help me ")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("ctrl+t")
        assert ta._next_word_ghost_visible() is True
        assert "[^T] word" in _bar_hint(bar)


async def test_selection_suppresses_ghost() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta.selection = Selection((0, 0), (0, 3))
        assert ta._next_word_ghost_allowed() is False
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is False
        ta.selection = Selection.cursor((0, len(ta.text)))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True


class FeedbackNextWordTestApp(NextWordTestApp):
    """Next-word harness mounted in the legacy feedback bar mode."""

    def compose(self) -> ComposeResult:
        yield PromptInputBar(mode="feedback")


async def test_feedback_mode_shows_ghost() -> None:
    app = FeedbackNextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        assert bar._mode == "feedback"
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        assert "[^T] word" in _bar_hint(bar)


async def test_tail_ghost_keeps_trailing_highlight_spans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        text = "Plan (see the)"
        ta.load_text(text)
        tail_start = len(text) - 1
        ta.cursor_location = (0, tail_start)
        ta._set_search_highlights(((tail_start, tail_start + 1),), refresh=False)
        _patch_confident(monkeypatch, ta, ["parser"])
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        assert ta.suggestion == " parser"
        # The highlight map still covers the tail past the ghost splice.
        assert ta._search_match_spans == ((tail_start, tail_start + 1),)
        await pilot.press("ctrl+l")
        assert ta.text == "Plan (see the parser)"


class StackedNextWordTestApp(NextWordTestApp):
    """Next-word harness with two stacked prompt panes."""

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_panes=["Can you help me", "second pane"])


async def test_multi_pane_ghost_isolation() -> None:
    app = StackedNextWordTestApp()
    async with app.run_test() as pilot:
        panes = list(app.query(PromptTextArea))
        assert len(panes) == 2
        first, second = panes
        first.cursor_location = (0, len(first.text))
        first._arm_next_word_chain()
        await pilot.pause()
        assert first._next_word_ghost_visible() is True
        assert second._next_word_ghost_visible() is False
        assert second._next_word_chain is None


async def test_typed_word_char_stays_silent_in_auto() -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me imple")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("m")
        await pilot.pause()
        # Mid-word completion arrives in the mid-word phase.
        assert ta.text == "Can you help me implem"
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_chain is None or not ta._next_word_chain_is_armed()
