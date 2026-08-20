"""Tests for shared UTF-16 editor-range conversion."""

from __future__ import annotations

from sase.ace.tui.util.editor_offsets import (
    _editor_position_to_offset,
    _python_column_from_utf16,
    editor_range_to_offsets,
    utf16_character,
)


def test_utf16_character_counts_non_bmp_as_two_units() -> None:
    assert utf16_character("A") == 1
    assert utf16_character("😀") == 2
    assert utf16_character("A😀B") == 4


def test_python_column_from_utf16_snaps_mid_surrogate_to_character() -> None:
    line = "😀X"
    assert _python_column_from_utf16(line, 0) == 0
    assert _python_column_from_utf16(line, 1) == 0
    assert _python_column_from_utf16(line, 2) == 1
    assert _python_column_from_utf16(line, 3) == 2
    assert _python_column_from_utf16(line, 4) is None


def test_editor_range_converts_wrapped_segment_and_non_bmp_prefix() -> None:
    text = "Ask 😀\n  Clan now"
    editor_range = {
        "start": {"line": 1, "character": 2},
        "end": {"line": 1, "character": 6},
    }

    assert editor_range_to_offsets(text, editor_range) == (
        text.index("Clan"),
        text.index("Clan") + 4,
    )


def test_malformed_editor_ranges_fail_open() -> None:
    text = "Agent Clan"
    assert editor_range_to_offsets(text, None) is None
    assert editor_range_to_offsets(text, {"start": {"line": 0}}) is None
    assert _editor_position_to_offset(text, {"line": 3, "character": 0}) is None
    assert (
        editor_range_to_offsets(
            text,
            {
                "start": {"line": 0, "character": 5},
                "end": {"line": 0, "character": 2},
            },
        )
        is None
    )
