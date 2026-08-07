"""Declarative per-option input fields for notification gates.

:class:`GateInputField` is the authoring vocabulary; :func:`compile_gate_input_schema`
projects a tuple of fields into the JSON Schema stored as a
:class:`~sase.notification_gates.model_options.GateOption`'s ``input_schema``, which
stays the single enforcement layer the executor validates against.

This module must not import :mod:`sase.notification_gates.model_options`;
``model_options`` imports this module instead.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sase.notification_gates.model_validation import (
    GateError,
    GateFeedbackMode,
    json_object,
    reject_unknown_fields,
)
from sase.xprompt.models import InputChoice, InputType

_GATE_INPUT_FIELD_KEYS = {
    "id",
    "label",
    "type",
    "required",
    "default",
    "choices",
    "placeholder",
    "help",
    "secret",
    "repeatable",
}

_GATE_INPUT_TYPE_SPELLINGS: dict[str, InputType] = {
    "word": InputType.WORD,
    "line": InputType.LINE,
    "text": InputType.TEXT,
    "path": InputType.PATH,
    "agent": InputType.AGENT,
    "int": InputType.INT,
    "bool": InputType.BOOL,
    "float": InputType.FLOAT,
    "enum": InputType.ENUM,
}

_TYPE_SCHEMA_FRAGMENTS: dict[InputType, dict[str, Any]] = {
    InputType.WORD: {"type": "string", "minLength": 1, "pattern": r"^\S+$"},
    InputType.AGENT: {"type": "string", "minLength": 1, "pattern": r"^\S+$"},
    InputType.LINE: {"type": "string", "pattern": r"^[^\n]*$"},
    InputType.TEXT: {"type": "string"},
    InputType.PATH: {"type": "string", "minLength": 1, "pattern": r"^[^\n]*$"},
    InputType.INT: {"type": "integer"},
    InputType.FLOAT: {"type": "number"},
    InputType.BOOL: {"type": "boolean"},
}

_GATE_INPUT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True)
class GateInputField:
    """One declared input a gate option's command consumes.

    Attributes:
        id: The JSON property name; must match ``^[a-z][a-z0-9_]*$``.
        label: Human-readable display text.
        type: One of ``word``, ``line``, ``text``, ``path``, ``agent``, ``int``,
            ``bool``, ``float``, ``enum``.
        required: Whether the compiled schema requires this property.
        default: A declared default value (not validated against ``type`` here;
            see ``custom-validation``).
        choices: Declared values for an ``enum`` field. Required and non-empty
            for ``enum``; must be empty for every other type.
        placeholder: Optional placeholder text for a rendered input.
        help: Optional help text for a rendered input.
        secret: Whether the resolved value is redacted in ``response.json``.
        repeatable: Whether the compiled schema wraps the fragment in an array.
    """

    id: str
    label: str
    type: InputType
    required: bool = False
    default: Any = None
    choices: tuple[InputChoice, ...] = ()
    placeholder: str | None = None
    help: str | None = None
    secret: bool = False
    repeatable: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "type": self.type.value,
            "required": self.required,
            "default": self.default,
            "choices": [
                {"value": choice.value, "label": choice.label}
                for choice in self.choices
            ],
            "placeholder": self.placeholder,
            "help": self.help,
            "secret": self.secret,
            "repeatable": self.repeatable,
        }


def parse_gate_input_fields(value: object, target: str) -> tuple[GateInputField, ...]:
    """Parse a gate option's ``inputs`` declaration into :class:`GateInputField`.

    Args:
        value: The raw ``inputs`` value (``None`` when undeclared).
        target: The owning option's error-message prefix (e.g. ``options[0]``).

    Returns:
        Tuple of parsed fields, in declared order. Empty when ``value`` is
        ``None`` or an empty list.

    Raises:
        GateError: ``invalid_input_field`` for any malformed field.
    """
    if value is None:
        return ()
    if not isinstance(value, list):
        raise GateError(
            "invalid_input_field", f"{target}.inputs", "inputs must be an array"
        )
    fields: list[GateInputField] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        item_target = f"{target}.inputs[{index}]"
        data = json_object(item, item_target)
        reject_unknown_fields(data, _GATE_INPUT_FIELD_KEYS, item_target)

        raw_id = data.get("id")
        if not isinstance(raw_id, str) or not _GATE_INPUT_ID_RE.fullmatch(raw_id):
            raise GateError(
                "invalid_input_field",
                f"{item_target}.id",
                f"{item_target}.id must match [a-z][a-z0-9_]*",
            )
        if raw_id in seen_ids:
            raise GateError(
                "invalid_input_field",
                f"{item_target}.id",
                f"duplicate input field id: {raw_id}",
            )
        seen_ids.add(raw_id)

        raw_label = data.get("label")
        if not isinstance(raw_label, str) or not raw_label.strip():
            raise GateError(
                "invalid_input_field",
                f"{item_target}.label",
                f"{item_target}.label is required",
            )

        raw_type = data.get("type")
        if not isinstance(raw_type, str) or raw_type not in _GATE_INPUT_TYPE_SPELLINGS:
            allowed = ", ".join(sorted(_GATE_INPUT_TYPE_SPELLINGS))
            raise GateError(
                "invalid_input_field",
                f"{item_target}.type",
                f"{item_target}.type must be one of {allowed}",
            )
        field_type = _GATE_INPUT_TYPE_SPELLINGS[raw_type]

        required = _bool_field(data, "required", item_target)
        secret = _bool_field(data, "secret", item_target)
        repeatable = _bool_field(data, "repeatable", item_target)
        placeholder = _optional_str_field(data, "placeholder", item_target)
        help_text = _optional_str_field(data, "help", item_target)

        raw_choices = data.get("choices")
        if field_type is InputType.ENUM:
            choices = _parse_gate_choices(raw_choices, item_target)
        elif raw_choices not in (None, []):
            raise GateError(
                "invalid_input_field",
                f"{item_target}.choices",
                f"{item_target}.choices is only valid for type 'enum'",
            )
        else:
            choices = ()

        fields.append(
            GateInputField(
                id=raw_id,
                label=raw_label.strip(),
                type=field_type,
                required=required,
                default=data.get("default"),
                choices=choices,
                placeholder=placeholder,
                help=help_text,
                secret=secret,
                repeatable=repeatable,
            )
        )
    return tuple(fields)


def _bool_field(data: Mapping[str, Any], key: str, target: str) -> bool:
    value = data.get(key, False)
    if not isinstance(value, bool):
        raise GateError(
            "invalid_input_field",
            f"{target}.{key}",
            f"{target}.{key} must be a boolean",
        )
    return value


def _optional_str_field(data: Mapping[str, Any], key: str, target: str) -> str | None:
    value = data.get(key)
    if value is not None and not isinstance(value, str):
        raise GateError(
            "invalid_input_field",
            f"{target}.{key}",
            f"{target}.{key} must be a string or null",
        )
    return value


def _parse_gate_choices(value: object, target: str) -> tuple[InputChoice, ...]:
    choices_target = f"{target}.choices"
    if not isinstance(value, list) or not value:
        raise GateError(
            "invalid_input_field",
            choices_target,
            f"{choices_target} must be a non-empty array for type 'enum'",
        )
    choices: list[InputChoice] = []
    seen_values: set[str] = set()
    for index, item in enumerate(value):
        item_target = f"{choices_target}[{index}]"
        if isinstance(item, str):
            gate_value, label = item, None
        elif isinstance(item, Mapping):
            data = json_object(item, item_target)
            reject_unknown_fields(data, {"value", "label"}, item_target)
            raw_value = data.get("value")
            if not isinstance(raw_value, str) or not raw_value:
                raise GateError(
                    "invalid_input_field",
                    f"{item_target}.value",
                    f"{item_target}.value must be a non-empty string",
                )
            raw_label = data.get("label")
            if raw_label is not None and not isinstance(raw_label, str):
                raise GateError(
                    "invalid_input_field",
                    f"{item_target}.label",
                    f"{item_target}.label must be a string or null",
                )
            gate_value, label = raw_value, raw_label
        else:
            raise GateError(
                "invalid_input_field",
                item_target,
                f"{item_target} must be a string or a {{value, label}} object",
            )
        if not gate_value:
            raise GateError(
                "invalid_input_field",
                f"{item_target}.value",
                f"{item_target}.value must be non-empty",
            )
        if gate_value in seen_values:
            raise GateError(
                "invalid_input_field",
                choices_target,
                f"duplicate choice value: {gate_value}",
            )
        seen_values.add(gate_value)
        choices.append(InputChoice(value=gate_value, label=label))
    return tuple(choices)


def compile_gate_input_schema(
    fields: tuple[GateInputField, ...], *, feedback_mode: GateFeedbackMode
) -> dict[str, Any]:
    """Project declared ``fields`` into the compiled ``input_schema`` object.

    A declared field whose id is ``feedback`` suppresses the automatic
    ``feedback`` property injection, so a later phase can declare feedback as
    an ordinary input field without a special case.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    has_feedback_field = False
    for gate_input_field in fields:
        if gate_input_field.type is InputType.ENUM:
            fragment: dict[str, Any] = {
                "enum": [choice.value for choice in gate_input_field.choices]
            }
        else:
            fragment = dict(_TYPE_SCHEMA_FRAGMENTS[gate_input_field.type])
        if gate_input_field.repeatable:
            fragment = {"type": "array", "items": fragment}
        properties[gate_input_field.id] = fragment
        if gate_input_field.required:
            required.append(gate_input_field.id)
        if gate_input_field.id == "feedback":
            has_feedback_field = True

    if feedback_mode != "disabled" and not has_feedback_field:
        properties["feedback"] = {"type": "string"}

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


__all__ = [
    "GateInputField",
    "compile_gate_input_schema",
    "parse_gate_input_fields",
]
