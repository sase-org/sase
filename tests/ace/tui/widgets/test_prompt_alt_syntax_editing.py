"""Tests for ``%{...}`` alt-shorthand editing in the prompt input bar."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets.text_area import Selection

from sase.ace.tui.widgets._alt_syntax_editing import (
    AltEdit,
    _find_enclosing_alt_span,
    _is_directive_valid_brace_opening,
    plan_alt_auto_pair,
    plan_alt_paired_delete_left,
    plan_alt_paired_delete_right,
    plan_alt_separator,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class AltEditTestApp(App[None]):
    """Minimal app that hosts a PromptTextArea without frontmatter dependencies."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield PromptInputBar(mode="feedback")


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


def test_plan_alt_auto_pair_after_directive_percent() -> None:
    assert plan_alt_auto_pair("%", 1) == AltEdit(start=1, end=1, text="{}", cursor=2)
    assert plan_alt_auto_pair("run %", 5) == AltEdit(
        start=5, end=5, text="{}", cursor=6
    )


def test_plan_alt_auto_pair_requires_directive_context() -> None:
    # ``%`` not at a directive-valid position.
    assert plan_alt_auto_pair("a%", 2) is None
    # Cursor not directly after a ``%``.
    assert plan_alt_auto_pair("ab", 2) is None


def test_plan_alt_auto_pair_rejects_when_text_follows() -> None:
    # The inserted ``}`` would run into following non-whitespace text.
    assert plan_alt_auto_pair("%foo", 1) is None
    # Trailing whitespace is fine.
    assert plan_alt_auto_pair("% foo", 1) == AltEdit(
        start=1, end=1, text="{}", cursor=2
    )


def test_plan_alt_paired_delete_left_empty_pair() -> None:
    assert plan_alt_paired_delete_left("%{}", 2) == AltEdit(
        start=1, end=3, text="", cursor=1
    )


def test_plan_alt_paired_delete_left_rejects_nonempty_or_nondirective() -> None:
    # Brace pair is not empty.
    assert plan_alt_paired_delete_left("%{x}", 2) is None
    # ``{`` is not a directive opening.
    assert plan_alt_paired_delete_left("a{}", 2) is None


def test_plan_alt_paired_delete_right_empty_pair() -> None:
    assert plan_alt_paired_delete_right("%{}", 1) == AltEdit(
        start=1, end=3, text="", cursor=1
    )


def test_plan_alt_paired_delete_right_rejects_nonempty_or_nondirective() -> None:
    assert plan_alt_paired_delete_right("%{x}", 1) is None
    assert plan_alt_paired_delete_right("a{}", 1) is None


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


async def test_alt_auto_pair_inserts_braces() -> None:
    app = AltEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await pilot.press("%", "{")
        assert ta.text == "%{}"
        assert ta.cursor_location == (0, 2)


async def test_alt_auto_pair_only_after_directive_percent() -> None:
    app = AltEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("word")
        ta.cursor_location = (0, 4)
        await pilot.press("{")
        # No directive ``%`` precedes the brace, so no pair is inserted.
        assert ta.text == "word{"


async def test_alt_paired_backspace_removes_both_braces() -> None:
    app = AltEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{}")
        ta.cursor_location = (0, 2)
        await pilot.press("backspace")
        assert ta.text == "%"
        assert ta.cursor_location == (0, 1)


async def test_alt_paired_delete_right_removes_both_braces() -> None:
    app = AltEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{}")
        ta.cursor_location = (0, 1)
        await pilot.press("delete")
        assert ta.text == "%"
        assert ta.cursor_location == (0, 1)


async def test_alt_separator_inside_braces() -> None:
    app = AltEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{foo}")
        ta.cursor_location = (0, 5)
        await pilot.press("|")
        assert ta.text == "%{foo | }"
        assert ta.cursor_location == (0, 8)


async def test_alt_separator_acceptance_example() -> None:
    app = AltEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{foo ,bar, and baz}")
        ta.cursor_location = (0, 19)
        await pilot.press("|")
        assert ta.text == "%{foo, bar, and baz | }"
        assert ta.cursor_location == (0, 22)


async def test_alt_separator_in_unclosed_span() -> None:
    app = AltEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{foo")
        ta.cursor_location = (0, 5)
        await pilot.press("|")
        assert ta.text == "%{foo | "
        assert ta.cursor_location == (0, 8)


async def test_pipe_outside_alt_span_inserts_literal() -> None:
    app = AltEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("foo")
        ta.cursor_location = (0, 3)
        await pilot.press("|")
        assert ta.text == "foo|"


async def test_alt_edit_skipped_with_selection() -> None:
    app = AltEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("%{foo}")
        # Select ``foo``; typing ``|`` should replace the selection literally
        # rather than running separator normalization.
        ta.selection = Selection((0, 2), (0, 5))
        await pilot.press("|")
        assert ta.text == "%{|}"
