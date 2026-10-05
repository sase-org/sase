"""JSON Schema generation for the macro input-type catalog."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from sase.core.rust import require_rust_binding

PLUGIN_QUALIFIED_TYPE_PATTERN = r"^[A-Za-z0-9._-]+@[a-z0-9][a-z0-9_-]*$"

WORKFLOW_SCHEMA_RELPATH = "src/sase/macros/workflow.schema.json"
CONFIG_SCHEMA_RELPATH = "src/sase/config/sase.schema.json"


def _builtin_macro_input_type_catalog() -> list[dict[str, Any]]:
    """Return the builtin catalog rows from ``sase_core_rs``."""
    payload = require_rust_binding("macro_input_type_catalog")()
    if not isinstance(payload, list):
        raise TypeError("macro_input_type_catalog must return a list")
    return [dict(entry) for entry in payload]


def _advertised_input_type_names(
    catalog: Sequence[Mapping[str, Any]] | None = None,
) -> list[str]:
    """Return advertised catalog names and aliases in catalog order."""
    names: list[str] = []
    for entry in (
        catalog if catalog is not None else _builtin_macro_input_type_catalog()
    ):
        if not entry.get("advertised", True):
            continue
        name = str(entry["name"])
        names.append(name)
        aliases = entry.get("aliases") or []
        names.extend(str(alias) for alias in aliases)
    return names


def _macro_input_type_field_schema(
    catalog: Sequence[Mapping[str, Any]] | None = None,
    *,
    include_default: bool = True,
    shorthand: bool = False,
) -> dict[str, Any]:
    """Return the generated JSON Schema for an input ``type`` field."""
    resolved = (
        list(catalog) if catalog is not None else _builtin_macro_input_type_catalog()
    )
    advertised = _advertised_input_type_names(resolved)
    string_entry = next(
        (entry for entry in resolved if entry.get("name") == "string"), None
    )
    deprecated_of = "line"
    if string_entry is not None:
        deprecated_of = str(string_entry.get("deprecated_alias_of") or "line")
    schema: dict[str, Any] = {
        "type": "string",
        "description": (
            "Type shorthand (e.g., 'text', 'line')"
            if shorthand
            else "The expected type of the argument value"
        ),
        "anyOf": [
            {"enum": advertised},
            {
                "const": "string",
                "deprecated": True,
                "description": f"Deprecated alias of {deprecated_of}",
            },
            {
                "pattern": PLUGIN_QUALIFIED_TYPE_PATTERN,
                "description": "Plugin-qualified input type (`distribution@id`).",
            },
        ],
    }
    if include_default:
        schema["default"] = "line"
    return schema


def _macro_input_choices_schema() -> dict[str, Any]:
    """Return the generated JSON Schema for an input ``choices`` field."""
    return {
        "type": "array",
        "description": (
            "Closed set of allowed values for an enum input. Each item is a "
            "string or a {value, label, description} object."
        ),
        "items": {
            "oneOf": [
                {"type": "string", "minLength": 1},
                {
                    "type": "object",
                    "required": ["value"],
                    "additionalProperties": False,
                    "properties": {
                        "value": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Exact value a caller must supply",
                        },
                        "label": {
                            "type": "string",
                            "description": "Optional display text for the value",
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional longer help text for the value",
                        },
                    },
                },
            ]
        },
    }


def _repeatable_schema() -> dict[str, Any]:
    return {
        "type": "boolean",
        "description": (
            "Whether this final positional input consumes all remaining values"
        ),
        "default": False,
    }


# symvision: tools/sync_macro_input_schemas
def workflow_input_definitions_block(
    catalog: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the generated ``inputDefinitions`` workflow schema block."""
    resolved = (
        list(catalog) if catalog is not None else _builtin_macro_input_type_catalog()
    )
    type_field = _macro_input_type_field_schema(resolved)
    shorthand_type = _macro_input_type_field_schema(
        resolved, include_default=False, shorthand=True
    )
    object_type = _macro_input_type_field_schema(resolved, include_default=False)
    choices = _macro_input_choices_schema()
    return {
        "description": "Input argument definitions (array or object shorthand)",
        "oneOf": [
            {
                "type": "array",
                "description": "List of input argument definitions",
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "additionalProperties": False,
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": (
                                "The argument name (used for named args like "
                                "name=value)"
                            ),
                        },
                        "type": type_field,
                        "default": {
                            "description": (
                                "Default value if argument is not provided "
                                "(null means required)"
                            )
                        },
                        "description": {
                            "type": "string",
                            "description": "Human-readable input description",
                        },
                        "repeatable": _repeatable_schema(),
                        "choices": choices,
                    },
                },
            },
            {
                "type": "object",
                "description": (
                    "Object shorthand: { argName: type } or "
                    "{ argName: { type, default, description } }"
                ),
                "additionalProperties": {
                    "oneOf": [
                        shorthand_type,
                        {
                            "type": "object",
                            "description": (
                                "Full definition with type, default, and description"
                            ),
                            "properties": {
                                "type": object_type,
                                "default": {
                                    "description": (
                                        "Default value if argument is not provided"
                                    )
                                },
                                "description": {
                                    "type": "string",
                                    "description": "Human-readable input description",
                                },
                                "repeatable": _repeatable_schema(),
                                "choices": choices,
                            },
                        },
                    ]
                },
            },
        ],
    }


