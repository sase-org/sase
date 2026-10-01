"""Pure and pilot tests for the mid-sentence next-word peek."""

from __future__ import annotations

import pytest
from rich.cells import cell_len
from textual.app import ComposeResult

from sase.ace.tui.widgets.next_word_completion import NEXT_WORD_GHOST_HINT
from sase.ace.tui.widgets.next_word_placement import (
    NEXT_WORD_PEEK_HINT_ALL,
    NEXT_WORD_PEEK_HINT_WORD,
    build_next_word_peek_text,
    trim_next_word_peek_words,
)
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui.widgets.test_prompt_next_word import NextWordTestApp, _bar_hint


def _auto_app() -> NextWordTestApp:
    return NextWordTestApp(settings=PromptCompletionSettings(next_word="auto"))


def _chain_app() -> NextWordTestApp:
    return NextWordTestApp(settings=PromptCompletionSettings(next_word="chain"))


def _off_app() -> NextWordTestApp:
    return NextWordTestApp(settings=PromptCompletionSettings(next_word="off"))


def _confident_result(words: list[str]):  # type: ignore[no-untyped-def]
    from sase.core.prompt_prediction_wire import PromptPredictionResult

    return PromptPredictionResult(
        schema_version=1,
        blocked_reason=None,
        context_words=["help", "me"],
        confident=True,
        ghost=list(words),
        candidates=[],
    )


def _patch_confident(
    monkeypatch: pytest.MonkeyPatch, area: PromptTextArea, words: list[str]
) -> None:
    result = _confident_result(words)
    monkeypatch.setattr(area, "_predict_next_words", lambda *args, **kwargs: result)


def test_peek_hint_matches_ghost_hint() -> None:
    assert (
        f"{NEXT_WORD_PEEK_HINT_WORD}  {NEXT_WORD_PEEK_HINT_ALL}" == NEXT_WORD_GHOST_HINT
    )


def test_trim_cuts_before_repeated_word() -> None:
    assert trim_next_word_peek_words(["review", "the", "plan"], " the plan") == [
        "review"
    ]


def test_trim_suppresses_when_first_word_repeats() -> None:
    assert trim_next_word_peek_words(["the", "plan"], " the plan") == []


def test_trim_is_casefolded_and_skips_punctuation() -> None:
    assert trim_next_word_peek_words(["Review", "it"], '  "REVIEW" now') == []
    assert trim_next_word_peek_words(["review", "it"], " after it") == ["review", "it"]


def test_trim_without_following_words_keeps_all() -> None:
    assert trim_next_word_peek_words(["review", "it"], "   ") == ["review", "it"]
    assert trim_next_word_peek_words([], " the plan") == []


def _available(bar_width: int, readout_cells: int = 12, pill_cells: int = 0) -> int:
    usable = bar_width - 6
    if pill_cells:
        return usable - readout_cells - pill_cells - 10
    return usable - readout_cells - 5


def test_peek_full_at_120_columns() -> None:
    peek = build_next_word_peek_text(
        ["review", "it", "now"], available_width=_available(120)
    )
    assert peek is not None
    assert peek.plain == "⇢ review it now  [^T] word  [^L] all"


def test_peek_degrades_at_70_columns() -> None:
    peek = build_next_word_peek_text(
        ["review", "it", "now"], available_width=_available(70)
    )
    assert peek is not None
    assert "review" in peek.plain
    assert cell_len(peek.plain) <= _available(70)


def test_peek_with_search_pill_drops_preview_first() -> None:
    without_pill = build_next_word_peek_text(
        ["review", "it", "now"], available_width=_available(70)
    )
    with_pill = build_next_word_peek_text(
        ["review", "it", "now"], available_width=_available(70, pill_cells=12)
    )
    assert without_pill is not None and with_pill is not None
    assert cell_len(with_pill.plain) <= cell_len(without_pill.plain)
    assert with_pill.plain.startswith("⇢ review")


def test_peek_minimal_at_40_columns() -> None:
    peek = build_next_word_peek_text(
        ["review", "it", "now"], available_width=_available(40)
    )
    assert peek is not None
    # A word is never cut: the first word survives even without hints.
    assert peek.plain.startswith("⇢ review")
    assert cell_len(peek.plain) <= _available(40)


def test_peek_none_when_first_word_does_not_fit() -> None:
    assert build_next_word_peek_text(["review"], available_width=5) is None
    assert build_next_word_peek_text(["review"], available_width=0) is None


def test_peek_uses_violet_glyph_and_theme_styles() -> None:
    peek = build_next_word_peek_text(
        ["review", "it"],
        variables={"text": "#FFFFFF", "text-muted": "#888888"},
        available_width=120,
    )
    assert peek is not None
    spans = [(span.start, span.end, span.style) for span in peek._spans]
    assert spans[0][2] == "bold #AF87FF"
    assert "bold" in str(spans[1][2]) and "#FFFFFF" in str(spans[1][2])


def test_peek_falls_back_for_textual_auto_specs() -> None:
    from rich.style import Style

    peek = build_next_word_peek_text(
        ["review", "it"],
        variables={"text": "auto 87%", "text-muted": "auto 60%"},
        available_width=120,
    )
    assert peek is not None
    assert peek.plain == "⇢ review it  [^T] word  [^L] all"
    for span in peek._spans:
        Style.parse(str(span.style))


async def test_auto_peek_appears_only_after_reveal_beat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Can you help me the plan")
        ta.cursor_location = (0, len("Can you help me"))
        _patch_confident(monkeypatch, ta, ["review", "it", "now"])
        ta._arm_next_word_chain(reveal="delayed")
        await pilot.pause()
        assert ta._next_word_peek_visible() is False
        assert ta._next_word_peek_pending() is True
        assert "[^T] word" not in _bar_hint(bar)
        await pilot.pause(0.6)
        assert ta._next_word_peek_visible() is True
        assert "review" in _bar_hint(bar)


