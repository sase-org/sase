"""Tests for xprompt.loader parsing functions."""

from sase.xprompt.loader_parsing import (
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
