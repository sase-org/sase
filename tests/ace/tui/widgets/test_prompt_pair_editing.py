"""Tests for generic insert-mode auto-pairing in the prompt input bar."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets.text_area import Selection

from sase.ace.tui.widgets._paired_text_editing import (
    TextEdit,
    plan_pair_close_skip,
    plan_pair_delete_left,
    plan_pair_delete_right,
    plan_pair_insert,
)
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


class PairEditTestApp(App[None]):
    """Minimal app that hosts a PromptTextArea without frontmatter dependencies."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield PromptInputBar(mode="feedback")


# --------------------------------------------------------------------------- #
# plan_pair_insert                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("char", "closer"),
    [
        ("(", ")"),
        ("[", "]"),
        ("{", "}"),
        ("'", "'"),
        ('"', '"'),
        ("`", "`"),
    ],
)
def test_plan_pair_insert_at_eof(char: str, closer: str) -> None:
    assert plan_pair_insert("", 0, char) == TextEdit(
        start=0, end=0, text=char + closer, cursor=1
    )


@pytest.mark.parametrize(
    ("char", "closer"),
    [
        ("(", ")"),
        ("[", "]"),
        ("{", "}"),
        ("'", "'"),
        ('"', '"'),
        ("`", "`"),
    ],
)
def test_plan_pair_insert_before_whitespace(char: str, closer: str) -> None:
    # ``<space><cursor><space>`` -- both neighbors are whitespace, which is safe
    # for brackets and the stricter quote rules alike.
    assert plan_pair_insert("  ", 1, char) == TextEdit(
        start=1, end=1, text=char + closer, cursor=2
    )


def test_plan_pair_insert_before_existing_closer() -> None:
    # ``(<cursor>)`` typing ``[`` pairs because the next character is a closer.
    assert plan_pair_insert("()", 1, "[") == TextEdit(
        start=1, end=1, text="[]", cursor=2
    )


@pytest.mark.parametrize("opener", ["("])
def test_plan_pair_insert_brackets_reject_before_token_chars(opener: str) -> None:
    # Word characters and token-continuation characters block bracket pairing.
    for following in ("a", "1", "_", ".", "$", "%", "(", "'", '"', "`"):
        assert plan_pair_insert(following, 0, opener) is None


def test_plan_pair_insert_never_pairs_angle_brackets() -> None:
    assert plan_pair_insert("", 0, "<") is None
    assert plan_pair_insert(" ", 0, "<") is None


def test_plan_pair_insert_quote_rejects_contraction() -> None:
    # ``don<cursor>`` typing ``'`` would be a contraction apostrophe.
    assert plan_pair_insert("don", 3, "'") is None


def test_plan_pair_insert_quote_rejects_possessive() -> None:
    assert plan_pair_insert("Bryan", 5, "'") is None


def test_plan_pair_insert_quote_rejects_after_escape() -> None:
    # A single trailing backslash escapes the typed quote.
    assert plan_pair_insert("\\", 1, "'") is None
    # An even run of backslashes is not an escape, so pairing resumes.
    assert plan_pair_insert("\\\\", 2, "'") == TextEdit(
        start=2, end=2, text="''", cursor=3
    )


def test_plan_pair_insert_quote_rejects_repeated_delimiter() -> None:
    # ``\`<cursor>`` typing another backtick keeps fences typeable.
    assert plan_pair_insert("`", 1, "`") is None
    assert plan_pair_insert("'", 1, "'") is None


def test_plan_pair_insert_quote_after_space() -> None:
    assert plan_pair_insert("a ", 2, "'") == TextEdit(
        start=2, end=2, text="''", cursor=3
    )


def test_plan_pair_insert_quote_rejects_before_word() -> None:
    assert plan_pair_insert("(x", 1, "'") is None


def test_plan_pair_insert_ignores_non_pair_chars() -> None:
    assert plan_pair_insert("", 0, "a") is None
    assert plan_pair_insert("", 0, ")") is None
    assert plan_pair_insert("", 0, ">") is None


# --------------------------------------------------------------------------- #
# plan_pair_close_skip                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("opener", "closer"), [("(", ")")])
def test_plan_pair_close_skip_bracket(opener: str, closer: str) -> None:
    assert plan_pair_close_skip(opener + closer, 1, closer) == TextEdit(
        start=1, end=1, text="", cursor=2
    )


@pytest.mark.parametrize(("opener", "closer"), [("(", ")")])
def test_plan_pair_close_skip_bracket_requires_unmatched_opener(
    opener: str, closer: str
) -> None:
    # A lone closer under the cursor has no opener to belong to.
    assert plan_pair_close_skip(closer, 0, closer) is None
    # An already-balanced pair before a stray closer is not skipped.
    assert plan_pair_close_skip(opener + closer + closer, 2, closer) is None


def test_plan_pair_close_skip_requires_next_char_match() -> None:
    assert plan_pair_close_skip("(x)", 1, ")") is None


def test_plan_pair_close_skip_quote_odd_count() -> None:
    assert plan_pair_close_skip("''", 1, "'") == TextEdit(
        start=1, end=1, text="", cursor=2
    )


def test_plan_pair_close_skip_quote_even_count_rejected() -> None:
    # Two delimiters already precede the cursor, so the next quote opens a pair.
    assert plan_pair_close_skip("'''", 2, "'") is None


