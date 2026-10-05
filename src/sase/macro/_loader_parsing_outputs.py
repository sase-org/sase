"""Macro output-spec parsing for front matter definitions."""

from typing import Any

from .models import (
    UNSET,
    OutputSpec,
)


def _parse_shortform_input_value(value: str | dict[str, Any]) -> tuple[str, Any]:
    """Parse shortform input value into (type, default).

    Args:
        value: Either a type string (e.g., "word") or a dict with 'type' and
            optional 'default' keys (e.g., {"type": "line", "default": ""}).

    Returns:
        Tuple of (type_str, default_value). default_value is UNSET if no default,
        None if the YAML value was explicitly null.
    """
    if isinstance(value, dict):
        type_str = str(value.get("type", "line"))
        default = value.get("default", UNSET)
        return type_str, default

    # Simple string type without default
    return str(value).strip(), UNSET


def _normalize_schema_properties(schema: dict[str, Any]) -> dict[str, Any]:
    """Expand shortform properties in a schema to standard JSON Schema format.

    Converts shortform like {"name": {"type": "word"}} to proper nested format.
    This handles both top-level properties and nested array items.

    Args:
        schema: The schema dict to normalize.

    Returns:
        Normalized schema dict.
    """
    if not isinstance(schema, dict):
        return schema

    result = dict(schema)

    # Handle properties
    if "properties" in result:
        result["properties"] = {
            name: _normalize_schema_properties(prop)
            for name, prop in result["properties"].items()
        }

    # Handle array items
    if "items" in result:
        result["items"] = _normalize_schema_properties(result["items"])

    return result


def _parse_shortform_output(output_data: dict[str, Any] | list[Any]) -> OutputSpec:
    """Convert shortform output syntax to OutputSpec.

    Shortform dict: {field: type} → OutputSpec with json_schema type
    Shortform list: [{field: type}] → OutputSpec with array schema

    Args:
        output_data: Either a dict like {"name": "word", "desc": "text"}
            or a list like [{"name": "word", "desc": {"type": "text", "default": ""}}].

    Returns:
        OutputSpec object.
    """
    if isinstance(output_data, list):
        # Array of objects syntax: [{name: word, desc: {type: text, default: ""}}]
        if not output_data:
            return OutputSpec(type="json_schema", schema={"type": "array", "items": {}})

        item_spec = output_data[0]
        if not isinstance(item_spec, dict):
            return OutputSpec(type="json_schema", schema={"type": "array", "items": {}})

        properties: dict[str, dict[str, Any]] = {}
        required: list[str] = []

        for field_name, field_value in item_spec.items():
            type_str, default = _parse_shortform_input_value(field_value)
            if default is not UNSET:
                prop: dict[str, Any] = {"type": [type_str, "null"]}
                if default is not None:
                    prop["default"] = default
                properties[field_name] = prop
            else:
                properties[field_name] = {"type": type_str}
                required.append(field_name)

        items_schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            items_schema["required"] = required

        return OutputSpec(
            type="json_schema",
            schema={
                "type": "array",
                "items": items_schema,
            },
        )
    else:
        # Object syntax: {name: word, desc: text}
        properties = {}
        for field_name, field_value in output_data.items():
            type_str, default = _parse_shortform_input_value(field_value)
            if default is not UNSET:
                prop = {"type": [type_str, "null"]}
                if default is not None:
                    prop["default"] = default
                properties[field_name] = prop
            else:
                properties[field_name] = {"type": type_str}

        return OutputSpec(
            type="json_schema",
            schema={
                "properties": properties,
            },
        )


def parse_output_from_front_matter(
    output_data: dict[str, Any] | list[Any] | None,
) -> OutputSpec | None:
    """Parse output specification from front matter.

    Supports both longform and shortform syntax.

    Longform:
        output:
          type: json_schema
          schema:
            properties:
              name: {type: word}

    Shortform (object):
        output: {name: word, desc: text}

    Shortform (array):
        output: [{name: word, desc: text = ""}]

    Args:
        output_data: The output data from YAML front matter.

    Returns:
        OutputSpec object if valid output specification found, None otherwise.
    """
    if not output_data:
        return None

    # Handle shortform list syntax: [{name: word, desc: text}]
    if isinstance(output_data, list):
        return _parse_shortform_output(output_data)

    # Check if this is longform (has 'type' and 'schema' keys) or shortform
    output_type = output_data.get("type")
    schema = output_data.get("schema")

    # Longform: has both 'type' and 'schema' keys, and 'type' is a string like "json_schema"
    if (
        output_type
        and isinstance(output_type, str)
        and schema
        and isinstance(schema, dict)
    ):
        return OutputSpec(type=output_type, schema=schema)

    # Raw JSON Schema: 'type' is a JSON Schema type keyword (e.g. "object", "array")
    # and the dict contains schema-specific keys like 'properties' or 'items'.
    # Treat the entire dict as the schema rather than falling through to shortform.
    _JSON_SCHEMA_TYPES = {
        "object",
        "array",
        "string",
        "number",
        "integer",
        "boolean",
        "null",
    }
    if (
        output_type
        and isinstance(output_type, str)
        and output_type in _JSON_SCHEMA_TYPES
        and ("properties" in output_data or "items" in output_data)
    ):
        return OutputSpec(type="json_schema", schema=output_data)

    # Shortform dict: {name: word, desc: text}
    # If 'type' is present but not a known longform type, treat as shortform
    return _parse_shortform_output(output_data)
