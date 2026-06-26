"""Tests for the editor-return ` @` review-marker helper.

``strip_editor_review_markers`` is the editor-only successor to the removed
``%edit`` directive: any line of text returned from ``$EDITOR`` that ends with
the exact ` @` suffix triggers a reload-for-review, with the marker stripped
from every matching line before xprompt-markdown parsing.
"""

from __future__ import annotations

from sase.ace.tui.actions.agent_workflow._prompt_bar_mount import (
    strip_editor_review_markers,
)


def test_no_marker_returns_original_unchanged() -> None:
    text = "Fix auth\n---\nFix API"
    assert strip_editor_review_markers(text) == (False, text)


def test_single_marker_strips_and_signals_review() -> None:
    assert strip_editor_review_markers("Fix auth @") == (True, "Fix auth")


def test_multiple_marked_lines_all_strip() -> None:
    marked = "Fix auth @\n---\nFix API @"
    assert strip_editor_review_markers(marked) == (True, "Fix auth\n---\nFix API")


def test_marker_on_one_line_strips_only_that_line() -> None:
    marked = "Fix auth\n---\nFix API @"
    assert strip_editor_review_markers(marked) == (True, "Fix auth\n---\nFix API")


def test_trailing_space_after_marker_does_not_match() -> None:
    # The line ends in ``@ `` (marker then space), not ` @`, so it is not a marker.
    assert strip_editor_review_markers("Fix auth @ ") == (False, "Fix auth @ ")


def test_extra_space_before_marker_leaves_one_trailing_space() -> None:
    # Two spaces before ``@``: the marker's space is consumed, one space remains.
    assert strip_editor_review_markers("Fix auth  @") == (True, "Fix auth ")


def test_final_newline_and_unix_style_preserved() -> None:
    assert strip_editor_review_markers("Fix auth @\n") == (True, "Fix auth\n")


def test_crlf_newline_style_preserved() -> None:
    marked = "Fix auth @\r\nkeep\r\n"
    assert strip_editor_review_markers(marked) == (True, "Fix auth\r\nkeep\r\n")


def test_non_marked_text_with_at_sign_elsewhere_is_unchanged() -> None:
    # A bare ``@`` that is not a trailing ` @` line suffix never matches.
    text = "ping @alice about the bug"
    assert strip_editor_review_markers(text) == (False, text)


def test_marked_separator_becomes_real_separator_for_stack_parsing() -> None:
    # ``--- @`` is stripped to a real ``---`` separator before xprompt parsing.
    marked = "Fix auth\n--- @\nFix API"
    assert strip_editor_review_markers(marked) == (True, "Fix auth\n---\nFix API")


def test_marker_inside_frontmatter_or_code_block_still_counts() -> None:
    # Unlike ``%`` directive parsing, the marker is recognized on any returned
    # line, including inside frontmatter and fenced code blocks.
    marked = "---\ndescription: do the thing @\n---\n```\ncode line @\n```"
    cleaned = "---\ndescription: do the thing\n---\n```\ncode line\n```"
    assert strip_editor_review_markers(marked) == (True, cleaned)
