"""Pure resolver tests for operator + search motions."""

from __future__ import annotations

from sase.ace.tui.widgets._vim_search_motion import (
    SEARCH_MOTION_MUTATING_OPERATORS,
    describe_search_motion_effect,
    _exclusive_motion_range,
    resolve_search_motion,
    search_motion_miss_message,
    search_operator_family,
    search_operator_verb,
)


def test_forward_basic() -> None:
    text = "foo bar foo"
    res = resolve_search_motion(text, 0, "foo", "forward", count=1)
    assert list(res.spans) == [(0, 3), (8, 11)]
    # Match at origin is skipped, so the target is the second span.
    assert res.target_index == 1
    assert res.reachable == 1
    assert res.opposite == 0
    assert res.motion_range is not None
    assert (res.motion_range.start, res.motion_range.end) == (0, 8)
    assert res.motion_range.linewise is False


def test_reverse_basic() -> None:
    text = "foo bar foo"
    res = resolve_search_motion(text, 10, "foo", "reverse", count=1)
    # Both matches start before the origin; nearest first wins.
    assert res.target_index == 1
    assert res.reachable == 2
    assert res.opposite == 0
    assert res.motion_range is not None
    assert (res.motion_range.start, res.motion_range.end) == (8, 10)


def test_match_at_cursor_skipped() -> None:
    text = "alpha beta alpha"
    # Origin exactly on the first match start: it counts toward neither side.
    res = resolve_search_motion(text, 0, "alpha", "forward", count=1)
    assert res.target_index == 1
    assert res.reachable == 1
    assert res.opposite == 0
    rev = resolve_search_motion(text, 0, "alpha", "reverse", count=1)
    assert rev.target_index is None
    assert rev.reachable == 0
    assert rev.opposite == 1


def test_overlapping_matches() -> None:
    text = "aaa"
    res = resolve_search_motion(text, 0, "aa", "forward", count=1)
    assert res.spans == ((0, 2), (1, 3))
    assert res.target_index == 1
    assert (res.motion_range.start, res.motion_range.end) == (0, 1)


def test_smartcase_forward_and_reverse() -> None:
    text = "Alpha alpha ALPHA"
    lower = resolve_search_motion(text, 0, "alpha", "forward", count=1)
    assert len(lower.spans) == 3
    upper = resolve_search_motion(text, 0, "Alpha", "forward", count=1)
    assert upper.spans == ((0, 5),)
    assert upper.target_index is None
    assert upper.reachable == 0
    assert upper.opposite == 0
    rev_lower = resolve_search_motion(text, len(text), "alpha", "reverse", count=1)
    assert rev_lower.reachable == 3
    rev_upper = resolve_search_motion(text, len(text), "Alpha", "reverse", count=1)
    assert rev_upper.spans == ((0, 5),)
    assert rev_upper.target_index == 0


def test_count_selects_nth_match() -> None:
    text = "a foo b foo c foo"
    res = resolve_search_motion(text, 0, "foo", "forward", count=2)
    # Count 2 selects the 2nd candidate (index 1); the range stops at its start.
    assert res.target_index == 1
    assert res.reachable == 3
    assert res.motion_range is not None
    assert res.motion_range.start == 0
    assert res.motion_range.end == 8


def test_count_exceeding_matches() -> None:
    text = "foo bar foo"
    res = resolve_search_motion(text, 0, "foo", "forward", count=5)
    assert res.target_index is None
    assert res.motion_range is None
    assert res.reachable == 1
    assert search_motion_miss_message(res, "forward", 5, "foo") == (
        "only 1 match after cursor"
    )
    rev = resolve_search_motion(text, len(text), "foo", "reverse", count=3)
    assert search_motion_miss_message(rev, "reverse", 3, "foo") == (
        "only 2 matches before cursor"
    )


def test_no_match_in_direction_reports_opposite() -> None:
    text = "foo bar foo"
    res = resolve_search_motion(text, len(text), "foo", "forward", count=1)
    assert res.target_index is None
    assert res.reachable == 0
    assert res.opposite == 2
    assert search_motion_miss_message(res, "forward", 1, "foo") == (
        "no match after cursor · 2 before"
    )
    rev = resolve_search_motion(text, 0, "foo", "reverse", count=1)
    # Origin on the first match: that match is neither side, one remains after.
    assert rev.opposite == 1
    assert search_motion_miss_message(rev, "reverse", 1, "foo") == (
        "no match before cursor · 1 after"
    )


def test_zero_matches() -> None:
    res = resolve_search_motion("hello world", 0, "zzz", "forward", count=1)
    assert res.spans == ()
    assert res.target_index is None
    assert res.reachable == 0
    assert res.opposite == 0
    assert search_motion_miss_message(res, "forward", 1, "zzz") == "pattern not found"


