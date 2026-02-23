"""Tests for xprompt syntax features (colon syntax and Jinja2 templates)."""

from unittest.mock import patch

from sase.xprompt.models import XPrompt
from sase.xprompt.processor import process_xprompt_references


def _make_xprompts(snippets: dict[str, str]) -> dict[str, XPrompt]:
    """Helper to convert string dict to XPrompt dict for mocking."""
    return {
        name: XPrompt(name=name, content=content) for name, content in snippets.items()
    }


# Tests for colon syntax (#name:arg)


def test_process_snippet_colon_syntax_basic() -> None:
    """Test basic colon syntax expands like parenthesis syntax."""
    snippets = {"greet": "Hello {1}!"}
    with patch(
        "sase.xprompt.processor.get_all_xprompts", return_value=_make_xprompts(snippets)
    ):
        result = process_xprompt_references("#greet:world")
    assert result == "Hello world!"


# Tests for Jinja2 templates with process_xprompt_references


# Tests for plus syntax (#name+)


def test_process_snippet_plus_syntax_basic() -> None:
    """Test plus syntax expands as 'true' positional argument."""
    snippets = {"enabled": "Feature: {1}"}
    with patch(
        "sase.xprompt.processor.get_all_xprompts", return_value=_make_xprompts(snippets)
    ):
        result = process_xprompt_references("#enabled+")
    assert result == "Feature: true"
