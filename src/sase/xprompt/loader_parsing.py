"""XPrompt parsing utilities for inputs, outputs, and front matter."""

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tags import XPromptTag

import yaml  # type: ignore[import-untyped]

from .models import UNSET, InputArg, InputType, OutputSpec, XPrompt
from .tags import parse_tags


def parse_yaml_front_matter(content: str) -> tuple[dict[str, Any] | None, str]:
    """Parse YAML front matter delimited by --- lines.

    Args:
        content: The full file content.

    Returns:
        Tuple of (front_matter_dict, body_content).
        front_matter_dict is None if no front matter found.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, content

    # Find the closing ---
    end_index = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = i
            break

    if end_index == -1:
        # No closing ---, treat as no front matter
        return None, content

    # Extract and parse YAML
    yaml_content = "\n".join(lines[1:end_index])
    try:
        front_matter = yaml.safe_load(yaml_content)
        if not isinstance(front_matter, dict):
            front_matter = {}
    except yaml.YAMLError:
        # Invalid YAML, treat as no front matter
        return None, content

    # Body is everything after the closing ---
    body = "\n".join(lines[end_index + 1 :])
    # Remove leading newline if present (common after front matter)
    if body.startswith("\n"):
        body = body[1:]

    return front_matter, body


def parse_input_type(type_str: str) -> InputType:
    """Parse an input type string to InputType enum.

    Args:
        type_str: The type string (e.g., "word", "line", "text", "path", "int").

    Returns:
        The corresponding InputType enum value.
    """
    type_map = {
        "word": InputType.WORD,
        "line": InputType.LINE,
        "text": InputType.TEXT,
        "path": InputType.PATH,
        "int": InputType.INT,
        "integer": InputType.INT,
        "bool": InputType.BOOL,
        "boolean": InputType.BOOL,
        "float": InputType.FLOAT,
    }
    return type_map.get(type_str.lower(), InputType.LINE)


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


def parse_shortform_inputs(
    input_dict: Mapping[str, str | dict[str, Any]],
) -> list[InputArg]:
    """Parse shortform input dict to list of InputArg.

    Args:
        input_dict: Dict mapping name to type string or dict with type/default.
            Example: {"diff_path": "path", "bug_flag": {"type": "line", "default": ""}}

    Returns:
        List of InputArg objects.
    """
    inputs: list[InputArg] = []
    for name, value in input_dict.items():
        type_str, default = _parse_shortform_input_value(value)
        inputs.append(
            InputArg(
                name=name,
                type=parse_input_type(type_str),
                default=default,
            )
        )
    return inputs


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


def parse_inputs_from_front_matter(
    input_data: list[dict[str, Any]] | dict[str, str | dict[str, Any]] | None,
) -> list[InputArg]:
    """Parse input definitions from front matter.

    Supports both longform (list of dicts) and shortform (dict) syntax.

    Args:
        input_data: Either a list of input dicts (longform) or a dict (shortform).
            Longform: [{"name": "foo", "type": "word", "default": ""}]
            Shortform: {"foo": "word", "bar": {"type": "line", "default": ""}}

    Returns:
        List of InputArg objects.
    """
    if not input_data:
        return []

    # Handle shortform dict syntax
    if isinstance(input_data, dict):
        return parse_shortform_inputs(input_data)

    # Handle longform list syntax
    inputs: list[InputArg] = []
    for item in input_data:
        if not isinstance(item, dict) or "name" not in item:
            continue

        name = str(item["name"])
        type_str = str(item.get("type", "line"))
        default = item.get("default", UNSET)

        inputs.append(
            InputArg(
                name=name,
                type=parse_input_type(type_str),
                default=default,
            )
        )

    return inputs


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


def parse_xprompt_entries(
    entries: dict[str, Any], source_path: str
) -> dict[str, XPrompt]:
    """Parse a dict of xprompt entries into XPrompt objects.

    Supports both simple string format and structured dict format:

    Simple format:
        foo: "Content here"

    Structured format (with inputs):
        bar:
            input: {name: word, count: {type: int, default: 0}}
            content: "Hello {{ name }}, count is {{ count }}"

    Args:
        entries: Dictionary mapping xprompt names to string content or
            structured dicts with input/content keys.
        source_path: Source identifier for the xprompts (e.g., file path or "config").

    Returns:
        Dictionary mapping xprompt name to XPrompt object.
    """
    xprompts: dict[str, XPrompt] = {}

    for name, value in entries.items():
        if not isinstance(name, str):
            continue

        if isinstance(value, str):
            # Simple string content (no arguments)
            content = value
            inputs: list[InputArg] = []
            tags: frozenset[XPromptTag] = frozenset()
            snippet: str | bool | None = None
            description: str | None = None
            skill: bool | list[str] | None = None
            keywords: list[str] = []
        elif isinstance(value, dict):
            # Structured xprompt with input/content
            content = value.get("content", "")
            if not isinstance(content, str):
                continue
            inputs = parse_inputs_from_front_matter(value.get("input"))
            tags = parse_tags(value.get("tags"))
            snippet = value.get("snippet")
            description = value.get("description")
            skill = value.get("skill")
            keywords = value.get("keywords", [])
        else:
            continue

        xprompts[name] = XPrompt(
            name=name,
            content=content,
            inputs=inputs,
            source_path=source_path,
            tags=tags,
            snippet=snippet,
            description=description,
            skill=skill,
            keywords=keywords,
        )

    return xprompts
