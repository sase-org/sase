"""Tests for macro syntax features (colon syntax and Jinja2 templates)."""

from unittest.mock import patch

from sase.macro.models import Macro
from sase.macro.processor import process_macro_references


def _make_macros(snippets: dict[str, str]) -> dict[str, Macro]:
    """Helper to convert string dict to Macro dict for mocking."""
    return {
        name: Macro(name=name, content=content) for name, content in snippets.items()
    }


# Tests for colon syntax (#name:arg)


def test_process_snippet_colon_syntax_basic() -> None:
    """Test basic colon syntax expands like parenthesis syntax."""
    snippets = {"greet": "Hello {1}!"}
    with patch(
        "sase.macro.processor.get_all_macros", return_value=_make_macros(snippets)
    ):
        result = process_macro_references("#greet:world")
    assert result == "Hello world!"


# Tests for Jinja2 templates with process_macro_references


# Tests for plus syntax (#name+)


def test_process_snippet_plus_syntax_basic() -> None:
    """Test plus syntax expands as 'true' positional argument."""
    snippets = {"enabled": "Feature: {1}"}
    with patch(
        "sase.macro.processor.get_all_macros", return_value=_make_macros(snippets)
    ):
        result = process_macro_references("#enabled+")
    assert result == "Feature: true"
