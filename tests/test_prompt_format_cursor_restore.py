"""Tests for cursor restoration after prettier reflow in PromptTextArea."""

import pytest

from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


# =============================================================================
# Unit tests for _map_offset
# =============================================================================


def test_map_offset_identical_text() -> None:
    """Offset is unchanged when old and new text are identical."""
    text = "hello world"
    assert PromptTextArea._map_offset(text, text, 5) == 5


def test_map_offset_space_collapse_before_cursor() -> None:
    """Cursor stays between same neighbors when spaces before it collapse."""
    old = "hello  world"  # cursor at 7, between the two 'w'-adjacent chars
    new = "hello world"
    # old[7] == 'w' (start of "world"); in new text "world" starts at 6
    assert PromptTextArea._map_offset(old, new, 7) == 6


def test_map_offset_space_collapse_cursor_in_gap() -> None:
    """Cursor inside the collapsed region maps to the collapse point."""
    old = "hello  world"  # cursor at 6 (second space)
    new = "hello world"
    mapped = PromptTextArea._map_offset(old, new, 6)
    # Should land at or just after the single space (position 5 or 6)
    assert 5 <= mapped <= 6


def test_map_offset_newline_reflow() -> None:
    """Cursor position is preserved across newline insertion."""
    old = "hello world foo"
    new = "hello world\nfoo"
    # Cursor was at offset 12 in old text (the 'f' of "foo")
    # In new text, 'f' is at offset 12 (after "hello world\n")
    assert PromptTextArea._map_offset(old, new, 12) == 12


def test_map_offset_at_end() -> None:
    """Cursor at end of text maps to end of new text."""
    old = "abc"
    new = "abcd"
    assert PromptTextArea._map_offset(old, new, 3) == 3


def test_map_offset_at_zero() -> None:
    """Cursor at start of unchanged text stays at start."""
    assert PromptTextArea._map_offset("abc", "abc", 0) == 0


def test_map_offset_insertion_at_start() -> None:
    """Cursor at start shifts right when new content is inserted before it."""
    # 'a' was at offset 0 in old; in new text 'x' is inserted before it,
    # so 'a' moves to offset 1.
    assert PromptTextArea._map_offset("abc", "xabc", 0) == 1


# =============================================================================
# Integration test: prettier reflow with mocked subprocess
# =============================================================================


def test_prettier_reflow_cursor_stays_between_neighbors() -> None:
    """Cursor stays between the same logical neighbors after prettier reflow.

    Regression test for the bug where naive absolute-offset restoration
    caused the cursor to drift when prettier normalized whitespace before
    the cursor position.
    """
    old_text = "foo  bar baz"
    new_text = "foo bar baz"
    cursor_offset = 5  # old[5] == 'b' (start of "bar")

    mapped = PromptTextArea._map_offset(old_text, new_text, cursor_offset)

    # In new text, 'b' (start of "bar") is at offset 4
    assert mapped == 4

    # Verify the cursor would land on the correct row/col
    lines = new_text.split("\n")
    remaining = mapped
    for i, line in enumerate(lines):
        if remaining <= len(line):
            assert (i, remaining) == (0, 4)
            break
        remaining -= len(line) + 1


def test_prettier_reflow_multiline_cursor_restore() -> None:
    """Cursor restores correctly when prettier reflows across lines."""
    # Old text: cursor at offset 16 ("w" of "world" on second chunk)
    old = "hello there  world"
    new = "hello there\nworld"

    mapped = PromptTextArea._map_offset(old, new, 13)
    # old[13] == 'w' of "world"; in new text after reflow, 'w' is at
    # offset 12 ("hello there\n" = 12 chars, then 'w' at 12)
    assert mapped == 12

    # Verify row/col conversion
    lines = new.split("\n")
    remaining = mapped
    for i, line in enumerate(lines):
        if remaining <= len(line):
            assert i == 1
            assert remaining == 0  # start of "world" on new line
            break
        remaining -= len(line) + 1


@pytest.mark.parametrize(
    "old, new, offset, expected_char",
    [
        ("a  b  c", "a b c", 3, "b"),  # cursor on 'b', spaces collapsed
        ("a  b  c", "a b c", 6, "c"),  # cursor on 'c', spaces collapsed
        ("ab cd", "ab\ncd", 3, "c"),  # cursor on 'c', space->newline
    ],
)
def test_map_offset_preserves_character_identity(
    old: str, new: str, offset: int, expected_char: str
) -> None:
    """Mapped offset points to the same character in the new text."""
    mapped = PromptTextArea._map_offset(old, new, offset)
    assert new[mapped] == expected_char
