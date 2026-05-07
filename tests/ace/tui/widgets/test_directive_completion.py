"""Tests for prompt directive completion."""

from __future__ import annotations

from unittest.mock import patch

from textual.widgets import Static

from sase.ace.tui.widgets.directive_completion import (
    build_directive_completion_candidates,
    extract_directive_token_around_cursor,
    is_directive_like_token,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp


def test_directive_like_token_accepts_marker_and_identifier() -> None:
    assert is_directive_like_token("%") is True
    assert is_directive_like_token("%model") is True
    assert is_directive_like_token("model") is False
    assert is_directive_like_token("%model:opus") is False


def test_directive_completion_lists_canonical_directives() -> None:
    candidates, shared = build_directive_completion_candidates("%")
    insertions = {candidate.insertion for candidate in candidates}

    assert shared == ""
    assert "%alt" in insertions
    assert "%model" in insertions
    assert "%wait" in insertions
    assert "%xprompts_enabled" not in insertions


def test_directive_completion_filters_partial_name() -> None:
    candidates, shared = build_directive_completion_candidates("%mo")

    assert shared == ""
    assert [candidate.insertion for candidate in candidates] == ["%model"]


def test_directive_completion_matches_aliases_to_canonical_insertions() -> None:
    model, _ = _single_candidate("%m")
    repeat, _ = _single_candidate("%r")
    wait, _ = _single_candidate("%w")

    assert model.insertion == "%model"
    assert repeat.insertion == "%repeat"
    assert wait.insertion == "%wait"


def test_directive_completion_returns_multi_match_without_false_shared_prefix() -> None:
    candidates, shared = build_directive_completion_candidates("%e")

    assert [candidate.insertion for candidate in candidates] == ["%edit", "%epic"]
    assert shared == ""


def test_directive_token_extraction_rejects_non_directive_percent_positions() -> None:
    assert extract_directive_token_around_cursor("50%", 3) is None
    assert (
        extract_directive_token_around_cursor("word%model", len("word%model")) is None
    )


def test_directive_token_extraction_accepts_parser_contexts() -> None:
    assert extract_directive_token_around_cursor("%", 1) == (0, 1, "%")
    assert extract_directive_token_around_cursor("run %mo", len("run %mo")) == (
        4,
        7,
        "%mo",
    )
    assert extract_directive_token_around_cursor("(%wait", len("(%wait")) == (
        1,
        6,
        "%wait",
    )


async def test_ctrl_t_at_percent_opens_directive_panel() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        bar = app.query_one(PromptInputBar)
        ta = app.query_one(PromptTextArea)
        ta.load_text("%")
        ta.cursor_location = (0, 1)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

        panel = bar.query_one("#prompt-completion", Static)
        assert ta._file_completion_active is True
        assert ta._completion_kind == "directive"
        assert panel.border_title == "directives"


async def test_ctrl_t_at_partial_directive_inserts_single_candidate() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%mo")
        ta.cursor_location = (0, 3)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model"
    assert ta._file_completion_active is False


async def test_ctrl_t_at_alias_partial_inserts_canonical_directive() -> None:
    app = CompletionTestApp()
    async with app.run_test():
        ta = app.query_one(PromptTextArea)
        ta.load_text("%m")
        ta.cursor_location = (0, 2)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            assert ta._try_file_completion_tab() is True

    assert ta.text == "%model"
    assert ta._file_completion_active is False


async def test_multi_candidate_directive_completion_accepts_ctrl_l() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%e")
        ta.cursor_location = (0, 2)
        with patch.object(
            type(ta),
            "_ace_app",
            new_callable=lambda: property(lambda _s: app),
        ):
            await pilot.press("ctrl+t")
            assert ta._file_completion_active is True
            await pilot.press("down")
            selected = ta._file_completion_candidates[
                ta._file_completion_index
            ].insertion
            await pilot.press("ctrl+l")

    assert ta.text == selected
    assert ta._file_completion_active is False


def _single_candidate(token: str):
    candidates, shared = build_directive_completion_candidates(token)
    assert len(candidates) == 1
    return candidates[0], shared
