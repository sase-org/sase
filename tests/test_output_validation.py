"""Tests for xprompt output validation module."""

import pytest
from sase.xprompt.models import OutputSpec
from sase.xprompt.output_validation import (
    OutputValidationError,
    _validate_semantic_type,
    extract_semantic_type_hints,
    extract_structured_content,
    generate_format_instructions,
    validate_against_schema,
    validate_response,
)


class TestExtractStructuredContent:
    """Tests for extract_structured_content function."""

    def test_yaml_list_is_accepted(self) -> None:
        """Test that YAML list is accepted."""
        response = "- item1\n- item2\n- item3"
        data, format_type = extract_structured_content(response)
        assert data == ["item1", "item2", "item3"]
        assert format_type == "yaml"

    def test_bare_json_language_prefix(self) -> None:
        """Test that a bare 'json' line prefix (no code fence backticks) is handled."""
        response = 'json\n{"key": "value"}'
        data, format_type = extract_structured_content(response)
        assert data == {"key": "value"}
        assert format_type == "json"

    def test_bare_yaml_language_prefix(self) -> None:
        """Test that a bare 'yaml' line prefix (no code fence backticks) is handled."""
        response = "yaml\nkey: value\nother: 42"
        data, format_type = extract_structured_content(response)
        assert data == {"key": "value", "other": 42}
        assert format_type == "yaml"


class TestValidateAgainstSchema:
    """Tests for validate_against_schema function."""


class TestGenerateFormatInstructions:
    """Tests for generate_format_instructions function."""

    def test_returns_empty_for_unknown_type(self) -> None:
        """Test that empty string is returned for unknown types."""
        output_spec = OutputSpec(
            type="unknown_type",
            schema={"some": "schema"},
        )
        instructions = generate_format_instructions(output_spec)
        assert instructions == ""


class TestValidateResponse:
    """Tests for validate_response function."""

    def test_valid_response_passes(self) -> None:
        """Test that valid response passes validation."""
        output_spec = OutputSpec(
            type="json_schema",
            schema={
                "type": "object",
                "required": ["name"],
                "properties": {"name": {"type": "string"}},
            },
        )
        response = '```json\n{"name": "test"}\n```'
        data, error = validate_response(response, output_spec)
        assert data == {"name": "test"}
        assert error is None

    def test_invalid_response_returns_error(self) -> None:
        """Test that invalid response returns error message."""
        output_spec = OutputSpec(
            type="json_schema",
            schema={
                "type": "object",
                "required": ["name", "value"],
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "integer"},
                },
            },
        )
        response = '```json\n{"name": "test"}\n```'  # Missing 'value'
        data, error = validate_response(response, output_spec)
        assert data == {"name": "test"}
        assert error is not None
        assert "value" in error

    def test_non_json_schema_type_passes_through(self) -> None:
        """Test that non-json_schema type passes response through."""
        output_spec = OutputSpec(
            type="custom_type",
            schema={},
        )
        response = "This is just plain text"
        data, error = validate_response(response, output_spec)
        assert data == response
        assert error is None

    def test_unparseable_response_raises_error(self) -> None:
        """Test that unparseable response raises OutputValidationError."""
        output_spec = OutputSpec(
            type="json_schema",
            schema={"type": "object"},
        )
        response = "This is not valid JSON at all {{{invalid"
        with pytest.raises(OutputValidationError):
            validate_response(response, output_spec)


class TestSemanticTypeValidation:
    """Tests for semantic output type validation."""

    def test_validate_semantic_type_word_with_tab(self) -> None:
        """Test that word with tab fails validation."""
        result = _validate_semantic_type("hello\tworld", "word", "name")
        assert result is not None
        assert "expected word" in result

    def test_validate_semantic_type_path_valid(self) -> None:
        """Test that valid path passes validation."""
        result = _validate_semantic_type("/some/path/file.txt", "path", "file")
        assert result is None

    def test_validate_semantic_type_path_with_space(self) -> None:
        """Test that path with space fails validation."""
        result = _validate_semantic_type("/some path/file.txt", "path", "file")
        assert result is not None
        assert "expected path" in result
        assert "no spaces" in result

    def test_validate_semantic_type_string_no_validation(self) -> None:
        """Test that string type has no validation."""
        result = _validate_semantic_type("any content\nwith spaces", "string", "field")
        assert result is None


class TestConvertSemanticSchema:
    """Tests for _convert_semantic_schema_to_json_schema function."""


