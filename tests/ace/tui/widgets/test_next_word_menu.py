"""Tests for the explicit next-word menu: pure model plus app behavior."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest
from textual.widgets import Static

from sase.ace.tui.widgets._next_word_rows import (
    append_next_word_completion_row,
    next_word_label_width,
)
from sase.ace.tui.widgets._ranking_signal_rows import build_sequence_meter
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.next_word_menu import (
    NEXT_WORD_COMPLETION_KIND,
    NextWordCompletionMetadata,
    build_next_word_completion_candidates,
    next_word_fallback_at_word_end,
    next_word_menu_context,
    next_word_menu_title,
)
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
    PromptPredictionResult,
    PromptPredictionRow,
)
from sase.core.prompt_prediction_wire_prediction import (
    _PromptPredictionSourceShares,
)

from ._completion_helpers import CompletionTestApp


def _candidate(
    word: str,
    *,
    order: int = 2,
    probability: float = 0.8,
    continuation: list[str] | None = None,
) -> PromptPredictionCandidate:
    return PromptPredictionCandidate(
        word=word,
        key=word.casefold(),
        score=probability,
        probability=probability,
        support=3,
        order=order,
        source_shares=_PromptPredictionSourceShares(history=1.0),
        continuation=list(continuation or []),
    )


def _result(
    words: list[PromptPredictionCandidate],
    *,
    context_words: list[str] | None = None,
) -> PromptPredictionResult:
    return PromptPredictionResult(
        schema_version=1,
        blocked_reason=None,
        context_words=list(context_words or ["help", "me"]),
        confident=False,
        ghost=[],
        candidates=words,
    )


def test_kind_constant() -> None:
    assert NEXT_WORD_COMPLETION_KIND == "next_word"


def test_builder_skips_unigram_only_words() -> None:
    result = _result(
        [
            _candidate("implement", order=2),
            _candidate("maybe", order=0),
            _candidate("", order=3),
        ]
    )
    rows = build_next_word_completion_candidates(result)
    assert [row.insertion for row in rows] == ["implement"]
    metadata = rows[0].metadata
    assert isinstance(metadata, NextWordCompletionMetadata)
    assert metadata.order == 2
    assert metadata.context_words == ["help", "me"]


def test_builder_caps_at_limit_and_continuation() -> None:
    result = _result(
        [_candidate(f"word{i}", continuation=["a", "b", "c", "d"]) for i in range(8)]
    )
    rows = build_next_word_completion_candidates(result, limit=5)
    assert len(rows) == 5
    assert rows[0].metadata.continuation == ["a", "b", "c"]


def test_builder_empty_when_no_evidence() -> None:
    assert build_next_word_completion_candidates(_result([])) == []
    assert (
        build_next_word_completion_candidates(_result([_candidate("maybe", order=0)]))
        == []
    )


def test_menu_title_names_last_three_context_words() -> None:
    assert next_word_menu_title(["help", "me"]) == "next word ⇢ “help me”"
    assert (
        next_word_menu_title(["can", "you", "help", "me"])
        == "next word ⇢ “you help me”"
    )
    assert next_word_menu_title([]) == "next word"


def test_menu_context_reads_first_row() -> None:
    rows = build_next_word_completion_candidates(_result([_candidate("implement")]))
    assert next_word_menu_context(rows) == ["help", "me"]
    assert next_word_menu_context([]) == []
    plain = CompletionCandidate(display="x", insertion="x", is_dir=False, name="x")
    assert next_word_menu_context([plain]) == []


def test_fallback_only_at_word_end() -> None:
    assert next_word_fallback_at_word_end("hello", 5) is True
    assert next_word_fallback_at_word_end("hello world", 5) is True
    assert next_word_fallback_at_word_end("hello world", 6) is False
    assert next_word_fallback_at_word_end("hello ", 6) is False
    assert next_word_fallback_at_word_end("", 0) is False


def test_sequence_meter_tracks_probability() -> None:
    assert build_sequence_meter(0.0).plain == "▱▱▱▱▱"
    assert build_sequence_meter(1.0).plain == "▰▰▰▰▰"
    assert build_sequence_meter(0.8).plain == "▰▰▰▰▱"


def test_next_word_row_never_clips_word() -> None:
    from rich.text import Text

    rows = build_next_word_completion_candidates(
        _result([_candidate("implement", continuation=["it", "now"])])
    )
    content = Text()
    append_next_word_completion_row(
        content,
        rows[0],
        True,
        label_width=next_word_label_width(rows[0]),
        inner_width=9,
    )
    # Width 9 fits "  implement" plus border but not the meter: word survives.
    assert content.plain.startswith("implement")

    full = Text()
    append_next_word_completion_row(
        full,
        rows[0],
        True,
        label_width=next_word_label_width(rows[0]),
        inner_width=120,
    )
    assert "implement" in full.plain
    assert "⇢" in full.plain
    assert "it now" in full.plain


def _menu_corpus_texts() -> list[str]:
    return [
        "Can you help me implement it now",
        "Can you help me implement it today",
        "Can you help me implement it soon",
        "Can you help me implement the plan",
        "Can you help me implement that feature",
    ]


def _compile_menu_model() -> PromptPredictionModel:
    now = int(time.time())
    rows = [
        PromptPredictionRow(text=text, epoch_seconds=now - index * 100, origin="typed")
        for index, text in enumerate(_menu_corpus_texts())
    ]
    corpus = PromptPredictionCorpus.compile(
        rows, PromptPredictionCorpusOptions(now_epoch=now)
    )
    return PromptPredictionModel.compose(
        [(corpus, "history", 1.0)], PromptPredictionModelConfig()
    )


class NextWordMenuTestApp(CompletionTestApp):
    """Harness with a warm prediction model and no history-word source."""

    def __init__(self) -> None:
        super().__init__()
        self.settings = PromptCompletionSettings()
        self.model = _compile_menu_model()
        self.prediction_deletions: frozenset[str] = frozenset()

    def get_prompt_completion_settings(self) -> PromptCompletionSettings:
        return self.settings

    def get_prompt_prediction_model(self) -> PromptPredictionModel | None:
        return self.model

    def get_prompt_prediction_project(self, _text: str) -> str | None:
        return None

    def prompt_prediction_disabled(self) -> bool:
        return False

    def disable_prompt_prediction(self) -> None:
        return None

    def warm_prompt_prediction(self) -> None:
        return None

    def history_prompt_word_deletions(self) -> frozenset[str]:
        return self.prediction_deletions


def _menu_bar_hint(bar: PromptInputBar) -> str:
    subtitle = bar.border_subtitle
    return subtitle.plain if hasattr(subtitle, "plain") else str(subtitle)


def _panel_title(bar: PromptInputBar) -> str:
    panel = bar.query_one("#prompt-completion", Static)
    title = panel.border_title
    return title.plain if hasattr(title, "plain") else str(title)


async def test_row3_midline_confident_shows_peek_not_menu() -> None:
    app = NextWordMenuTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Can you help me here")
        ta.cursor_location = (0, len("Can you help me"))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is False
        # A confident midline guess becomes a border peek, not a menu.
        assert ta._next_word_peek_visible() is True
        assert "implement" in _menu_bar_hint(bar)
        await pilot.press("ctrl+t")
        assert ta.text == "Can you help me implement here"
        assert ta._file_completion_active is False


async def test_row3_midline_without_confidence_opens_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = NextWordMenuTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Can you help me here")
        ta.cursor_location = (0, len("Can you help me"))
        weak = _result([_candidate("implement", continuation=["it", "now"])])
        monkeypatch.setattr(ta, "_predict_next_words", lambda *args, **kwargs: weak)
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_peek_visible() is False
        await pilot.press("ctrl+t")
        assert ta._file_completion_active is True
        assert ta._completion_kind == "next_word"
        assert _panel_title(bar).startswith("next word")
        assert "implement" in [
            candidate.insertion for candidate in ta._file_completion_candidates
        ]


async def test_row4b_word_end_fallback_shows_ghost() -> None:
    app = NextWordMenuTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        assert ta._next_word_chain_is_armed() is False
        ta.load_text("Can you help me")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("ctrl+t")
        assert ta._next_word_ghost_visible() is True
        assert ta.suggestion.startswith(" implement")
        assert ta._file_completion_active is False


async def test_row4b_mid_word_stays_noop() -> None:
    app = NextWordMenuTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("hello")
        ta.cursor_location = (0, 3)
        assert ta._try_file_completion_tab() is False
        assert ta._file_completion_active is False
        assert ta._next_word_chain_is_armed() is False
        assert "no next-word guess" not in _menu_bar_hint(bar)
        await pilot.pause()


async def test_menu_accept_inserts_separator_and_continues_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = NextWordMenuTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me here")
        ta.cursor_location = (0, len("Can you help me"))
        # Without confidence there is no peek: the menu still opens midline.
        weak = _result([_candidate("implement", continuation=["it", "now"])])
        monkeypatch.setattr(ta, "_predict_next_words", lambda *args, **kwargs: weak)
        ta._arm_next_word_chain()
        await pilot.pause()
        await pilot.press("ctrl+t")
        assert ta._completion_kind == "next_word"
        await pilot.press("ctrl+t")
        assert ta.text == "Can you help me implement here"
        assert ta._file_completion_active is False
        assert ta._next_word_chain_is_armed() is True


async def test_menu_ctrl_n_then_ctrl_t_accepts_second_row() -> None:
    app = NextWordMenuTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me implement it here")
        ta.cursor_location = (0, len("Can you help me implement it"))
        ta._arm_next_word_chain()
        await pilot.pause()
        await pilot.press("ctrl+t")
        assert ta._completion_kind == "next_word"
        assert len(ta._file_completion_candidates) >= 2
        expected = ta._file_completion_candidates[1].insertion
        await pilot.press("ctrl+n")
        await pilot.press("ctrl+t")
        assert f"it {expected}" in ta.text
        assert ta._next_word_chain_is_armed() is True


async def test_menu_ctrl_d_forgets_word_immediately() -> None:
    app = NextWordMenuTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me implement it here")
        ta.cursor_location = (0, len("Can you help me implement it"))
        ta._arm_next_word_chain()
        await pilot.pause()
        await pilot.press("ctrl+t")
        assert ta._completion_kind == "next_word"
        victim = ta._file_completion_candidates[0].insertion
        with (
            patch(
                "sase.ace.tui.util.io_async.schedule_persist",
            ) as schedule,
            patch.object(app, "notify") as notify,
        ):
            await pilot.press("ctrl+d")
        assert app.forgotten_history_words == [victim]
        assert victim not in [
            candidate.insertion for candidate in ta._file_completion_candidates
        ]
        assert ta._file_completion_active is True
        notify.assert_called_once_with(
            f"Deleted history word: {victim}",
            severity="information",
            markup=False,
        )
        assert schedule.call_args.args[2] == victim


async def test_menu_excludes_deleted_words() -> None:
    app = NextWordMenuTestApp()
    app.prediction_deletions = frozenset({"now"})
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me implement it here")
        ta.cursor_location = (0, len("Can you help me implement it"))
        ta._arm_next_word_chain()
        await pilot.pause()
        await pilot.press("ctrl+t")
        assert ta._completion_kind == "next_word"
        insertions = [
            candidate.insertion for candidate in ta._file_completion_candidates
        ]
        assert "now" not in insertions
        assert insertions


async def test_structural_context_never_opens_menu() -> None:
    app = NextWordMenuTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("```\nCan you help me")
        ta.cursor_location = (0, len(ta.text))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is False
        await pilot.press("ctrl+t")
        assert ta._file_completion_active is False
        assert "no next-word guess" in _menu_bar_hint(bar)
