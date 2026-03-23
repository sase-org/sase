"""Tests for sase.content module."""

from sase.content import (
    apply_section_marker_handling,
    content_ends_with_markdown_heading,
    ensure_str_content,
)


def test_ensure_str_content_with_list() -> None:
    """Test that list content is converted to string."""
    content: list[str | dict[str, str]] = ["part1", "part2", {"key": "value"}]
    result = ensure_str_content(content)
    assert isinstance(result, str)
    assert "part1" in result
    assert "part2" in result


# Tests for apply_section_marker_handling
def test_apply_section_marker_handling_hr_marker_only_not_at_line_start() -> None:
    """Test standalone --- marker not at line start is stripped (no newlines added for empty)."""
    content = "---"
    result = apply_section_marker_handling(content, is_at_line_start=False)
    assert result == ""


def test_apply_section_marker_handling_hr_marker_with_content() -> None:
    """Test --- marker at line start prepends \\n for paragraph break."""
    content = "---\nActual content"
    result = apply_section_marker_handling(content, is_at_line_start=True)
    assert result == "\nActual content"


# Tests for content_ends_with_markdown_heading
def test_content_ends_with_markdown_heading_empty() -> None:
    """Test that empty content returns False."""
    assert content_ends_with_markdown_heading("") is False
