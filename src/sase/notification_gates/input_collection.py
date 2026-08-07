"""Shared per-selection input collection for remote gate surfaces.

Telegram, ACE, and the CLI all have to answer the same three questions for one
gate selection: which fields does it ask for, how does a typed text answer
become a JSON value, and which option gets which value. This module answers
each once so no surface reimplements the shared xprompt ``InputArg``
conversion rules on its own.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.notification_gates.model_inputs import GateInputField
from sase.notification_gates.model_options import GateOption
from sase.notification_gates.model_validation import GateError
from sase.xprompt.models import UNSET, InputArg


def collected_input_fields(options: Sequence[GateOption]) -> tuple[GateInputField, ...]:
    """Declared fields for one selection, in first-declared order, deduped by id.

    Two selected options may declare the same field id, in which case it is
    collected once -- the same rule the ACE form uses. A shared id declared
    with a different ``type``, ``choices``, or ``repeatable`` cannot be
    collected once and cannot be collected twice, so it raises
    ``GateError``. Differing ``label``, ``help``, ``placeholder``,
    ``required``, or ``default`` are presentation only; the first declaration
    wins.

    Raises:
        GateError: ``conflicting_input_field`` naming both declaring options.
    """
    fields: dict[str, GateInputField] = {}
    declared_by: dict[str, str] = {}
    ordered: list[GateInputField] = []
    for option in options:
        for gate_input_field in option.inputs:
            existing = fields.get(gate_input_field.id)
            if existing is None:
                fields[gate_input_field.id] = gate_input_field
                declared_by[gate_input_field.id] = option.id
                ordered.append(gate_input_field)
                continue
            if (
                existing.type != gate_input_field.type
                or existing.choices != gate_input_field.choices
                or existing.repeatable != gate_input_field.repeatable
            ):
                raise GateError(
                    "conflicting_input_field",
                    f"inputs.{gate_input_field.id}",
                    f"input '{gate_input_field.id}' is declared differently by "
                    f"options '{declared_by[gate_input_field.id]}' and '{option.id}'",
                )
    return tuple(ordered)


def input_arg_for_field(field: GateInputField) -> InputArg:
    """Project a declared field onto the shared xprompt ``InputArg`` rules."""
    return InputArg(
        name=field.id,
        type=field.type,
        default=UNSET if field.required else field.default,
        description=field.help,
        repeatable=field.repeatable,
        choices=field.choices,
    )


def coerce_field_text(field: GateInputField, text: str) -> Any:
    """Convert one raw text answer to ``field``'s declared type.

    A ``repeatable`` field splits ``text`` on newlines, drops blank lines,
    and converts each remaining line independently -- ``InputArg`` has no
    repeatable conversion rule of its own because xprompt repeatability
    consumes positional arguments, which a chat transport has no equivalent
    of.

    Raises:
        XPromptValidationError: If a value cannot be converted.
    """
    input_arg = input_arg_for_field(field)
    if field.repeatable:
        lines = [line for line in text.split("\n") if line.strip()]
        return [input_arg.validate_and_convert(line) for line in lines]
    return input_arg.validate_and_convert(text)


def option_inputs_from_values(
    options: Sequence[GateOption], values: Mapping[str, Any]
) -> dict[str, dict[str, Any]]:
    """Distribute collected ``values`` to each option that declares them.

    An option that declares nothing maps to ``{}``. This is what makes two
    AND members with mutually exclusive ``additionalProperties: false``
    schemas both answerable from one collected set.
    """
    return {
        option.id: {
            gate_input_field.id: values[gate_input_field.id]
            for gate_input_field in option.inputs
            if gate_input_field.id in values
        }
        for option in options
    }


__all__ = [
    "coerce_field_text",
    "collected_input_fields",
    "input_arg_for_field",
    "option_inputs_from_values",
]
