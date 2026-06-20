"""Tests for ``%{...}`` alt-shorthand editing in the prompt input bar."""

from __future__ import annotations

from textual.widgets.text_area import Selection

from sase.ace.tui.widgets._alt_syntax_editing import (
    AltEdit,
    _find_enclosing_alt_span,
    _is_directive_valid_brace_opening,
    plan_alt_separator,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

from ._completion_helpers import CompletionTestApp

# --------------------------------------------------------------------------- #
# Pure-helper tests                                                           #
# --------------------------------------------------------------------------- #


def test_is_directive_valid_brace_opening_contexts() -> None:
    assert _is_directive_valid_brace_opening("%", 0) is True
    assert _is_directive_valid_brace_opening("run %", 4) is True
    assert _is_directive_valid_brace_opening("(%", 1) is True
    assert _is_directive_valid_brace_opening("a%", 1) is False
    assert _is_directive_valid_brace_opening("50%", 2) is False
    assert _is_directive_valid_brace_opening("x", 0) is False


def test_find_enclosing_alt_span() -> None:
    text = "%{foo}"
    assert _find_enclosing_alt_span(text, 2) == (2, 5)
    assert _find_enclosing_alt_span(text, 5) == (2, 5)
    # Cursor on the ``%`` (offset 0) is not inside the span content.
    assert _find_enclosing_alt_span(text, 0) is None
    # Outside any span.
    assert _find_enclosing_alt_span("plain text", 4) is None
    # Unclosed span runs to end of text.
    assert _find_enclosing_alt_span("%{foo", 4) == (2, 5)


def test_find_enclosing_alt_span_ignores_non_directive_brace() -> None:
    # ``a%{`` is not a directive-valid opening, so no span is reported.
    assert _find_enclosing_alt_span("a%{foo}", 4) is None


def test_plan_alt_separator_simple_branch() -> None:
    # ``%{foo}`` with the cursor before ``}``.
    assert plan_alt_separator("%{foo}", 5) == AltEdit(
        start=2, end=5, text="foo | ", cursor=8
    )


def test_plan_alt_separator_acceptance_example() -> None:
    text = "%{foo ,bar, and baz}"
    # Cursor before the closing ``}``.
    assert plan_alt_separator(text, 19) == AltEdit(
        start=2, end=19, text="foo, bar, and baz | ", cursor=22
    )


def test_plan_alt_separator_second_branch_preserves_prior_separator() -> None:
    # ``%{a | b}`` typing ``|`` after ``b`` keeps the first separator intact.
    text = "%{a | b}"
    plan = plan_alt_separator(text, 7)
    assert plan is not None
    applied = text[: plan.start] + plan.text + text[plan.end :]
    assert applied == "%{a | b | }"


def test_plan_alt_separator_outside_span_returns_none() -> None:
    assert plan_alt_separator("plain", 3) is None


# --------------------------------------------------------------------------- #
# Textual integration tests                                                   #
# --------------------------------------------------------------------------- #


async def test_alt_open_brace_inserts_literally_after_percent() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await pilot.press("%", "{")
        assert ta.text == "%{"
        assert ta.cursor_location == (0, 2)


async def test_open_brace_inserts_literally_outside_alt_context() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("word")
        ta.cursor_location = (0, 4)
        await pilot.press("{")
        # No directive ``%`` precedes the brace, so no pair is inserted.
        assert ta.text == "word{"


async def test_alt_backspace_deletes_only_opening_brace() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{}")
        ta.cursor_location = (0, 2)
        await pilot.press("backspace")
        assert ta.text == "%}"
        assert ta.cursor_location == (0, 1)


async def test_alt_delete_right_deletes_only_opening_brace() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{}")
        ta.cursor_location = (0, 1)
        await pilot.press("delete")
        assert ta.text == "%}"
        assert ta.cursor_location == (0, 1)


async def test_alt_separator_inside_braces() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{foo}")
        ta.cursor_location = (0, 5)
        await pilot.press("|")
        assert ta.text == "%{foo | }"
        assert ta.cursor_location == (0, 8)


async def test_alt_separator_acceptance_example() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{foo ,bar, and baz}")
        ta.cursor_location = (0, 19)
        await pilot.press("|")
        assert ta.text == "%{foo, bar, and baz | }"
        assert ta.cursor_location == (0, 22)


async def test_alt_separator_in_unclosed_span() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{foo")
        ta.cursor_location = (0, 5)
        await pilot.press("|")
        assert ta.text == "%{foo | "
        assert ta.cursor_location == (0, 8)


async def test_pipe_outside_alt_span_inserts_literal() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("foo")
        ta.cursor_location = (0, 3)
        await pilot.press("|")
        assert ta.text == "foo|"


async def test_alt_edit_skipped_with_selection() -> None:
    app = CompletionTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{foo}")
        # Select ``foo``; typing ``|`` should replace the selection literally
        # rather than running separator normalization.
        ta.selection = Selection((0, 2), (0, 5))
        await pilot.press("|")
        assert ta.text == "%{|}"
