"""Tests for chat resume formatting and turn parsing."""

import tempfile
from pathlib import Path

from sase.history.chat import _parse_chat_turns, _parse_flat_turns, load_chat_for_resume


def test_load_chat_for_resume_format() -> None:
    """Test load_chat_for_resume produces flat User/Assistant format."""
    content = """\
# Chat History - run

**Timestamp:** 2024-01-02

## Previous Conversation

## Chat History - run

**Timestamp:** 2024-01-01

### Prompt

Hello

### Response

World

---

## Prompt

Follow up

## Response

Follow up answer
"""
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.md"
        test_file.write_text(content, encoding="utf-8")

        result = load_chat_for_resume(str(test_file))

    # Should have flat format with no markdown headings
    assert "**User:**" in result
    assert "**Assistant:**" in result
    assert "## Prompt" not in result
    assert "## Response" not in result
    assert "### Prompt" not in result

    # Content should be in chronological order
    hello_pos = result.index("Hello")
    followup_pos = result.index("Follow up")
    assert hello_pos < followup_pos

    # Turns should be separated by ---
    assert "---" in result


def test_parse_chat_turns_with_extra_sections() -> None:
    """Test _parse_chat_turns still works when extra sections are present."""
    content = """\
# Chat History - run

**Timestamp:** 2024-01-01

## Plan Feedback

### Round 1
> Please add tests

## Questions & Answers

### Q1: Which DB?
**Selected:** PostgreSQL

## Prompt

Fix the login bug

## Response

Done!
"""
    turns = _parse_chat_turns(content)
    assert len(turns) == 1
    assert turns[0][0] == "Fix the login bug"
    assert turns[0][1] == "Done!"


def test_load_chat_for_resume_fallback() -> None:
    """Test load_chat_for_resume falls back to raw content if no turns found."""
    content = "Just some raw text with no prompt/response structure."
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = Path(tmpdir) / "test.md"
        test_file.write_text(content, encoding="utf-8")

        result = load_chat_for_resume(str(test_file))

    assert result == content


def test_parse_flat_turns_basic() -> None:
    """Test _parse_flat_turns with standard input."""
    text = (
        "**User:**\n\nHello\n\n**Assistant:**\n\nWorld\n\n---\n\n"
        "**User:**\n\nHow are you?\n\n**Assistant:**\n\nFine!"
    )
    turns = _parse_flat_turns(text)
    assert len(turns) == 2
    assert turns[0] == ("Hello", "World")
    assert turns[1] == ("How are you?", "Fine!")


def test_parse_flat_turns_empty() -> None:
    """Test _parse_flat_turns with empty input."""
    assert _parse_flat_turns("") == []
    assert _parse_flat_turns("   ") == []


def test_parse_flat_turns_malformed() -> None:
    """Test _parse_flat_turns with text that has no Assistant marker."""
    text = "**User:**\n\nJust a prompt with no response"
    assert _parse_flat_turns(text) == []
