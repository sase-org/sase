"""Tests for xprompt.loader shortform syntax parsing."""

from sase.xprompt.loader_parsing import (
    _normalize_schema_properties,
    _parse_shortform_output,
    parse_output_from_front_matter,
)

# Tests for _parse_shortform_input_value


# Tests for parse_shortform_inputs


# Tests for _parse_shortform_output


def test_parse_shortform_output_array_nullable_field() -> None:
    """Test that default: null produces a nullable type in array format."""
    output = _parse_shortform_output(
        [
            {
                "name": "word",
                "parent": {"type": "word", "default": None},
            }
        ]
    )
    assert output.type == "json_schema"
    items = output.schema["items"]
    assert items["properties"]["parent"]["type"] == ["word", "null"]
    # name has no default, so it's required; parent has default null, not required
    assert "name" in items["required"]
    assert "parent" not in items["required"]


def test_parse_shortform_output_object_nullable_field() -> None:
    """Test that default: null produces a nullable type in object format."""
    output = _parse_shortform_output(
        {
            "name": "word",
            "parent": {"type": "word", "default": None},
        }
    )
    assert output.type == "json_schema"
    assert output.schema["properties"]["parent"]["type"] == ["word", "null"]
    assert output.schema["properties"]["name"]["type"] == "word"


def test_parse_shortform_output_array_empty() -> None:
    """Test parsing empty array shortform."""
    output = _parse_shortform_output([])
    assert output.type == "json_schema"
    assert output.schema["type"] == "array"


def test_parse_shortform_output_array_non_dict_item() -> None:
    """Test parsing array shortform with non-dict item."""
    output = _parse_shortform_output(["not a dict"])  # type: ignore[list-item]
    assert output.type == "json_schema"
    assert output.schema["type"] == "array"
    assert output.schema["items"] == {}


# Tests for _parse_inputs_from_front_matter with shortform


# Tests for parse_output_from_front_matter


def test_parse_output_from_front_matter_shortform_array() -> None:
    """Test parsing shortform array output."""
    output = parse_output_from_front_matter(
        [
            {
                "name": "word",
                "description": "text",
            }
        ]
    )
    assert output is not None
    assert output.type == "json_schema"
    assert output.schema["type"] == "array"
    assert output.schema["items"]["properties"]["name"]["type"] == "word"


def test_parse_output_from_front_matter_empty() -> None:
    """Test parsing empty output returns None."""
    assert parse_output_from_front_matter(None) is None
    assert parse_output_from_front_matter({}) is None


def test_parse_output_distinguishes_longform_from_shortform() -> None:
    """Test that parser correctly distinguishes longform from shortform.

    Longform has 'type' as output format type (e.g., 'json_schema'),
    while shortform has 'type' as field types (e.g., 'word', 'text').
    """
    # This is longform because it has 'type' + 'schema' keys
    longform = parse_output_from_front_matter(
        {
            "type": "json_schema",
            "schema": {"properties": {}},
        }
    )
    assert longform is not None
    assert longform.type == "json_schema"

    # This is shortform because 'type' is a field with no 'schema' key
    shortform = parse_output_from_front_matter(
        {
            "type": "word",  # This is a field named 'type'
            "name": "line",
        }
    )
    assert shortform is not None
    assert "properties" in shortform.schema


# Tests for _normalize_schema_properties


def test_normalize_schema_properties_non_dict() -> None:
    """Test that non-dict input is returned as-is."""
    result = _normalize_schema_properties("not a dict")  # type: ignore[arg-type]
    assert result == "not a dict"


def test_normalize_schema_properties_with_items() -> None:
    """Test normalizing array items."""
    schema = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
            },
        },
    }
    result = _normalize_schema_properties(schema)
    assert result["items"]["properties"]["name"]["type"] == "string"
