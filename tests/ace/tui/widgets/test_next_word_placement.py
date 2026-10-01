"""Pure helper tests for next-word placement and tail-aware fitting."""

from __future__ import annotations

from sase.ace.tui.widgets.next_word_placement import (
    NEXT_WORD_CLOSING_TAIL_CHARS,
    NEXT_WORD_MAX_TAIL_CHARS,
    NextWordPlacement,
    classify_next_word_placement,
    fit_next_word_ghost_with_tail,
    _next_word_closing_tail,
    next_word_auto_space_eligible,
    next_word_is_last_wrapped_section,
)


def test_classify_end_of_line() -> None:
    assert classify_next_word_placement("hello", 5) is NextWordPlacement.INLINE_EOL
    assert classify_next_word_placement("hello ", 6) is NextWordPlacement.INLINE_EOL
    assert (
        classify_next_word_placement("hello\nworld", 5) is NextWordPlacement.INLINE_EOL
    )
    assert classify_next_word_placement("", 0) is NextWordPlacement.INLINE_EOL


def test_classify_closing_tail_variants() -> None:
    assert (
        classify_next_word_placement("Please check (see the)", 21)
        is NextWordPlacement.INLINE_TAIL
    )
    # Quoted and emphasized tails count.
    assert classify_next_word_placement('say ""', 4) is NextWordPlacement.INLINE_TAIL
    assert classify_next_word_placement("very **", 5) is NextWordPlacement.INLINE_TAIL
    # Spaces inside the tail are fine.
    assert classify_next_word_placement("x ) )", 2) is NextWordPlacement.INLINE_TAIL
    # Sentence-final punctuation is a tail.
    assert classify_next_word_placement("done.", 4) is NextWordPlacement.INLINE_TAIL


def test_classify_tail_too_long_becomes_peek() -> None:
    rest = ")" * (NEXT_WORD_MAX_TAIL_CHARS + 1)
    assert classify_next_word_placement("hi " + rest, 3) is NextWordPlacement.PEEK
    assert (
        classify_next_word_placement("hi " + ")" * NEXT_WORD_MAX_TAIL_CHARS, 3)
        is NextWordPlacement.INLINE_TAIL
    )


def test_classify_backtick_is_never_a_tail() -> None:
    assert classify_next_word_placement("hi `code`", 3) is NextWordPlacement.PEEK
    assert "`" not in NEXT_WORD_CLOSING_TAIL_CHARS


def test_classify_word_char_after_cursor_is_none() -> None:
    assert classify_next_word_placement("hello world", 6) is NextWordPlacement.NONE
    assert classify_next_word_placement("a-b", 1) is NextWordPlacement.NONE
    assert classify_next_word_placement("a_b", 1) is NextWordPlacement.NONE
    assert classify_next_word_placement("don't", 3) is NextWordPlacement.NONE
    assert classify_next_word_placement("hi’", 2) is NextWordPlacement.NONE
    assert classify_next_word_placement("a1", 0) is NextWordPlacement.NONE


def test_classify_prose_after_cursor_is_peek() -> None:
    assert classify_next_word_placement("a b c", 1) is NextWordPlacement.PEEK
    assert (
        classify_next_word_placement("see the(parser output)", 7)
        is NextWordPlacement.PEEK
    )
    assert classify_next_word_placement("hi", 9) is NextWordPlacement.NONE
    assert classify_next_word_placement("hi", -1) is NextWordPlacement.NONE


def test_closing_tail_validator() -> None:
    assert _next_word_closing_tail(")") == ")"
    assert _next_word_closing_tail(") ") == ") "
    assert _next_word_closing_tail("") is None
    assert _next_word_closing_tail("   ") is None
    assert _next_word_closing_tail("the)") is None
    assert _next_word_closing_tail("`x`") is None


def test_last_wrapped_section() -> None:
    assert next_word_is_last_wrapped_section([], 5) is True
    assert next_word_is_last_wrapped_section([3, 8], 10) is True
    assert next_word_is_last_wrapped_section([3, 8], 8) is True
    assert next_word_is_last_wrapped_section([3, 8], 7) is False
    assert next_word_is_last_wrapped_section([3, 8], 0) is False


def test_fit_with_tail_subtracts_tail_cells() -> None:
    words = ["parser", "output"]
    # " parser output" is 15 cells; the ")" leaves 19 of 20.
    assert fit_next_word_ghost_with_tail(words, " ", 20, 4, ")") == words
    # A wide tail squeezes out the second word, then the first.
    assert fit_next_word_ghost_with_tail(words, " ", 20, 4, ")" * 12) == ["parser"]
    assert fit_next_word_ghost_with_tail(words, " ", 20, 4, ")" * 14) == []
    # An empty tail behaves like the plain fit.
    assert fit_next_word_ghost_with_tail(words, " ", 100, 2, "") == words
    assert fit_next_word_ghost_with_tail(words, " ", 5, 4, ")") == []
    assert fit_next_word_ghost_with_tail([], " ", 100, 4, ")") == []


def test_fit_without_tail_truncates_to_whole_words_and_caps() -> None:
    words = ["implement", "it", "now"]
    assert fit_next_word_ghost_with_tail(words, " ", 100, 4, "") == words
    assert fit_next_word_ghost_with_tail(words, " ", 100, 2, "") == ["implement", "it"]
    # " implement" is 10 cells; width 10 fits first word only.
    assert fit_next_word_ghost_with_tail(words, " ", 10, 4, "") == ["implement"]
    assert fit_next_word_ghost_with_tail(words, " ", 5, 4, "") == []
    assert fit_next_word_ghost_with_tail(words, " ", 0, 4, "") == []


def test_auto_trigger_generalized_beyond_end_of_line() -> None:
    # End of line still triggers.
    assert next_word_auto_space_eligible("hello ", 6) is True
    assert next_word_auto_space_eligible("hello, ", 7) is True
    # Before a closing tail triggers now (was end-of-line only). A
    # closer before the trigger is skipped like other clause punctuation.
    assert next_word_auto_space_eligible("see the) ", 9) is True
    assert next_word_auto_space_eligible("see the )", 8) is True
    assert next_word_auto_space_eligible("see (the)", 4) is True
    # A word character after the cursor never triggers.
    assert next_word_auto_space_eligible("hello world", 6) is False
    # A typed word character is a mid-word keystroke, not a trigger.
    assert next_word_auto_space_eligible("helloX", 6) is False
    # Doubled spaces, line starts, and empty text have no word token.
    assert next_word_auto_space_eligible("hello  ", 7) is False
    assert next_word_auto_space_eligible(" ", 1) is False
    assert next_word_auto_space_eligible("", 0) is False
    # Structural prefixes are not word tokens.
    assert next_word_auto_space_eligible("# ", 2) is False
    assert next_word_auto_space_eligible("( ", 2) is False
    assert next_word_auto_space_eligible("hello. ", 7) is True
