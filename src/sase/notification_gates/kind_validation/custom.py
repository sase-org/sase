"""Answerability contract for author-defined custom gates.

Every other gate kind is built by code in this repo and validated against a
registered shape. A custom gate's options are written by hand, and until this
module existed nothing checked that the option's declared ``input_schema``
could accept what a client is actually able to submit. A gate declaring a
required property with no matching ``inputs`` field was therefore accepted at
creation, rejected by the executor on every submission, and -- before
``executor-integrity`` -- left no error record at all. It was permanently
unanswerable and silently so.

The check here is a probe: build the value a client can really produce and
validate it against the option's own schema. Failing at ``sase gate create``,
with the offending property named, is the whole point.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.notification_gates.feedback_input import FEEDBACK_INPUT_PROPERTY
from sase.notification_gates.model_inputs import GateInputField
from sase.notification_gates.model_options import GateOption
from sase.notification_gates.model_validation import first_schema_error
from sase.notification_gates.models import GateError, GateSpec
from sase.xprompt.models import InputType

_SAMPLE_VALUES: dict[InputType, Any] = {
    InputType.WORD: "value",
    InputType.AGENT: "value",
    InputType.LINE: "value",
    InputType.TEXT: "value",
    InputType.PATH: "value",
    InputType.INT: 0,
    InputType.FLOAT: 0.0,
    InputType.BOOL: False,
}


def validate_custom_spec(spec: GateSpec) -> None:
    """Reject a custom gate that no client could answer."""
    for index, option in enumerate(spec.options):
        _validate_option_answerability(option, f"options[{index}]")


def _validate_option_answerability(option: GateOption, target: str) -> None:
    probe = _client_producible_input(option)
    error = first_schema_error(probe, option.input_schema)
    if error is None:
        return
    raise GateError(
        "unanswerable_option",
        f"{target}.input_schema",
        f"option {option.id!r} cannot be answered: no surface can submit a "
        f"value its input_schema accepts ({error.message}). " + _remedy(option, error),
    )


def _client_producible_input(option: GateOption) -> dict[str, Any]:
    """Return the richest input value a surface can submit for *option*.

    Declared ``inputs`` are what a surface renders, so each contributes its
    default or a representative value of its declared type. The reviewer's
    note is added only when the option would really receive it -- the same
    ``properties``-based rule
    :mod:`sase.notification_gates.feedback_input` applies at execution -- so
    the probe never credits a client with a field it could not send.
    """
    probe: dict[str, Any] = {
        input_field.id: _producible_value(input_field) for input_field in option.inputs
    }
    if (
        option.feedback != "disabled"
        and FEEDBACK_INPUT_PROPERTY not in probe
        and _declares_feedback_property(option.input_schema)
    ):
        probe[FEEDBACK_INPUT_PROPERTY] = "feedback"
    return probe


def _producible_value(input_field: GateInputField) -> Any:
    if input_field.default is not None:
        return input_field.default
    if input_field.type is InputType.ENUM:
        value: Any = input_field.choices[0].value
    else:
        value = _SAMPLE_VALUES[input_field.type]
    return [value] if input_field.repeatable else value


def _declares_feedback_property(schema: Mapping[str, Any]) -> bool:
    properties = schema.get("properties")
    return isinstance(properties, Mapping) and FEEDBACK_INPUT_PROPERTY in properties


def _remedy(option: GateOption, error: Any) -> str:
    """Explain what the author should change, in the author's own vocabulary."""
    if error.validator != "required":
        return (
            "Declare the input the command needs under 'inputs' so every "
            "surface can collect it."
        )
    missing = sorted(
        str(name)
        for name in error.validator_value
        if name not in _client_producible_input(option)
    )
    named = ", ".join(repr(name) for name in missing) or "the required property"
    remedy = (
        f"Declare {named} under this option's 'inputs' so every surface "
        "collects it, or drop it from 'required'."
    )
    if _requires_format(option.input_schema, missing):
        remedy += (
            " Note that 'format' is annotation-only here: the executor "
            "validates with no FormatChecker, so a declared format is "
            "documentation and never a constraint."
        )
    return remedy


def _requires_format(schema: Mapping[str, Any], property_names: list[str]) -> bool:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return False
    return any(
        isinstance(properties.get(name), Mapping) and "format" in properties[name]
        for name in property_names
    )


__all__ = ["validate_custom_spec"]
