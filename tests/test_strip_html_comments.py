"""Tests for the strip_html_comments function."""

from sase.gemini_wrapper.file_references import strip_html_comments


def test_no_comments_unchanged() -> None:
    """Text without comments should be returned unchanged."""
    text = "Hello world\nNo comments here."
    assert strip_html_comments(text) == text


def test_comments_in_code_blocks_preserved() -> None:
    """Comments inside fenced code blocks should be preserved."""
    text = """Some text
```html
<!-- This comment should stay -->
<div>Content</div>
```
More text"""
    result = strip_html_comments(text)
    assert "<!-- This comment should stay -->" in result
    assert "Some text" in result
    assert "More text" in result
