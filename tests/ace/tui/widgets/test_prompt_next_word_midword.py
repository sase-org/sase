"""Pilot and pure tests for mid-word autosuggest from word completion."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets.next_word_completion import (
    NextWordChain,
    build_midword_ghost_text,
    fit_midword_ghost_with_tail,
    midword_peek_words,
)
from sase.ace.tui.widgets.next_word_placement import next_word_midword_eligible
from sase.ace.tui.widgets.prompt_completion import PromptCompletionSettings
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.core.prompt_prediction_wire import (
    PromptPredictionRequest,
    PromptPredictionResult,
    PromptPredictionWordCompletion,
)
from tests.ace.tui.widgets.test_prompt_next_word import NextWordTestApp, _bar_hint


def _place_cursor_at_end(ta: PromptTextArea) -> None:
    rows = ta.text.split("\n")
    ta.cursor_location = (len(rows) - 1, len(rows[-1]))


def _auto_app() -> NextWordTestApp:
    return NextWordTestApp(settings=PromptCompletionSettings(next_word="auto"))


class _DeletedWordApp(NextWordTestApp):
    """Harness where ``implement`` was deleted from history words."""

    def history_prompt_word_deletions(self) -> frozenset[str]:
        return frozenset({"implement"})


def _midword_result(
    prefix: str,
    word: str,
    suffix: str,
    ghost: list[str],
    *,
    confident: bool = True,
) -> PromptPredictionResult:
    return PromptPredictionResult(
        schema_version=1,
        blocked_reason=None,
        context_words=["help", "me"],
        confident=confident,
        ghost=list(ghost),
        candidates=[],
        word_completion=PromptPredictionWordCompletion(
            prefix=prefix, word=word, suffix=suffix
        ),
    )


def _completionless_result(words: list[str]) -> PromptPredictionResult:
    """A confident old-core result: no ``word_completion`` field."""
    return PromptPredictionResult(
        schema_version=1,
        blocked_reason=None,
        context_words=["help", "me"],
        confident=True,
        ghost=list(words),
        candidates=[],
    )


def _patch_result(
    monkeypatch: pytest.MonkeyPatch,
    area: PromptTextArea,
    result: PromptPredictionResult,
) -> None:
    monkeypatch.setattr(area, "_predict_next_words", lambda *args, **kwargs: result)


def test_chain_defaults_to_boundary_arms() -> None:
    assert NextWordChain(anchor_offset=1, anchor_text="x").midword is False
    assert NextWordChain(anchor_offset=1, anchor_text="x", midword=True).midword is True


def test_build_midword_ghost_shapes() -> None:
    assert build_midword_ghost_text("ment", ["it", "now"]) == "ment it now"
    assert build_midword_ghost_text("", ["it", "now"]) == " it now"
    assert build_midword_ghost_text("ment", []) == "ment"
    assert build_midword_ghost_text("", []) == ""


def test_fit_midword_drops_trailing_continuation() -> None:
    assert (
        fit_midword_ghost_with_tail("ment", ["it", "now", "please"], 12, 4, "")
        == "ment it now"
    )
    assert fit_midword_ghost_with_tail("ment", ["it", "now"], 12, 4, " )") == "ment it"
    assert fit_midword_ghost_with_tail("ment", ["it"], 3, 4, "") == ""
    assert fit_midword_ghost_with_tail("", [], 40, 4, "") == ""


def test_fit_midword_caps_continuation_at_max_words_minus_one() -> None:
    assert (
        fit_midword_ghost_with_tail("ment", ["it", "now", "a", "b"], 40, 2, "")
        == "ment it"
    )
    assert midword_peek_words("implement", ["it", "now", "a", "b"], 2) == [
        "implement",
        "it",
    ]


def test_midword_peek_first_word_is_the_completed_word() -> None:
    assert midword_peek_words("implement", ["it", "now"], 4) == [
        "implement",
        "it",
        "now",
    ]


def test_midword_eligible() -> None:
    assert next_word_midword_eligible("Can you help me imple", 21) is True
    assert next_word_midword_eligible("Plan (see the imple)", 19) is True
    assert next_word_midword_eligible("Can you help me imple the plan", 21) is True
    assert next_word_midword_eligible("Can you help me implement it", 20) is False
    assert next_word_midword_eligible("Can you help me ", 16) is False
    assert next_word_midword_eligible("", 0) is False
    assert next_word_midword_eligible("imple", 99) is False


async def test_typing_word_character_shows_midword_ghost() -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me impl")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("e")
        assert ta.text == "Can you help me imple"
        assert ta.suggestion == "ment it"
        assert ta._next_word_ghost_visible() is True
        assert ta._next_word_chain is not None
        assert ta._next_word_chain.midword is True


async def test_matching_keystroke_consumes_midword_ghost() -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me impl")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("e")
        assert ta._next_word_ghost_visible() is True
        await pilot.press("m")
        assert ta.text == "Can you help me implem"
        assert ta.suggestion == "ent it"
        assert ta._next_word_ghost_visible() is True


async def test_divergent_keystroke_repredicts_to_silence() -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me impl")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("e")
        assert ta._next_word_ghost_visible() is True
        await pilot.press("x")
        assert ta.text == "Can you help me implex"
        assert ta._next_word_ghost_visible() is False
        assert ta.suggestion == ""


async def test_exact_word_shows_continuation_ghost() -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me implemen")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("t")
        assert ta.text == "Can you help me implement"
        assert ta.suggestion == " it"
        assert ta._next_word_ghost_visible() is True


async def test_ctrl_t_finishes_word_then_continues() -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me impl")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("e")
        assert ta.suggestion == "ment it"
        await pilot.press("ctrl+t")
        assert ta.text == "Can you help me implement"
        assert ta.suggestion.startswith(" it")
        ta.undo()
        assert ta.text == "Can you help me imple"


async def test_title_and_allcaps_casing() -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me Impl")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("e")
        assert ta.suggestion == "ment it"
        ta.load_text("Can you help me IMPL")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("E")
        assert ta.suggestion == "MENT it"


async def test_deleted_word_is_never_completed() -> None:
    app = _DeletedWordApp(settings=PromptCompletionSettings(next_word="auto"))
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        result = ta._predict_next_words(
            "Can you help me imple", complete_current_word=True
        )
        assert result is not None
        assert result.confident is True
        assert result.word_completion is None
        ta.load_text("Can you help me impl")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("e")
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_peek_visible() is False


async def test_old_core_result_stays_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _patch_result(monkeypatch, ta, _completionless_result(["it", "now"]))
        ta.load_text("Can you help me impl")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("e")
        assert ta.text == "Can you help me imple"
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_peek_visible() is False
        assert ta.suggestion == ""


async def test_explicit_midword_never_opens_a_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.widgets.next_word_completion import NEXT_WORD_NO_GUESS_HINT

    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        _patch_result(monkeypatch, ta, _completionless_result(["it", "now"]))
        ta.load_text("Can you help me impl")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("e")
        assert ta._next_word_chain is not None
        assert ta._next_word_chain.midword is True
        await pilot.press("ctrl+t")
        assert ta._file_completion_active is False
        assert NEXT_WORD_NO_GUESS_HINT in _bar_hint(bar)


async def test_chain_mode_shows_no_midword_ghost() -> None:
    app = NextWordTestApp(settings=PromptCompletionSettings(next_word="chain"))
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me impl")
        ta.cursor_location = (0, len(ta.text))
        await pilot.press("e")
        assert ta.text == "Can you help me imple"
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_peek_visible() is False


async def test_word_character_after_cursor_stays_silent() -> None:
    app = _auto_app()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("Can you help me implement it now")
        ta.cursor_location = (0, len("Can you help me imple"))
        assert ta._maybe_auto_next_word_ghost("e") is False
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_peek_visible() is False


async def test_midword_peek_reveals_then_finishes_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        _patch_result(
            monkeypatch, ta, _midword_result("imple", "implement", "ment", ["it"])
        )
        ta.load_text("Can you help me impl the plan")
        ta.cursor_location = (0, len("Can you help me impl"))
        await pilot.press("e")
        assert ta.text == "Can you help me imple the plan"
        assert ta._next_word_peek_pending() is True
        before = ta.text
        await pilot.press("ctrl+t")
        assert ta.text == before
        assert ta._next_word_peek_visible() is True
        assert "implement" in _bar_hint(bar)


async def test_midword_peek_ctrl_t_finishes_without_duplicating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _patch_result(
            monkeypatch, ta, _midword_result("imple", "implement", "ment", ["it"])
        )
        ta.load_text("Can you help me impl the plan")
        ta.cursor_location = (0, len("Can you help me impl"))
        await pilot.press("e")
        await pilot.pause(0.6)
        assert ta._next_word_peek_visible() is True
        await pilot.press("ctrl+t")
        assert ta.text == "Can you help me implement the plan"
        assert ta._next_word_chain_is_armed() is True
        ta.undo()
        assert ta.text == "Can you help me imple the plan"


async def test_midword_peek_ctrl_l_takes_all_in_one_undo_step(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        _patch_result(
            monkeypatch,
            ta,
            _midword_result("imple", "implement", "ment", ["it", "now"]),
        )
        ta.load_text("Can you help me impl the plan")
        ta.cursor_location = (0, len("Can you help me impl"))
        await pilot.press("e")
        await pilot.pause(0.6)
        assert ta._next_word_peek_visible() is True
        before = ta.text
        await pilot.press("ctrl+l")
        assert ta.text == "Can you help me implement it now the plan"
        ta.undo()
        assert ta.text == before


async def test_real_midword_peek_after_prose() -> None:
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        bar = app.query_one(PromptInputBar)
        ta.load_text("Can you help me impl the plan")
        ta.cursor_location = (0, len("Can you help me impl"))
        await pilot.press("e")
        assert ta.text == "Can you help me imple the plan"
        assert ta._next_word_ghost_visible() is False
        await pilot.pause(0.6)
        assert ta._next_word_peek_visible() is True
        assert "implement" in _bar_hint(bar)
        await pilot.press("ctrl+t")
        assert ta.text == "Can you help me implement the plan"


def _long_midword_text() -> str:
    # Newline padding keeps the last wrapped row roomy (so the ghost
    # fits inline) while pushing the draft past the synchronous
    # threshold; only the trailing words matter for the request.
    return "padding words for length\n" * 200 + "Can you help me imple"


def _spy_predict(monkeypatch: pytest.MonkeyPatch, seen: dict[str, object]) -> None:
    """Record deferred request flags while delegating to the real model."""
    from sase.core.prompt_prediction_facade import PromptPredictionModel

    real_predict = PromptPredictionModel.predict

    def spy_predict(
        self: object, request: PromptPredictionRequest
    ) -> PromptPredictionResult:
        seen["complete_current_word"] = request.complete_current_word
        seen["limit"] = request.limit
        return real_predict(self, request)

    monkeypatch.setattr(PromptPredictionModel, "predict", spy_predict)


async def test_deferred_midword_defers_then_applies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    _spy_predict(monkeypatch, seen)
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(_long_midword_text())
        _place_cursor_at_end(ta)
        # A direct trigger call is synchronous: the timer is pending but
        # nothing has predicted yet (pilot.press would wait it out).
        assert ta._maybe_auto_next_word_midword("e") is False
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_peek_visible() is False
        assert ta._next_word_midword_timer is not None
        await pilot.pause(0.6)
        assert ta._next_word_ghost_visible() is True
        assert ta.suggestion == "ment it"
        assert seen["complete_current_word"] is True
        assert seen["limit"] == 0


async def test_deferred_midword_discards_a_stale_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}
    _spy_predict(monkeypatch, seen)
    app = _auto_app()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(_long_midword_text())
        _place_cursor_at_end(ta)
        assert ta._maybe_auto_next_word_midword("e") is False
        ta.load_text("something else entirely")
        ta.cursor_location = (0, len(ta.text))
        await pilot.pause(0.6)
        assert ta._next_word_ghost_visible() is False
        assert ta._next_word_peek_visible() is False
        assert ta.suggestion == ""
