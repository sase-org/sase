"""Shared Rust ``MacroInputHint`` wire serializer."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def _macro_input_choice_to_wire(choice: object) -> dict[str, str | None] | None:
    """Normalize one choice to the Rust wire shape, or None when invalid."""
    if isinstance(choice, str):
        return {"value": choice, "label": None, "description": None}
    if isinstance(choice, Mapping):
        value = choice.get("value")
        label = choice.get("label")
        description = choice.get("description")
    else:
        value = getattr(choice, "value", None)
        label = getattr(choice, "label", None)
        description = getattr(choice, "description", None)
    if not isinstance(value, str):
        return None
    return {
        "value": value,
        "label": label if isinstance(label, str) else None,
        "description": description if isinstance(description, str) else None,
    }


def _position_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def macro_input_hint_to_wire(
    *,
    name: object,
    type: object,
    description: object,
    required: object,
    default_display: object,
    position: object,
    repeatable: object,
    choices: object,
    named_type: object,
    value_role: object,
) -> dict[str, Any]:
    """Serialize hint fields to the Rust ``MacroInputHint`` wire shape."""
    raw_choices = (
        choices
        if isinstance(choices, Sequence)
        and not isinstance(choices, (str, bytes, bytearray))
        else ()
    )
    return {
        "name": name,
        "type": type,
        "description": description,
        "required": bool(required),
        "default_display": default_display,
        "position": _position_value(position),
        "repeatable": bool(repeatable),
        "choices": [
            wire_choice
            for choice in raw_choices
            if (wire_choice := _macro_input_choice_to_wire(choice)) is not None
        ],
        "named_type": named_type,
        "value_role": value_role,
    }


__all__ = ["_macro_input_choice_to_wire", "macro_input_hint_to_wire"]
