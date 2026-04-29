"""Tests for xprompt processor internal parsing and substitution functions."""

import pytest
from sase.xprompt._exceptions import XPromptArgumentError
from sase.xprompt._jinja import substitute_placeholders
from sase.xprompt._parsing import (
    _process_text_block,
    find_matching_paren_for_args,
    parse_args,
    parse_workflow_reference,
)
from sase.xprompt.models import XPrompt
from sase.xprompt.processor import expand_single_xprompt

# Tests for parse_named_arg


# Tests for parse_args


# Tests for is_jinja2_template


# Tests for substitute_placeholders (legacy mode)


# Tests for substitute_placeholders (Jinja2 mode)


def testsubstitute_placeholders_jinja2_missing_var_error() -> None:
    """Test that missing required variable raises error."""
    with pytest.raises(XPromptArgumentError, match="template error"):
        substitute_placeholders("Hello {{ name }}!", [], {}, "test")


# Tests for expand_single_xprompt


def testexpand_single_xprompt_mixed_args_jinja2() -> None:
    """Test expanding Jinja2 xprompt with mixed positional and named args."""
    xprompt = XPrompt(name="msg", content="{{ _1 }} says {{ message }}")
    result = expand_single_xprompt(xprompt, ["Alice"], {"message": "hello"})
    assert result == "Alice says hello"


# Tests for process_text_block


def testprocess_text_block_multiline_with_indentation() -> None:
    """Test processing a multiline text block with proper indentation."""
    text_block = """\
[[
  Line one.

  Line two.
]]"""
    result = _process_text_block(text_block)
    assert result == "Line one.\n\nLine two."


# Tests for find_matching_paren_for_args


def test_find_matching_paren_nested() -> None:
    """Test finding matching paren with nested parens."""
    assert find_matching_paren_for_args("(a(b)c)", 0) == 6


def test_find_matching_paren_unclosed() -> None:
    """Test that unclosed paren returns None."""
    assert find_matching_paren_for_args("(abc", 0) is None


# Tests for parse_args with text blocks


def testparse_args_mixed_text_blocks_and_quotes() -> None:
    """Test parsing mixed text blocks and quoted strings."""
    positional, named = parse_args('"quoted", [[text block]], name=value')
    assert positional == ["quoted", "text block"]
    assert named == {"name": "value"}


# Tests for parse_named_arg with text blocks


# Tests for parse_workflow_reference


def test_parse_workflow_reference_multiline_colon() -> None:
    """Test parsing workflow with multi-line colon syntax (space after colon)."""
    name, pos, named = parse_workflow_reference("foo: Some text here")
    assert name == "foo"
    assert pos == ["Some text here"]
    assert named == {}


def test_parse_workflow_reference_empty_parens() -> None:
    """Test parsing workflow with empty parentheses."""
    name, pos, named = parse_workflow_reference("workflow()")
    assert name == "workflow"
    assert pos == []
    assert named == {}
