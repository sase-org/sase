"""Tests for the xprompt.models module."""

import pytest
from sase.xprompt.models import (
    UNSET,
    InputArg,
    InputType,
    XPrompt,
    XPromptValidationError,
    create_anonymous_workflow,
    xprompt_to_workflow,
)

# Tests for InputType enum


def test_input_type_values() -> None:
    """Test that InputType enum has expected values."""
    assert InputType.WORD.value == "word"
    assert InputType.LINE.value == "line"
    assert InputType.TEXT.value == "text"
    assert InputType.PATH.value == "path"
    assert InputType.INT.value == "int"
    assert InputType.BOOL.value == "bool"
    assert InputType.FLOAT.value == "float"


# Tests for InputArg.validate_and_convert


def test_input_arg_word_rejects_whitespace() -> None:
    """Test that word type rejects values with whitespace."""
    arg = InputArg(name="test", type=InputType.WORD)
    with pytest.raises(XPromptValidationError, match="expects word"):
        arg.validate_and_convert("hello world")
    with pytest.raises(XPromptValidationError, match="expects word"):
        arg.validate_and_convert("hello\tworld")
    with pytest.raises(XPromptValidationError, match="expects word"):
        arg.validate_and_convert("hello\nworld")


def test_input_arg_line_rejects_newlines() -> None:
    """Test that line type rejects values with newlines."""
    arg = InputArg(name="test", type=InputType.LINE)
    with pytest.raises(XPromptValidationError, match="expects line"):
        arg.validate_and_convert("hello\nworld")
    with pytest.raises(XPromptValidationError, match="expects line"):
        arg.validate_and_convert("line1\nline2\nline3")


def test_input_arg_path_rejects_whitespace() -> None:
    """Test that path type rejects values with whitespace."""
    arg = InputArg(name="test", type=InputType.PATH)
    with pytest.raises(XPromptValidationError, match="expects path"):
        arg.validate_and_convert("/path/with spaces/file.txt")


def test_input_arg_path_rejects_nonexistent() -> None:
    """Test that path type rejects non-existent paths."""
    arg = InputArg(name="test", type=InputType.PATH)
    with pytest.raises(XPromptValidationError, match="does not exist"):
        arg.validate_and_convert("/nonexistent/path/that/does/not/exist.txt")


def test_input_arg_float_invalid_raises_error() -> None:
    """Test that invalid float raises error."""
    arg = InputArg(name="ratio", type=InputType.FLOAT)
    with pytest.raises(XPromptValidationError, match="expects float"):
        arg.validate_and_convert("not_a_float")


def test_input_arg_bool_invalid_raises_error() -> None:
    """Test that invalid bool raises error."""
    arg = InputArg(name="enabled", type=InputType.BOOL)
    with pytest.raises(XPromptValidationError, match="expects bool"):
        arg.validate_and_convert("maybe")
    with pytest.raises(XPromptValidationError, match="expects bool"):
        arg.validate_and_convert("")


def test_input_arg_default_type_is_line() -> None:
    """Test that default type is LINE."""
    arg = InputArg(name="test")
    assert arg.type == InputType.LINE


def test_input_arg_default_is_unset() -> None:
    """Test that default value is UNSET when not specified."""
    arg = InputArg(name="test")
    assert arg.default is UNSET


def test_input_arg_with_default_value() -> None:
    """Test InputArg with a default value."""
    arg = InputArg(name="count", type=InputType.INT, default=10)
    assert arg.default == 10


# Tests for XPrompt


def test_xprompt_basic_construction() -> None:
    """Test basic XPrompt construction."""
    xp = XPrompt(name="test", content="Hello world")
    assert xp.name == "test"
    assert xp.content == "Hello world"
    assert xp.inputs == []
    assert xp.source_path is None


def test_xprompt_with_inputs() -> None:
    """Test XPrompt with input definitions."""
    inputs = [
        InputArg(name="name", type=InputType.LINE),
        InputArg(name="count", type=InputType.INT, default=5),
    ]
    xp = XPrompt(name="test", content="Hello {{ name }}", inputs=inputs)
    assert len(xp.inputs) == 2
    assert xp.inputs[0].name == "name"
    assert xp.inputs[1].name == "count"
    assert xp.inputs[1].default == 5


def test_xprompt_with_source_path() -> None:
    """Test XPrompt with source path."""
    xp = XPrompt(name="test", content="content", source_path="/path/to/file.md")
    assert xp.source_path == "/path/to/file.md"


# Tests for xprompt_to_workflow


def test_xprompt_to_workflow_preserves_source_path() -> None:
    """Test that conversion preserves source path."""
    xp = XPrompt(name="test", content="test content", source_path="/path/to/test.md")
    workflow = xprompt_to_workflow(xp)

    assert workflow.source_path == "/path/to/test.md"


# Tests for create_anonymous_workflow


def test_create_anonymous_workflow_multiline_query() -> None:
    """Test anonymous workflow with multiline query."""
    query = """Please review this code:

def foo():
    pass"""
    workflow = create_anonymous_workflow(query)

    assert workflow.steps[0].agent == query