def test_charwise_column_zero_adjustment() -> None:
    text = "  abcdef\nXYZ\n"
    # Origin inside the first row after its indent; match at next row col 0.
    res = resolve_search_motion(text, 5, "XYZ", "forward", count=1)
    assert res.target_index == 0
    assert res.motion_range is not None
    assert res.motion_range.linewise is False
    assert (res.motion_range.start, res.motion_range.end) == (5, 8)
    assert (res.motion_range.first_row, res.motion_range.last_row) == (0, 0)


def test_linewise_adjustment() -> None:
    text = "alpha\nbeta\n"
    res = resolve_search_motion(text, 0, "beta", "forward", count=1)
    assert res.motion_range is not None
    assert res.motion_range.linewise is True
    assert (res.motion_range.start, res.motion_range.end) == (0, 6)
    assert (res.motion_range.first_row, res.motion_range.last_row) == (0, 0)


def test_linewise_on_whitespace_only_row() -> None:
    text = "   \nbeta\n"
    res = resolve_search_motion(text, 1, "beta", "forward", count=1)
    assert res.motion_range is not None
    assert res.motion_range.linewise is True
    assert (res.motion_range.first_row, res.motion_range.last_row) == (0, 0)


def test_empty_adjustment_guard_keeps_raw_range() -> None:
    text = "  ab\ncd\n"
    # Cursor at end of row 0 (offset 4); match at row 1 col 0 would adjust to
    # an empty range, so the raw newline-only range is kept.
    res = resolve_search_motion(text, 4, "cd", "forward", count=1)
    assert res.motion_range is not None
    assert res.motion_range.linewise is False
    assert (res.motion_range.start, res.motion_range.end) == (4, 5)


def test_reverse_origin_at_column_zero() -> None:
    text = "foo\nbar\nfoo\n"
    res = resolve_search_motion(text, 8, "foo", "reverse", count=1)
    assert res.target_index == 0
    assert res.motion_range is not None
    assert res.motion_range.linewise is True
    assert (res.motion_range.first_row, res.motion_range.last_row) == (0, 1)


def test_first_row_last_row_charwise_multiline() -> None:
    text = "ab cd\nef gh\nij"
    res = resolve_search_motion(text, 0, "gh", "forward", count=1)
    assert res.motion_range is not None
    assert res.motion_range.linewise is False
    assert res.motion_range.first_row == 0
    assert res.motion_range.last_row == 1


def test_exclusive_motion_range_direct() -> None:
    assert _exclusive_motion_range("hello", 1, 4).start == 1
    linewise = _exclusive_motion_range("alpha\nbeta\n", 0, 6)
    assert linewise.linewise is True
    assert (linewise.first_row, linewise.last_row) == (0, 0)


def test_effect_strings() -> None:
    text = "foo bar foo"
    res = resolve_search_motion(text, 0, "foo", "forward", count=1)
    assert res.motion_range is not None
    assert describe_search_motion_effect("d", res.motion_range) == "delete 8 chars"
    single = resolve_search_motion("ab foo", 0, "foo", "forward", count=1)
    assert single.motion_range is not None
    assert describe_search_motion_effect("y", single.motion_range) == "yank 3 chars"
    one = _exclusive_motion_range("ab", 0, 1)
    assert describe_search_motion_effect("d", one) == "delete 1 char"
    linewise = _exclusive_motion_range("alpha\nbeta\n", 0, 6)
    assert describe_search_motion_effect("d", linewise) == "delete 1 line"
    two_lines = _exclusive_motion_range("a\nb\nc\n", 0, 4)
    assert describe_search_motion_effect("d", two_lines) == "delete 2 lines"
    multi = resolve_search_motion("ab cd\nef gh\nij", 0, "gh", "forward", count=1)
    assert multi.motion_range is not None
    effect = describe_search_motion_effect("d", multi.motion_range)
    assert "chars · 2 lines" in effect
    indent = resolve_search_motion(text, 0, "foo", "forward", count=1)
    assert indent.motion_range is not None
    assert describe_search_motion_effect(">", indent.motion_range).startswith("indent")


def test_families_verbs_and_mutating_set() -> None:
    assert search_operator_family("d") == "destructive"
    assert search_operator_family("c") == "destructive"
    assert search_operator_family("y") == "yank"
    assert search_operator_family("gU") == "transform"
    assert search_operator_family(">") == "transform"
    assert search_operator_family("ys") == "transform"
    assert search_operator_verb("d") == "delete"
    assert search_operator_verb("c") == "change"
    assert search_operator_verb("y") == "yank"
    assert search_operator_verb("gu") == "lowercase"
    assert search_operator_verb("gU") == "uppercase"
    assert search_operator_verb("g~") == "toggle case"
    assert search_operator_verb(">") == "indent"
    assert search_operator_verb("<") == "dedent"
    assert search_operator_verb("ys") == "surround"
    assert "d" in SEARCH_MOTION_MUTATING_OPERATORS
    assert "y" not in SEARCH_MOTION_MUTATING_OPERATORS
    assert "ys" not in SEARCH_MOTION_MUTATING_OPERATORS