def test_plan_pair_close_skip_ignores_openers() -> None:
    assert plan_pair_close_skip("((", 1, "(") is None


# --------------------------------------------------------------------------- #
# plan_pair_delete_left / plan_pair_delete_right                              #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("pair", ["()", "[]", "{}", "''", '""', "``"])
def test_plan_pair_delete_left_empty_pair(pair: str) -> None:
    assert plan_pair_delete_left(pair, 1) == TextEdit(start=0, end=2, text="", cursor=0)


@pytest.mark.parametrize("pair", ["()", "[]", "{}", "''", '""', "``"])
def test_plan_pair_delete_right_empty_pair(pair: str) -> None:
    assert plan_pair_delete_right(pair, 0) == TextEdit(
        start=0, end=2, text="", cursor=0
    )


def test_plan_pair_delete_left_rejects_non_empty_pair() -> None:
    assert plan_pair_delete_left("(x)", 1) is None


def test_plan_pair_delete_right_rejects_non_empty_pair() -> None:
    assert plan_pair_delete_right("(x)", 0) is None


def test_plan_pair_delete_rejects_mismatched_pair() -> None:
    assert plan_pair_delete_left("(]", 1) is None
    assert plan_pair_delete_right("(]", 0) is None


def test_plan_pair_delete_left_rejects_at_edges() -> None:
    assert plan_pair_delete_left("()", 0) is None
    assert plan_pair_delete_left("()", 2) is None


# --------------------------------------------------------------------------- #
# Multiline absolute-offset behavior                                          #
# --------------------------------------------------------------------------- #


def test_plan_pair_insert_multiline_offset() -> None:
    # ``foo\n<cursor>`` -- offset 4 sits at the start of the second line (EOF).
    assert plan_pair_insert("foo\n", 4, "(") == TextEdit(
        start=4, end=4, text="()", cursor=5
    )


def test_plan_pair_delete_left_multiline_offset() -> None:
    # ``x\n(<cursor>)`` -- the empty pair spans offsets 2..4 on the second line.
    assert plan_pair_delete_left("x\n()", 3) == TextEdit(
        start=2, end=4, text="", cursor=2
    )


# --------------------------------------------------------------------------- #
# Textual integration                                                         #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("char", "expected"),
    [
        ("(", "()"),
        ("[", "[]"),
        ("{", "{}"),
        ("'", "''"),
        ('"', '""'),
        ("`", "``"),
    ],
)
async def test_typing_opener_inserts_pair(char: str, expected: str) -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await pilot.press(char)
        assert ta.text == expected
        assert ta.cursor_location == (0, 1)


@pytest.mark.parametrize(
    ("opener", "closer"),
    [("(", ")"), ("[", "]"), ("{", "}")],
)
async def test_typing_closer_moves_over_auto_pair(opener: str, closer: str) -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await pilot.press(opener, closer)
        assert ta.text == opener + closer
        assert ta.cursor_location == (0, 2)


@pytest.mark.parametrize("pair", ["()", "[]", "{}", "''", '""', "``"])
async def test_backspace_removes_empty_pair(pair: str) -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(pair)
        ta.cursor_location = (0, 1)
        await pilot.press("backspace")
        assert ta.text == ""


@pytest.mark.parametrize("pair", ["()", "[]", "{}", "''", '""', "``"])
async def test_delete_removes_empty_pair(pair: str) -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text(pair)
        ta.cursor_location = (0, 0)
        await pilot.press("delete")
        assert ta.text == ""


async def test_typing_angle_brackets_is_literal_and_not_paired_deleted() -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        await pilot.press("<")
        assert ta.text == "<"
        assert ta.cursor_location == (0, 1)

        await pilot.press(">")
        assert ta.text == "<>"
        assert ta.cursor_location == (0, 2)

        ta.cursor_location = (0, 1)
        await pilot.press("backspace")
        assert ta.text == ">"


async def test_backspace_keeps_non_empty_pair() -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("(x)")
        ta.cursor_location = (0, 1)
        await pilot.press("backspace")
        # Only the opener is removed; the closer survives.
        assert ta.text == "x)"


async def test_selection_receives_literal_replacement() -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("abc")
        ta.selection = Selection((0, 0), (0, 3))
        await pilot.press("(")
        # The selection is replaced literally rather than being wrapped.
        assert ta.text == "("


async def test_quote_not_paired_in_contraction() -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("don")
        ta.cursor_location = (0, 3)
        await pilot.press("'")
        assert ta.text == "don'"


async def test_markdown_backtick_fence_progression() -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        # First backtick opens an inline pair.
        await pilot.press("`")
        assert ta.text == "``"
        assert ta.cursor_location == (0, 1)
        # Second backtick moves over the auto-inserted closer.
        await pilot.press("`")
        assert ta.text == "``"
        assert ta.cursor_location == (0, 2)
        # Third backtick is literal, giving a triple-backtick fence prefix.
        await pilot.press("`")
        assert ta.text == "```"
        assert ta.cursor_location == (0, 3)


async def test_typing_opener_pairs_on_second_line() -> None:
    app = PairEditTestApp()
    async with app.run_test() as pilot:
        ta = app.query_one(PromptTextArea)
        ta.load_text("foo\n")
        ta.cursor_location = (1, 0)
        await pilot.press("(")
        assert ta.text == "foo\n()"
        assert ta.cursor_location == (1, 1)
