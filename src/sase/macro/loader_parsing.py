"""Macro parsing utilities for inputs, outputs, and front matter."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .tags import MacroTag

import yaml  # type: ignore[import-untyped]

from .models import (
    UNSET,
    InputArg,
    InputChoice,
    InputType,
    OutputSpec,
    Macro,
    MacroValidationError,
)
from .tags import parse_tags
from sase.core.rust import require_rust_binding


@dataclass(frozen=True)
class ResolvedInputType:
    """Python view of one type resolved by the Rust input-type catalog."""

    base: InputType
    named_type: str | None
    value_role: str | None
    choices: tuple[InputChoice, ...] = ()
    warnings: tuple[str, ...] = ()


class LocalMacroNameError(ValueError):
    """Raised when a local macro name does not start with ``_``."""


def parse_yaml_front_matter_with_error(
    content: str,
) -> tuple[dict[str, Any] | None, str, yaml.YAMLError | None]:
    """Parse YAML front matter delimited by --- lines.

    Args:
        content: The full file content.

    Returns:
        Tuple of (front_matter_dict, body_content, parse_error).
        front_matter_dict is None if no front matter found.
    """
    lines = content.split("\n")
    if not lines or lines[0].strip() != "---":
        return None, content, None

    # Find the closing ---
    end_index = -1
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_index = i
            break

    if end_index == -1:
        # No closing ---, treat as no front matter
        return None, content, None

    # Extract and parse YAML
    yaml_content = "\n".join(lines[1:end_index])
    try:
        front_matter = yaml.safe_load(yaml_content)
        if not isinstance(front_matter, dict):
            front_matter = {}
    except yaml.YAMLError as exc:
        # Invalid YAML, treat as no front matter
        return None, content, exc

    # Body is everything after the closing ---
    body = "\n".join(lines[end_index + 1 :])
    # Remove leading newline if present (common after front matter)
    if body.startswith("\n"):
        body = body[1:]

    return front_matter, body, None


def parse_yaml_front_matter(content: str) -> tuple[dict[str, Any] | None, str]:
    """Parse YAML front matter delimited by --- lines.

    Invalid YAML preserves the historical fallback of treating the full content
    as plain body text.
    """
    front_matter, body, _error = parse_yaml_front_matter_with_error(content)
    return front_matter, body


def parse_input_type(
    raw: Any,
    *,
    name: str = "input",
    source_path: str | None = None,
) -> ResolvedInputType:
    """Resolve a raw YAML type through the shared Rust catalog.

    Unknown names keep their historical ``line`` fallback only while the
    ``strict_macro_input_types`` sunset flag is disabled. Deprecated spellings
    are accepted and surfaced as load warnings regardless of that flag.
    """
    try:
        resolved = require_rust_binding("resolve_input_type")(
            {"name": name, "raw": raw}
        )
    except ValueError as exc:
        message = str(exc)
        if "unknown type" in message.casefold():
            from sase.feature_flags import FeatureFlag, current_flags

            if not current_flags().enabled(FeatureFlag.strict_macro_input_types):
                return ResolvedInputType(
                    base=InputType.LINE,
                    named_type=None,
                    value_role=None,
                )
        raise MacroValidationError(message) from None

    choices = tuple(
        InputChoice(
            value=str(item["value"]),
            label=None if item.get("label") is None else str(item["label"]),
            description=(
                None if item.get("description") is None else str(item["description"])
            ),
        )
        for item in resolved.get("choices", [])
    )
    warnings: tuple[str, ...] = ()
    if resolved.get("deprecated"):
        warnings = (
            f"input `{name}` uses deprecated type `string`; use `line` instead",
        )

    result = ResolvedInputType(
        base=InputType(str(resolved["base"])),
        named_type=resolved.get("named_type"),
        value_role=resolved.get("value_role"),
        choices=choices,
        warnings=warnings,
    )
    if source_path is not None:
        from .load_issues import record_load_issue

        for warning in result.warnings:
            record_load_issue(source_path, warning, kind="input_type_warning")
    return result


def _parse_input_choices(
    raw: Any,
    name: str,
    *,
    source_path: str | None = None,
) -> tuple[InputChoice, ...]:
    """Parse an enum input's ``choices`` value into :class:`InputChoice` tuples.

    Args:
        raw: A raw YAML list of scalar values or ``{value, label, description}``
            mappings. Values are passed to Rust without Python coercion.
        name: The owning input's name, used in error messages.

    Returns:
        Tuple of :class:`InputChoice` objects, in declared order.

    Raises:
        MacroValidationError: If Rust reports invalid choices or choice values.
    """
    try:
        result = require_rust_binding("validate_enum_choices")({"items": raw})
    except ValueError as exc:
        raise MacroValidationError(str(exc)) from None
    choices = tuple(
        InputChoice(
            value=str(item["value"]),
            label=None if item.get("label") is None else str(item["label"]),
            description=(
                None if item.get("description") is None else str(item["description"])
            ),
        )
        for item in result.get("choices", [])
    )
    first_error: str | None = None
    for issue in result.get("issues", []):
        message = str(issue.get("message", "invalid enum choice"))
        if issue.get("severity") == "error":
            first_error = first_error or message
        elif issue.get("severity") == "warning" and source_path is not None:
            from .load_issues import record_load_issue

            record_load_issue(source_path, message, kind="input_type_warning")
    if first_error is not None:
        raise MacroValidationError(first_error)
    if not isinstance(raw, list) or not raw:
        raise MacroValidationError(
            f"Argument '{name}' choices must be a non-empty list"
        )
    return choices


def parse_input_definition(
    *,
    name: str,
    type_raw: Any,
    default: Any,
    description: str | None,
    repeatable: bool,
    choices_raw: Any,
    source_path: str | None,
) -> InputArg:
    """Build one input definition from raw frontmatter values."""
    resolved = parse_input_type(
        type_raw,
        name=name,
        source_path=source_path,
    )
    choices = resolved.choices
    if choices_raw is not None:
        choices = _parse_input_choices(
            choices_raw,
            name,
            source_path=source_path,
        )
    _validate_enum_default(name, default, choices, resolved.base)
    return InputArg(
        name=name,
        type=resolved.base,
        default=default,
        description=description,
        repeatable=repeatable,
        choices=choices,
        named_type=resolved.named_type,
        value_role=resolved.value_role,
    )


def _validate_enum_default(
    name: str,
    default: Any,
    choices: tuple[InputChoice, ...],
    input_type: InputType,
) -> None:
    if (
        input_type is not InputType.ENUM
        or not choices
        or default is UNSET
        or default is None
    ):
        return
    if not isinstance(default, str):
        scalar_name = (
            "a boolean"
            if isinstance(default, bool)
            else "an int"
            if isinstance(default, int)
            else "a float"
            if isinstance(default, float)
            else type(default).__name__
        )
        raise MacroValidationError(
            f"Argument '{name}' default arrived as {scalar_name} and must be a quoted choice"
        )
    values = tuple(choice.value for choice in choices)
    if default in values:
        return
    allowed = " | ".join(values) if len(values) <= 8 else f"{len(values)} choices"
    raise MacroValidationError(f"default `{default}` is not one of {allowed}")


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


def _parse_shortform_input_metadata(
    name: str,
    value: Any,
) -> tuple[Any, Any, str | None, bool, Any]:
    """Parse raw shortform metadata without coercing YAML input-type scalars."""
    if isinstance(value, dict):
        type_str = value.get("type", "line")
        default = value.get("default", UNSET)
        description_value = value.get("description")
        description = None if description_value is None else str(description_value)
        repeatable = value.get("repeatable", False) is True
        choices_value = value.get("choices")
        return type_str, default, description, repeatable, choices_value

    return value, UNSET, None, False, None


def parse_shortform_inputs(
    input_dict: Mapping[str, Any],
    *,
    source_path: str | None = None,
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
        type_raw, default, description, repeatable, choices_raw = (
            _parse_shortform_input_metadata(name, value)
        )
        inputs.append(
            parse_input_definition(
                name=name,
                type_raw=type_raw,
                default=default,
                description=description,
                repeatable=repeatable,
                choices_raw=choices_raw,
                source_path=source_path,
            )
        )
    from .input_binding import validate_repeatable_input_order

    validate_repeatable_input_order(inputs)
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
    input_data: list[dict[str, Any]] | dict[str, Any] | None,
    *,
    source_path: str | None = None,
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
        return parse_shortform_inputs(input_data, source_path=source_path)

    # Handle longform list syntax
    inputs: list[InputArg] = []
    for item in input_data:
        if not isinstance(item, dict) or "name" not in item:
            continue

        name = str(item["name"])
        type_raw = item.get("type", "line")
        default = item.get("default", UNSET)
        description_value = item.get("description")
        description = None if description_value is None else str(description_value)
        repeatable = item.get("repeatable", False) is True
        choices_value = item.get("choices")
        inputs.append(
            parse_input_definition(
                name=name,
                type_raw=type_raw,
                default=default,
                description=description,
                repeatable=repeatable,
                choices_raw=choices_value,
                source_path=source_path,
            )
        )

    from .input_binding import validate_repeatable_input_order

    validate_repeatable_input_order(inputs)
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


def parse_macro_entries(entries: dict[str, Any], source_path: str) -> dict[str, Macro]:
    """Parse a dict of macro entries into Macro objects.

    Supports both simple string format and structured dict format:

    Simple format:
        foo: "Content here"

    Structured format (with inputs):
        bar:
            input: {name: word, count: {type: int, default: 0}}
            content: "Hello {{ name }}, count is {{ count }}"

    Args:
        entries: Dictionary mapping macro names to string content or
            structured dicts with input/content keys.
        source_path: Source identifier for the macros (e.g., file path or "config").

    Returns:
        Dictionary mapping macro name to Macro object.
    """
    macros: dict[str, Macro] = {}

    for name, value in entries.items():
        if not isinstance(name, str):
            from .load_issues import record_load_issue

            record_load_issue(
                source_path,
                f"skipped macro entry with non-string name: {name!r}",
                kind="config",
            )
            continue

        if isinstance(value, str):
            # Simple string content (no arguments)
            content = value
            inputs: list[InputArg] = []
            tags: frozenset[MacroTag] = frozenset()
            snippet: str | bool | None = None
            description: str | None = None
            skill: bool | list[str] | None = None
            log_skill_use = True
            local_macros: dict[str, Macro] = {}
        elif isinstance(value, dict):
            # Structured macro with input/content
            content = value.get("content", "")
            if not isinstance(content, str):
                from .load_issues import record_load_issue

                record_load_issue(
                    source_path,
                    f"skipped macro entry {name!r}: content must be a string",
                    kind="config",
                )
                continue
            try:
                inputs = parse_inputs_from_front_matter(
                    value.get("input"),
                    source_path=source_path,
                )
                tags = parse_tags(value.get("tags"))
                snippet = value.get("snippet")
                description = value.get("description")
                skill = value.get("skill")
                log_skill_use = value.get("log_skill_use", True)
                from sase.legacy_xprompt_syntax import normalize_frontmatter_macros

                local_entries = normalize_frontmatter_macros(
                    value,
                    source=source_path,
                )
                local_macros = (
                    parse_local_macro_entries(local_entries, source_path)
                    if local_entries
                    else {}
                )
            except MacroValidationError as exc:
                from .load_issues import record_load_issue

                record_load_issue(source_path, exc, kind="input_type")
                continue
        else:
            from .load_issues import record_load_issue

            record_load_issue(
                source_path,
                f"skipped macro entry {name!r}: value must be a string or mapping",
                kind="config",
            )
            continue

        macro_def = Macro(
            name=name,
            content=content,
            inputs=inputs,
            source_path=source_path,
            tags=tags,
            snippet=snippet,
            description=description,
            skill=skill,
            log_skill_use=log_skill_use,
            local_macros=local_macros,
        )
        if _reject_reserved_memory_namespace(macro_def, source_path):
            continue
        # A skill needs a Markdown file in a canonical skill directory for
        # generation to render from, so a config entry can never be one.
        if _reject_config_skill(macro_def, source_path):
            continue
        macros[name] = macro_def

    return macros


def _reject_config_skill(macro_def: Macro, source_path: str) -> bool:
    """Drop a config-defined entry that declares ``skill:``."""
    if not macro_def.skill:
        return False

    from .loader_skills import config_skill_destination, reject_misplaced_skill

    return reject_misplaced_skill(
        macro_def,
        source=f"{source_path}:{macro_def.name}",
        migrate_to=config_skill_destination(),
    )


def _reject_reserved_memory_namespace(macro_def: Macro, source_path: str) -> bool:
    """Drop a config-defined entry that claims the macro-memory namespace."""
    from .reserved_namespaces import reject_reserved_memory_namespace

    return reject_reserved_memory_namespace(
        macro_def.name,
        source=f"{source_path}:{macro_def.name}",
    )


def _validate_local_macro_names(macros: dict[str, Macro]) -> None:
    """Raise if any local macro name does not start with ``_``."""
    for name in macros:
        if not name.startswith("_"):
            raise LocalMacroNameError(
                f"Local macro_def '{name}' must start with '_' (e.g. '_{name}')"
            )


def parse_local_macro_entries(
    entries: dict[str, Any], source_path: str
) -> dict[str, Macro]:
    """Parse local macro entries and enforce local-name scoping rules."""
    macros = parse_macro_entries(entries, source_path)
    _validate_local_macro_names(macros)
    return macros