# symvision: tools/sync_macro_input_schemas
def config_macro_input_definitions_block(
    catalog: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the generated ``macroInputDefinitions`` config schema block."""
    resolved = (
        list(catalog) if catalog is not None else _builtin_macro_input_type_catalog()
    )
    type_field = _macro_input_type_field_schema(resolved)
    shorthand_type = _macro_input_type_field_schema(
        resolved, include_default=False, shorthand=True
    )
    object_type = _macro_input_type_field_schema(resolved, include_default=False)
    choices = _macro_input_choices_schema()
    return {
        "description": "Input argument definitions (array or object shorthand)",
        "oneOf": [
            {
                "type": "array",
                "description": "List of input argument definitions",
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": (
                                "The argument name (used for named args like "
                                "name=value)"
                            ),
                        },
                        "type": type_field,
                        "default": {
                            "description": ("Default value if argument is not provided")
                        },
                        "description": {
                            "type": "string",
                            "description": "Human-readable input description",
                        },
                        "repeatable": _repeatable_schema(),
                        "choices": choices,
                    },
                },
            },
            {
                "type": "object",
                "description": (
                    "Object shorthand: { argName: type } or "
                    "{ argName: { type, default, description } }"
                ),
                "additionalProperties": {
                    "oneOf": [
                        shorthand_type,
                        {
                            "type": "object",
                            "description": (
                                "Full definition with type, default, and description"
                            ),
                            "properties": {
                                "type": object_type,
                                "default": {
                                    "description": (
                                        "Default value if argument is not provided"
                                    )
                                },
                                "description": {
                                    "type": "string",
                                    "description": "Human-readable input description",
                                },
                                "repeatable": _repeatable_schema(),
                                "choices": choices,
                            },
                        },
                    ]
                },
            },
        ],
    }


def _definition_block(document: Mapping[str, Any] | None, key: str) -> Any:
    if not isinstance(document, Mapping):
        return None
    definitions = document.get("definitions")
    if isinstance(definitions, Mapping):
        return definitions.get(key)
    return None


def _stable_json(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True)


# symvision: tools/sync_macro_input_schemas
def macro_input_schemas_drift(
    workflow_document: Mapping[str, Any] | None,
    config_document: Mapping[str, Any] | None,
    catalog: Sequence[Mapping[str, Any]] | None = None,
) -> str | None:
    """Return a human-readable drift message, or ``None`` when both docs match."""
    resolved = (
        list(catalog) if catalog is not None else _builtin_macro_input_type_catalog()
    )
    expected_workflow = workflow_input_definitions_block(resolved)
    expected_config = config_macro_input_definitions_block(resolved)
    actual_workflow = _definition_block(workflow_document, "inputDefinitions")
    actual_config = _definition_block(config_document, "macroInputDefinitions")
    messages: list[str] = []
    if actual_workflow != expected_workflow:
        messages.append(
            "workflow inputDefinitions schema block is out of sync with the "
            "input-type catalog\n"
            f"expected:\n{_stable_json(expected_workflow)}\n"
            f"actual:\n{_stable_json(actual_workflow)}"
        )
    if actual_config != expected_config:
        messages.append(
            "config macroInputDefinitions schema block is out of sync with the "
            "input-type catalog\n"
            f"expected:\n{_stable_json(expected_config)}\n"
            f"actual:\n{_stable_json(actual_config)}"
        )
    if not messages:
        return None
    return "\n\n".join(messages)