class TestValidateAgainstSchemaWithSemanticTypes:
    """Tests for validate_against_schema with semantic types."""

    def test_line_with_newline_fails(self) -> None:
        """Test that line with newline fails validation."""
        schema = {
            "type": "object",
            "properties": {
                "title": {"type": "line"},
            },
        }
        data = {"title": "Hello\nWorld"}
        is_valid, error = validate_against_schema(data, schema)
        assert is_valid is False
        assert error is not None
        assert "expected line" in error

    def test_int_type_with_invalid_string_keeps_string(self) -> None:
        """Test that int type with non-numeric string stays as string."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "int"},
            },
        }
        # String that can't be converted to int should fail validation
        data = {"count": "not a number"}
        is_valid, error = validate_against_schema(data, schema)
        # It should fail because "not a number" is not an integer
        assert is_valid is False

    def test_float_type_with_invalid_string_keeps_string(self) -> None:
        """Test that float type with non-numeric string stays as string."""
        schema = {
            "type": "object",
            "properties": {
                "value": {"type": "float"},
            },
        }
        # String that can't be converted to float should fail validation
        data = {"value": "not a float"}
        is_valid, error = validate_against_schema(data, schema)
        # It should fail because "not a float" is not a number
        assert is_valid is False


class TestExtractSemanticTypeHints:
    """Tests for extract_semantic_type_hints function."""

    def test_extract_path_hint(self) -> None:
        """Test extracting hint for path type."""
        schema = {
            "type": "object",
            "properties": {
                "file": {"type": "path"},
            },
        }
        hints = extract_semantic_type_hints(schema)
        assert len(hints) == 1
        assert "file" in hints[0]
        assert "valid path" in hints[0]

    def test_multiple_hints_from_nested_schema(self) -> None:
        """Test extracting multiple hints from nested schema."""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "word"},
                    "description": {"type": "text"},
                    "parent": {"type": "word"},
                },
            },
        }
        hints = extract_semantic_type_hints(schema)
        assert len(hints) == 2  # name and parent are word types
        names_mentioned = [h for h in hints if "name" in h]
        parent_mentioned = [h for h in hints if "parent" in h]
        assert len(names_mentioned) == 1
        assert len(parent_mentioned) == 1


class TestConvertSemanticSchemaListTypes:
    """Tests for _convert_semantic_schema_to_json_schema with list types."""


class TestValidateAgainstSchemaNullable:
    """Tests for validate_against_schema with nullable fields."""

    def test_nullable_array_items(self) -> None:
        """Test nullable fields within array items."""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "word"},
                    "parent": {"type": ["word", "null"]},
                },
            },
        }
        data = [
            {"name": "child1", "parent": "root"},
            {"name": "root", "parent": None},
        ]
        is_valid, error = validate_against_schema(data, schema)
        assert is_valid is True
        assert error is None

    def test_null_with_empty_string_default_passes(self) -> None:
        """Test that null passes for a field with default: ''."""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "word"},
                    "parent": {"type": ["word", "null"], "default": ""},
                },
            },
        }
        data = [{"name": "child1", "parent": None}]
        is_valid, error = validate_against_schema(data, schema)
        assert is_valid is True
        assert error is None

    def test_null_with_default_none_passes(self) -> None:
        """Test that null passes for a field with default: None (null)."""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "word"},
                    "parent": {"type": ["word", "null"]},
                },
            },
        }
        data = [{"name": "root", "parent": None}]
        is_valid, error = validate_against_schema(data, schema)
        assert is_valid is True
        assert error is None

    def test_null_without_default_fails(self) -> None:
        """Test that null fails for a required field without a default."""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "word"},
                },
            },
        }
        data = [{"name": None}]
        is_valid, error = validate_against_schema(data, schema)
        assert is_valid is False
        assert error is not None

    def test_null_normalized_to_default_value(self) -> None:
        """Test that null is replaced with the default before validation."""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "word"},
                    "parent": {"type": ["word", "null"], "default": ""},
                },
            },
        }
        data = [{"name": "child1", "parent": None}]
        is_valid, error = validate_against_schema(data, schema)
        assert is_valid is True
        # Verify normalization happened in-place
        assert data[0]["parent"] == ""


class TestExtractSemanticTypeHintsNullable:
    """Tests for extract_semantic_type_hints with nullable types."""

    def test_nullable_word_hint_includes_or_null(self) -> None:
        """Test that nullable word type hint includes 'or null'."""
        schema = {
            "type": "object",
            "properties": {
                "parent": {"type": ["word", "null"]},
            },
        }
        hints = extract_semantic_type_hints(schema)
        assert len(hints) == 1
        assert "parent" in hints[0]
        assert "single word" in hints[0]
        assert "or null" in hints[0]


class TestGenerateFormatInstructionsWithSemanticTypes:
    """Tests for generate_format_instructions with semantic types."""

    def test_includes_semantic_constraints(self) -> None:
        """Test that format instructions include semantic type constraints."""
        output_spec = OutputSpec(
            type="json_schema",
            schema={
                "type": "object",
                "properties": {
                    "name": {"type": "word"},
                    "title": {"type": "line"},
                },
            },
        )
        instructions = generate_format_instructions(output_spec)
        assert "FIELD CONSTRAINTS" in instructions
        assert "name" in instructions
        assert "single word" in instructions
        assert "title" in instructions
        assert "single line" in instructions

    def test_no_constraints_section_when_no_semantic_types(self) -> None:
        """Test that FIELD CONSTRAINTS is omitted when no semantic types."""
        output_spec = OutputSpec(
            type="json_schema",
            schema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
            },
        )
        instructions = generate_format_instructions(output_spec)
        assert "FIELD CONSTRAINTS" not in instructions
