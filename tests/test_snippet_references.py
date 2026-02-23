"""Tests for process_xprompt_references function (basic and section xprompts)."""

from unittest.mock import patch

from sase.xprompt.models import XPrompt
from sase.xprompt.processor import process_xprompt_references


def _make_xprompts(snippets: dict[str, str]) -> dict[str, XPrompt]:
    """Helper to convert string dict to XPrompt dict for mocking."""
    return {
        name: XPrompt(name=name, content=content) for name, content in snippets.items()
    }


# Tests for process_xprompt_references


def test_process_xprompt_references_no_snippets_defined() -> None:
    """Test with # but no snippets defined returns unchanged."""
    with patch("sase.xprompt.processor.get_all_xprompts", return_value={}):
        result = process_xprompt_references("Using #foo here")
    assert result == "Using #foo here"


def test_process_xprompt_references_with_optional_arg_using_default() -> None:
    """Test snippet with optional arg using default value."""
    snippets = {"opt": "Value is {1:DEFAULT}"}
    with patch(
        "sase.xprompt.processor.get_all_xprompts", return_value=_make_xprompts(snippets)
    ):
        result = process_xprompt_references("#opt()")
    assert result == "Value is DEFAULT"


# Tests for section snippets (content starting with ###)


# Tests for horizontal rule snippets (content starting with ---)


def test_process_xprompt_heading_content_gets_newline_before_inline_text() -> None:
    """Test that xprompt ending with heading gets newline when followed by inline text."""
    snippets = {"section": "# New Query"}
    with patch(
        "sase.xprompt.processor.get_all_xprompts", return_value=_make_xprompts(snippets)
    ):
        result = process_xprompt_references("#section Fix this bug")
    # The heading should be separated from the following text by a blank line
    # (two newlines so that prettier doesn't collapse the separation)
    assert result == "# New Query\n\n Fix this bug"


def test_process_xprompt_heading_content_no_extra_newline_at_end() -> None:
    """Test that xprompt ending with heading at end of prompt gets no extra newline."""
    snippets = {"section": "# New Query"}
    with patch(
        "sase.xprompt.processor.get_all_xprompts", return_value=_make_xprompts(snippets)
    ):
        result = process_xprompt_references("#section")
    # No trailing newline when nothing follows
    assert result == "# New Query"


def test_process_xprompt_heading_content_no_extra_newline_before_newline() -> None:
    """Test that xprompt ending with heading before a newline gets no extra newline."""
    snippets = {"section": "# New Query"}
    with patch(
        "sase.xprompt.processor.get_all_xprompts", return_value=_make_xprompts(snippets)
    ):
        result = process_xprompt_references("#section\nFix this bug")
    # No extra newline added since the next char is already a newline
    assert result == "# New Query\nFix this bug"
