"""Tests for prompt search match helpers."""

from __future__ import annotations

import pytest

from sase.ace.tui.widgets._vim_search import (
    SearchSelection,
    find_search_matches,
    select_search_match,
)


def test_smartcase_lowercase_query_matches_case_insensitively() -> None:
    text = "Foo foo FOO"

    assert find_search_matches(text, "foo") == ((0, 3), (4, 7), (8, 11))


def test_smartcase_uppercase_query_matches_case_sensitively() -> None:
    text = "Foo foo FOO"

    assert find_search_matches(text, "Fo") == ((0, 2),)
    assert find_search_matches(text, "FO") == ((8, 10),)


def test_smartcase_can_be_disabled_for_case_sensitive_matching() -> None:
    text = "Foo foo FOO"

    assert find_search_matches(text, "foo", smartcase=False) == ((4, 7),)


def test_find_search_matches_handles_empty_and_no_match() -> None:
    assert find_search_matches("abc", "") == ()
    assert find_search_matches("abc", "z") == ()


def test_find_search_matches_handles_multiline_query() -> None:
    text = "one\ntwo\none"

    assert find_search_matches(text, "two\none") == ((4, 11),)


def test_find_search_matches_handles_unicode_case_insensitively() -> None:
    text = "café CAFÉ"

    assert find_search_matches(text, "café") == ((0, 4), (5, 9))


def test_find_search_matches_includes_overlapping_and_adjacent_spans() -> None:
    assert find_search_matches("aaaa", "aa") == ((0, 2), (1, 3), (2, 4))
    assert find_search_matches("abab", "ab") == ((0, 2), (2, 4))


def test_select_search_match_forward_without_wrap() -> None:
    matches = ((0, 3), (5, 8), (10, 13))

    assert select_search_match(matches, 4, "forward") == SearchSelection(
        index=1,
        wrapped=False,
    )


def test_select_search_match_forward_wraps_to_first() -> None:
    matches = ((0, 3), (5, 8), (10, 13))

    assert select_search_match(matches, 13, "forward") == SearchSelection(
        index=0,
        wrapped=True,
    )


def test_select_search_match_forward_can_exclude_origin() -> None:
    matches = ((0, 3), (5, 8), (10, 13))

    assert select_search_match(
        matches,
        5,
        "forward",
        include_origin=False,
    ) == SearchSelection(index=2, wrapped=False)


def test_select_search_match_reverse_without_wrap() -> None:
    matches = ((0, 3), (5, 8), (10, 13))

    assert select_search_match(matches, 9, "reverse") == SearchSelection(
        index=1,
        wrapped=False,
    )


def test_select_search_match_reverse_wraps_to_last() -> None:
    matches = ((0, 3), (5, 8), (10, 13))

    assert select_search_match(
        matches,
        0,
        "reverse",
        include_origin=False,
    ) == SearchSelection(index=2, wrapped=True)


def test_select_search_match_handles_empty_matches() -> None:
    assert select_search_match((), 0, "forward") is None
    assert select_search_match((), 0, "reverse") is None


def test_select_search_match_rejects_unknown_direction() -> None:
    with pytest.raises(ValueError, match="unknown search direction"):
        select_search_match(((0, 1),), 0, "sideways")  # type: ignore[arg-type]
