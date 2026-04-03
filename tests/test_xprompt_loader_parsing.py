"""Tests for xprompt.loader parsing functions."""

from sase.xprompt.loader_parsing import (
    _parse_shortform_output,
    parse_inputs_from_front_matter,
    parse_yaml_front_matter,
)

# Tests for parse_yaml_front_matter


def testparse_yaml_front_matter_opening_without_closing() -> None:
    """Test content with opening --- but no closing ---."""
    content = """---
name: test
No closing marker"""
    front_matter, body = parse_yaml_front_matter(content)

    assert front_matter is None
    assert body == content


def testparse_yaml_front_matter_empty_front_matter() -> None:
    """Test empty front matter section."""
    content = """---
---
Body here"""
    front_matter, body = parse_yaml_front_matter(content)

    assert front_matter == {}
    assert body == "Body here"


# Tests for parse_inputs_from_front_matter


def test_parse_inputs_empty_list() -> None:
    """Test with empty list."""
    inputs = parse_inputs_from_front_matter([])
    assert inputs == []


def test_parse_inputs_skips_invalid_items() -> None:
    """Test that items without name are skipped."""
    input_list = [
        {"name": "valid"},
        {"type": "int"},  # Missing name
        "not a dict",  # Wrong type (intentionally testing edge case)
        {"name": "also_valid"},
    ]
    inputs = parse_inputs_from_front_matter(input_list)  # type: ignore[arg-type]

    assert len(inputs) == 2
    assert inputs[0].name == "valid"
    assert inputs[1].name == "also_valid"


# Tests for _parse_shortform_output


def test_shortform_output_spec_field_with_empty_string_default_is_nullable() -> None:
    """Field with default: '' should produce nullable type."""
    spec = _parse_shortform_output(
        [{"name": "word", "parent": {"type": "word", "default": ""}}]
    )
    props = spec.schema["items"]["properties"]
    assert props["parent"]["type"] == ["word", "null"]
    assert props["parent"]["default"] == ""


def test_shortform_output_spec_field_with_none_default_is_nullable() -> None:
    """Field with default: None (null) should produce nullable type."""
    spec = _parse_shortform_output(
        [{"name": "word", "parent": {"type": "word", "default": None}}]
    )
    props = spec.schema["items"]["properties"]
    assert props["parent"]["type"] == ["word", "null"]
    assert "default" not in props["parent"]


def test_shortform_output_spec_field_without_default_not_nullable() -> None:
    """Field without a default should NOT be nullable and should be required."""
    spec = _parse_shortform_output([{"name": "word", "parent": "word"}])
    props = spec.schema["items"]["properties"]
    assert props["parent"]["type"] == "word"
    assert "parent" in spec.schema["items"]["required"]
