"""Pure helper tests for the next-word ghost chain."""

from __future__ import annotations

from sase.ace.tui.widgets.next_word_completion import (
    NEXT_WORD_GHOST_HINT,
    NEXT_WORD_NO_GUESS_HINT,
    NEXT_WORD_WARMING_HINT,
    NextWordChain,
    NextWordGhost,
    build_next_word_ghost_text,
    fit_next_word_ghost,
    next_word_chain_armed,
    next_word_ghost_expected,
    next_word_has_word_suffix,
    next_word_leading_separator,
    next_word_rest_of_line,
    split_next_word_one,
)


def test_leading_separator_rules() -> None:
    assert next_word_leading_separator("") == ""
    assert next_word_leading_separator("hello") == " "
    assert next_word_leading_separator("hello ") == ""
    assert next_word_leading_separator("hello\n") == ""
    assert next_word_leading_separator("(") == ""
    assert next_word_leading_separator("[") == ""
    assert next_word_leading_separator('"') == ""


def test_build_and_split_ghost() -> None:
    assert build_next_word_ghost_text(["it", "now"], " ") == " it now"
    assert build_next_word_ghost_text(["it"], "") == "it"
    assert build_next_word_ghost_text([], " ") == ""
    assert split_next_word_one(" it now") == " it"
    assert split_next_word_one("it now") == "it"
    assert split_next_word_one("") == ""
    assert split_next_word_one(" ") == ""


def test_fit_truncates_to_whole_words_and_caps() -> None:
    words = ["implement", "it", "now"]
    assert fit_next_word_ghost(words, " ", 100, 4) == words
    assert fit_next_word_ghost(words, " ", 100, 2) == ["implement", "it"]
    # " implement" is 10 cells; width 10 fits first word only.
    assert fit_next_word_ghost(words, " ", 10, 4) == ["implement"]
    assert fit_next_word_ghost(words, " ", 5, 4) == []
    assert fit_next_word_ghost(words, " ", 0, 4) == []


def test_chain_armed_requires_offset_and_text() -> None:
    chain = NextWordChain(anchor_offset=5, anchor_text="hello")
    assert next_word_chain_armed(chain, text="hello", cursor_offset=5) is True
    assert next_word_chain_armed(chain, text="hello!", cursor_offset=5) is False
    assert next_word_chain_armed(chain, text="hello", cursor_offset=4) is False
    assert next_word_chain_armed(None, text="hello", cursor_offset=5) is False


def test_ghost_expected_tracks_consumed_prefix() -> None:
    ghost = NextWordGhost(anchor_offset=5, full_text=" it now")
    assert (
        next_word_ghost_expected(ghost, text="hello it now", cursor_offset=5)
        == " it now"
    )
    assert (
        next_word_ghost_expected(ghost, text="hello it now", cursor_offset=8) == " now"
    )
    assert next_word_ghost_expected(ghost, text="helloX", cursor_offset=6) is None
    assert next_word_ghost_expected(ghost, text="hell", cursor_offset=5) is None
    assert next_word_ghost_expected(ghost, text="hello", cursor_offset=4) is None


def test_rest_of_line_and_suffix() -> None:
    assert next_word_rest_of_line("hello", 5) == ""
    assert next_word_rest_of_line("hello\nworld", 5) == ""
    assert next_word_rest_of_line("hello world", 5) == " world"
    assert next_word_has_word_suffix("foo bar", 4) is True
    assert next_word_has_word_suffix("foo bar", 3) is False


def test_hint_constants() -> None:
    assert NEXT_WORD_GHOST_HINT == "[^T] word  [^F] all"
    assert NEXT_WORD_NO_GUESS_HINT == "no next-word guess"
    assert NEXT_WORD_WARMING_HINT == "warming next words…"
