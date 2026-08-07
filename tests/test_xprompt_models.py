"""Tests for the xprompt.models module."""

import pytest
from sase.xprompt.models import (
    UNSET,
    InputArg,
    InputChoice,
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
    assert InputType.ENUM.value == "enum"


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


def test_input_arg_path_accepts_spaces() -> None:
    """Test that path type accepts single-line values with spaces."""
    arg = InputArg(name="test", type=InputType.PATH)
    result = arg.validate_and_convert("/path/with spaces/file.txt")
    assert result == "/path/with spaces/file.txt"


def test_input_arg_path_rejects_newlines() -> None:
    """Test that path type rejects multiline values."""
    arg = InputArg(name="test", type=InputType.PATH)
    with pytest.raises(XPromptValidationError, match="single-line path"):
        arg.validate_and_convert("/path/with\nnewline/file.txt")


def test_input_arg_path_accepts_nonexistent() -> None:
    """Test that path type accepts non-existent paths (no existence check)."""
    arg = InputArg(name="test", type=InputType.PATH)
    result = arg.validate_and_convert("/nonexistent/path/that/does/not/exist.txt")
    assert result == "/nonexistent/path/that/does/not/exist.txt"


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


def test_input_arg_enum_accepts_declared_value() -> None:
    """Test that enum type accepts an exact declared choice value."""
    arg = InputArg(
        name="mode",
        type=InputType.ENUM,
        choices=(InputChoice(value="fast"), InputChoice(value="slow")),
    )
    assert arg.validate_and_convert("fast") == "fast"


def test_input_arg_enum_rejects_undeclared_value_listing_allowed() -> None:
    """Test that enum type rejects an undeclared value, listing allowed values."""
    arg = InputArg(
        name="mode",
        type=InputType.ENUM,
        choices=(InputChoice(value="fast"), InputChoice(value="slow")),
    )
    with pytest.raises(XPromptValidationError, match="fast, slow") as excinfo:
        arg.validate_and_convert("turbo")
    assert "mode" in str(excinfo.value)


def test_input_arg_enum_is_case_sensitive_and_ignores_labels() -> None:
    """Test that enum matching is exact on value, not case-folded or by label."""
    arg = InputArg(
        name="mode",
        type=InputType.ENUM,
        choices=(InputChoice(value="fast", label="Fast mode"),),
    )
    with pytest.raises(XPromptValidationError):
        arg.validate_and_convert("Fast")
    with pytest.raises(XPromptValidationError):
        arg.validate_and_convert("Fast mode")


def test_input_arg_enum_without_choices_raises() -> None:
    """Test that declaring type=enum with no choices raises."""
    with pytest.raises(XPromptValidationError, match="no choices"):
        InputArg(name="mode", type=InputType.ENUM)


def test_input_arg_choices_on_non_enum_type_raises() -> None:
    """Test that declaring choices on a non-enum type raises."""
    with pytest.raises(XPromptValidationError, match="not type 'enum'"):
        InputArg(name="mode", type=InputType.WORD, choices=(InputChoice(value="fast"),))


def test_input_arg_duplicate_choice_values_raises() -> None:
    """Test that two choices sharing a value raises."""
    with pytest.raises(XPromptValidationError, match="duplicate choice"):
        InputArg(
            name="mode",
            type=InputType.ENUM,
            choices=(InputChoice(value="fast"), InputChoice(value="fast")),
        )


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


def test_xprompt_to_workflow_preserves_description() -> None:
    xp = XPrompt(name="test", content="test content", description="Test prompt")
    workflow = xprompt_to_workflow(xp)

    assert workflow.description == "Test prompt"


# Tests for create_anonymous_workflow


def test_create_anonymous_workflow_multiline_query() -> None:
    """Test anonymous workflow with multiline query."""
    query = """Please review this code:

def foo():
    pass"""
    workflow = create_anonymous_workflow(query)

    assert workflow.steps[0].agent == query
