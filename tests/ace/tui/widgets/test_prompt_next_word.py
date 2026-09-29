"""Pilot tests for the ghost-text next-word chain on Ctrl+T."""

from __future__ import annotations

import time

import pytest
from textual.widgets import Static

from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.core.prompt_prediction_facade import (
    PromptPredictionCorpus,
    PromptPredictionModel,
)
from sase.core.prompt_prediction_wire import (
    PromptPredictionCorpusOptions,
    PromptPredictionModelConfig,
    PromptPredictionRow,
)

from ._completion_helpers import CompletionTestApp


def _corpus_texts() -> list[str]:
    return [
        "Can you help me implement it now",
        "Can you help me implement it today",
        "Can you help me implement it soon",
        "Can you help me implement the plan",
        "Can you help me implement that feature",
    ]


def _compile_model() -> PromptPredictionModel:
    now = int(time.time())
    rows = [
        PromptPredictionRow(text=text, epoch_seconds=now - index * 100, origin="typed")
        for index, text in enumerate(_corpus_texts())
    ]
    corpus = PromptPredictionCorpus.compile(
        rows, PromptPredictionCorpusOptions(now_epoch=now)
    )
    return PromptPredictionModel.compose(
        [(corpus, "history", 1.0)], PromptPredictionModelConfig()
    )


class NextWordTestApp(CompletionTestApp):
    """Harness with a warm prediction model built from a tiny corpus."""

    def __init__(
        self,
        *,
        settings: PromptCompletionSettings | None = None,
        model: PromptPredictionModel | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings or PromptCompletionSettings()
        self.model = model if model is not None else _compile_model()
        self.warm_requests = 0
        self.disabled = False

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings

    def get_prompt_prediction_model(self) -> PromptPredictionModel | None:
        return None if self.disabled else self.model

    def get_prompt_prediction_project(self, _text: str) -> str | None:
        return None

    def prompt_prediction_disabled(self) -> bool:
        return self.disabled

    def disable_prompt_prediction(self) -> None:
        self.disabled = True

    def warm_prompt_prediction(self) -> None:
        self.warm_requests += 1

    def history_prompt_word_deletions(self) -> frozenset[str]:
        return frozenset()


def _bar_hint(bar: PromptInputBar) -> str:
    subtitle = bar.border_subtitle
    return subtitle.plain if hasattr(subtitle, "plain") else str(subtitle)


async def test_arm_after_word_commit_shows_ghost_with_hint() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        assert ta.suggestion == " implement it"
        assert "[^T] word" in _bar_hint(bar)


async def test_ctrl_t_takes_one_word_then_advances_ghost() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        first = ta.text
        await pilot.press("ctrl+t")
        assert ta.text.startswith(first + " implement")
        assert ta._next_word_chain_is_armed() is True
        # Ghost redraws synchronously so it never flickers.
        assert ta._next_word_ghost_visible() is True


async def test_ctrl_f_takes_whole_ghost_and_rearms() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        ghost = ta.suggestion
        assert ghost
        before = ta.text
        await pilot.press("ctrl+f")
        assert ta.text == before + ghost
        assert ta._next_word_chain_is_armed() is True


async def test_alt_f_takes_one_word() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        before = ta.text
        await pilot.press("alt+f")
        assert ta.text == before + " implement"
        assert ta._next_word_chain_is_armed() is True


async def test_type_through_consumes_ghost() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta.suggestion == " implement it"
        await pilot.press("space")
        # Leading space matches the ghost separator and is consumed.
        assert ta.text == "Can you help me "
        assert ta.suggestion == "implement it"


async def test_mismatched_typing_clears_ghost() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        await pilot.press("x")
        assert ta._next_word_ghost_visible() is False


async def test_backspace_and_cursor_move_clear_ghost() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        await pilot.press("left")
        assert ta._next_word_ghost_visible() is False


async def test_esc_then_right_inserts_nothing() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        await pilot.press("escape")
        before = ta.text
        await pilot.press("right")
        assert ta.text == before
        assert ta._next_word_ghost_visible() is False


async def test_explicit_request_without_guess_shows_hint() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("zzz qqq")
        ta.cursor_location = (0, len(ta.text))
        # Arm manually: no gated ghost, but the chain stays armed.
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_chain_is_armed() is True
        await pilot.press("ctrl+t")
        assert "no next-word guess" in _bar_hint(bar)


async def test_cold_model_shows_warming_hint() -> None:
    settings = PromptCompletionSettings()
    app = NextWordTestApp(settings=settings, model=None)
    app.model = None
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is False
        await pilot.press("ctrl+t")
        assert "warming next words" in _bar_hint(bar)
        assert app.warm_requests >= 1


async def test_mid_line_suppresses_ghost() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me here")
        ta.cursor_location = (0, len("Can you help me"))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is False


async def test_soft_completion_blocked_while_ghost_visible() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        assert ta._soft_completion_blocked() is True


async def test_next_word_off_disables_chain() -> None:
    settings = PromptCompletionSettings(next_word="off")
    app = NextWordTestApp(settings=settings)
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_chain_is_armed() is False
        assert ta._predict_next_words("Can you help me") is None


async def test_one_undo_step_per_accept() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        before = ta.text
        await pilot.press("ctrl+t")
        assert ta.text != before
        ta.undo()
        assert ta.text == before


def _auto_app() -> NextWordTestApp:
    return NextWordTestApp(settings=PromptCompletionSettings(next_word="auto"))


async def test_auto_space_shows_ghost_without_separator() -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Can you help me,")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("space")
        await pilot.pause()
        assert ta.text == "Can you help me, "
        assert ta._next_word_ghost_visible() is True
        # The typed space is the separator, so the ghost has none.
        assert not ta.suggestion.startswith(" ")
        assert ta._next_word_chain_is_armed() is True
        assert "[^T] word" in _bar_hint(bar)


async def test_auto_space_after_sentence_end_shows_nothing() -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me.")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("space")
        await pilot.pause()
        assert ta.text == "Can you help me. "
        # Sentence-final punctuation resets the context to ``<s>`` only,
        # which never passes the gate.
        assert ta._next_word_ghost_visible() is False


async def test_auto_space_only_fires_in_auto_mode() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me,")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("space")
        await pilot.pause()
        assert ta.text == "Can you help me, "
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_chain_is_armed() is False


async def test_auto_second_space_shows_nothing() -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me, ")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("space")
        await pilot.pause()
        assert ta.text == "Can you help me,  "
        assert ta._next_word_ghost_visible() is False