async def test_ctrl_t_before_reveal_reveals_without_inserting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _chain_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me the plan")
        ta.cursor_location = (0, len("Can you help me"))
        _patch_confident(monkeypatch, ta, ["review", "it", "now"])
        ta._arm_next_word_chain(reveal="delayed")
        await pilot.pause()
        assert ta._next_word_peek_pending() is True
        before = ta.text
        await pilot.press("ctrl+t")
        assert ta.text == before
        assert ta._next_word_peek_visible() is True


async def test_ctrl_t_after_reveal_inserts_and_predicts_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _chain_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Can you help me the plan")
        ta.cursor_location = (0, len("Can you help me"))
        _patch_confident(monkeypatch, ta, ["review", "it", "now"])
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_peek_visible() is True
        await pilot.press("ctrl+t")
        assert ta.text.startswith("Can you help me review")
        assert ta._next_word_chain_is_armed() is True
        # The next guess shows immediately: no flicker, no extra pause.
        assert ta._next_word_peek_visible() is True or ta._next_word_ghost_visible()
        assert "[^T] word" in _bar_hint(bar)


async def test_ctrl_l_takes_all_peek_in_one_undo_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _chain_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me the plan")
        ta.cursor_location = (0, len("Can you help me"))
        _patch_confident(monkeypatch, ta, ["review", "it"])
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_peek_visible() is True
        before = ta.text
        await pilot.press("ctrl+l")
        assert ta.text == "Can you help me review it the plan"
        ta.undo()
        assert ta.text == before


async def test_peek_ctrl_t_lands_cursor_after_word() -> None:
    app = _chain_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me the plan")
        ta.cursor_location = (0, len("Can you help me"))
        from sase.core.prompt_prediction_wire import PromptPredictionResult

        result = PromptPredictionResult(
            schema_version=1,
            blocked_reason=None,
            context_words=["help", "me"],
            confident=True,
            ghost=["review"],
            candidates=[],
        )
        ta._predict_next_words = lambda *args, **kwargs: result  # type: ignore[method-assign]
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_peek_visible() is True
        await pilot.press("ctrl+t")
        offset = ta._absolute_offset(ta.cursor_location)
        assert ta.text[:offset].endswith("review")
        assert ta.text[offset:].startswith(" the plan")


async def test_peek_suppressed_when_next_word_already_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _chain_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("help me the plan")
        ta.cursor_location = (0, len("help me"))
        _patch_confident(monkeypatch, ta, ["the", "plan"])
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_peek_visible() is False
        assert ta._next_word_peek_pending() is False


async def test_unfittable_eol_ghost_becomes_peek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _chain_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Can you help me implement it now and then some more words here")
        ta.cursor_location = (0, len("Can you help me"))
        _patch_confident(monkeypatch, ta, ["review", "it", "now"])
        monkeypatch.setattr(ta, "_next_word_on_last_wrapped_row", lambda: False)
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_peek_visible() is True
        assert "review" in _bar_hint(bar)


async def test_backspace_and_cursor_motion_clear_peek(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _chain_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me the plan")
        ta.cursor_location = (0, len("Can you help me"))
        _patch_confident(monkeypatch, ta, ["review", "it", "now"])
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_peek_visible() is True
        await pilot.press("left")
        assert ta._next_word_peek_visible() is False
        ta.cursor_location = (0, len("Can you help me"))
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_peek_visible() is True
        await pilot.press("backspace")
        assert ta._next_word_peek_visible() is False


async def test_blur_clears_peek(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _chain_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me the plan")
        ta.cursor_location = (0, len("Can you help me"))
        _patch_confident(monkeypatch, ta, ["review", "it", "now"])
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_peek_visible() is True
        ta.on_blur()
        await pilot.pause()
        assert ta._next_word_peek_visible() is False


class StackedPeekTestApp(NextWordTestApp):
    """Peek harness with two stacked prompt panes."""

    def compose(self) -> ComposeResult:
        yield PromptInputBar(initial_panes=["Can you help me", "second pane"])


async def test_multi_pane_peek_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    app = StackedPeekTestApp()
    async with app.run_test() as pilot:
        panes = list(app.query(PromptTextArea))
        assert len(panes) == 2
        first, second = panes
        first.load_text("Can you help me the plan")
        first.cursor_location = (0, len("Can you help me"))
        _patch_confident(monkeypatch, first, ["review", "it", "now"])
        first._arm_next_word_chain()
        await pilot.pause()
        assert first._next_word_peek_visible() is True
        assert second._next_word_peek_visible() is False
        assert getattr(second, "_next_word_peek", None) is None


async def test_peek_soft_completion_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _chain_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me the plan")
        ta.cursor_location = (0, len("Can you help me"))
        _patch_confident(monkeypatch, ta, ["review", "it", "now"])
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_peek_visible() is True
        assert ta._soft_completion_blocked() is True


async def test_off_mode_shows_no_peek(monkeypatch: pytest.MonkeyPatch) -> None:
    app = _off_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me the plan")
        ta.cursor_location = (0, len("Can you help me"))
        _patch_confident(monkeypatch, ta, ["review", "it", "now"])
        ta._arm_next_word_chain()
        await pilot.pause()
        assert ta._next_word_peek_visible() is False
        assert ta._next_word_chain_is_armed() is False


async def test_chain_mode_auto_trigger_stays_silent() -> None:
    app = _chain_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me(and more)")
        ta.cursor_location = (0, len("Can you help me"))
        await pilot.press("space")
        await pilot.pause(0.6)
        assert ta._next_word_peek_visible() is False
