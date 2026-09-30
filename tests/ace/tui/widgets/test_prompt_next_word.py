"""Pilot tests for the ghost-text next-word chain on Ctrl+T."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from textual.widgets import Static

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.next_word_completion import (
    NEXT_WORD_NO_GUESS_RECENT_FILES_HINT,
)
from sase.ace.tui.widgets.next_word_menu import NEXT_WORD_COMPLETION_KIND
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.core.prompt_prediction_facade import (
    PromptPredictionCorpus,
    PromptPredictionModel,
)
from sase.core.prompt_prediction_wire import (
    PromptPredictionCandidate,
    PromptPredictionCorpusOptions,
    PromptPredictionModelConfig,
    PromptPredictionRequest,
    PromptPredictionResult,
    PromptPredictionRow,
)

from ._completion_helpers import CompletionTestApp


def _corpus_texts() -> list[str]:
    return [
        "Can you help me implement it now",
        "Can you help me implement it today",
        "Can you help me implement it soon",
        "Can you help me implement it later",
        "Can you help me implement it quickly",
        "Can you help me implement it cleanly",
        "Can you help me implement it safely",
        "Can you help me implement it tomorrow",
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


async def test_ghost_suppressed_inside_jinja_tag() -> None:
    app = NextWordTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("{{ ")
        ta.cursor_location = (0, len(ta.text))
        assert ta._next_word_ghost_allowed() is False


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
        assert ta.suggestion == ""


async def test_stale_ghost_clears_textual_suggestion() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        # Backspace invalidates the anchor: the stale Textual suggestion
        # must clear so no ghost is drawn or inserted.
        await pilot.press("backspace")
        assert ta._next_word_ghost_visible() is False
        assert ta.suggestion == ""
        # Re-arm, then Home: cursor leaves the anchor row end.
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        await pilot.press("home")
        assert ta._next_word_ghost_visible() is False
        assert ta.suggestion == ""


async def test_left_then_right_is_plain_cursor_move() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        await pilot.press("left")
        assert ta.suggestion == ""
        before = ta.text
        await pilot.press("right")
        assert ta.text == before
        assert ta.suggestion == ""
        assert ta._next_word_ghost_visible() is False


async def test_home_then_ctrl_f_inserts_nothing() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        await pilot.press("home")
        assert ta.suggestion == ""
        before = ta.text
        await pilot.press("ctrl+f")
        assert ta.text == before
        assert ta.suggestion == ""
        assert ta._next_word_ghost_visible() is False


async def test_undo_and_redo_clear_stale_ghost() -> None:
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        before = ta.text
        await pilot.press("ctrl+t")
        assert ta.text != before
        ta.undo()
        await pilot.pause()
        assert ta.text == before
        assert ta.suggestion == ""
        assert ta._next_word_ghost_visible() is False
        ta.redo()
        await pilot.pause()
        assert ta.suggestion == ""
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


def _record_predict_limits(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    limits: list[int] = []
    original = PromptPredictionModel.predict

    def recording_predict(
        self: PromptPredictionModel, request: PromptPredictionRequest
    ) -> PromptPredictionResult:
        limits.append(request.limit)
        return original(self, request)

    monkeypatch.setattr(PromptPredictionModel, "predict", recording_predict)
    return limits


async def test_arm_requests_no_menu_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    limits = _record_predict_limits(monkeypatch)
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        # The ghost and gate never read menu rows, so arming skips them.
        assert ta.suggestion == " implement it"
        assert limits and set(limits) == {0}


async def test_auto_space_requests_no_menu_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    limits = _record_predict_limits(monkeypatch)
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me,")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("space")
        await pilot.pause()
        assert ta._next_word_ghost_visible() is True
        assert limits and set(limits) == {0}


async def test_boundary_ctrl_t_with_confident_corpus_shows_ghost() -> None:
    """A whitespace ``Ctrl+T`` runs the next-word request, not file history."""
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Can you help me ")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta._next_word_chain_is_armed() is True
        assert ta._next_word_ghost_visible() is True
        assert ta._completion_kind != "file_history"
        assert "[^T] word" in _bar_hint(bar)


async def test_boundary_ctrl_t_with_weak_corpus_opens_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-confident boundary guess opens the ``next_word`` menu."""
    weak = PromptPredictionResult(
        schema_version=1,
        blocked_reason=None,
        context_words=["help", "me"],
        confident=False,
        ghost=[],
        candidates=[
            PromptPredictionCandidate(
                word="implement",
                key="implement",
                score=0.4,
                probability=0.4,
                support=2,
                order=2,
                continuation=["it"],
            )
        ],
    )
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me ")
        ta.cursor_location = (0, len(ta.text))
        monkeypatch.setattr(ta, "_predict_next_words", lambda *args, **kwargs: weak)
        await pilot.press("ctrl+t")

        assert ta._next_word_chain_is_armed() is True
        assert ta._file_completion_active is True
        assert ta._completion_kind == NEXT_WORD_COMPLETION_KIND


async def test_boundary_ctrl_t_without_guess_teaches_recent_files() -> None:
    """A guess-free boundary ``Ctrl+T`` names the moved ``Ctrl+G r`` menu."""
    app = NextWordTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("zzz qqq ")
        ta.cursor_location = (0, len(ta.text))

        await pilot.press("ctrl+t")

        assert ta._next_word_chain_is_armed() is True
        assert ta._file_completion_active is False
        assert NEXT_WORD_NO_GUESS_RECENT_FILES_HINT in _bar_hint(bar)


async def test_boundary_ctrl_t_off_opens_file_history() -> None:
    """With next-word off, a whitespace ``Ctrl+T`` keeps file history."""
    history = CompletionCandidate(
        display="docs/readme.md",
        insertion="docs/readme.md",
        is_dir=False,
        name="docs/readme.md",
    )
    app = NextWordTestApp(settings=PromptCompletionSettings(next_word="off"))
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("alpha ")
        ta.cursor_location = (0, len(ta.text))

        with patch(
            "sase.ace.tui.widgets._file_completion_open."
            "build_file_history_completion_candidates",
            return_value=([history], ""),
        ):
            await pilot.press("ctrl+t")

        assert ta._completion_kind == "file_history"
        assert ta._file_completion_candidates == [history]
