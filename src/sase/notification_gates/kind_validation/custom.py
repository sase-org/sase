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

What a client can produce depends on how the option declares its input, and
there are two shapes:

* An option declaring ``inputs`` gets its ``input_schema`` compiled from
  those fields, so the probe is exactly the set of fields every surface
  renders a typed control for. Any schema error against that probe is a
  gate no surface can answer.
* An option declaring a raw ``input_schema`` and no ``inputs`` is answered
  through the raw-schema escape hatch the surfaces gained later: ACE's YAML
  editor (which renders a control for each declared, non-host-collected
  property and validates the reviewer's text against this very schema),
  ``sase gate answer --option-input``, and the mobile bridge's
  ``option_inputs``. A reviewer types the value, so any *constraint* the
  schema states about a declared property is satisfiable. What stays a real
  trap is a ``required`` name that nothing renders a control for: a name
  absent from ``properties`` (ACE's raw editor skips it, and skips the
  editor entirely when no property remains), or the host-collected
  ``feedback`` on an option whose feedback mode is ``disabled``.
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

_SCHEMA_TYPE_SAMPLES: dict[str, Any] = {
    "string": "value",
    "integer": 0,
    "number": 0.0,
    "boolean": False,
    "array": [],
    "object": {},
    "null": None,
}


def validate_custom_spec(spec: GateSpec) -> None:
    """Reject a custom gate that no client could answer."""
    for index, option in enumerate(spec.options):
        _validate_option_answerability(option, f"options[{index}]")


def _validate_option_answerability(option: GateOption, target: str) -> None:
    probe = _client_producible_input(option)
    message = (
        _typed_form_failure(option, probe)
        if option.inputs
        else _raw_schema_failure(option, probe)
    )
    if message is None:
        return
    raise GateError(
        "unanswerable_option",
        f"{target}.input_schema",
        f"option {option.id!r} cannot be answered: no surface can submit a "
        f"value its input_schema accepts ({message}). " + _remedy(option, probe),
    )


def _typed_form_failure(option: GateOption, probe: Mapping[str, Any]) -> str | None:
    """Return why the compiled schema refuses its own fields, or ``None``."""
    error = first_schema_error(probe, option.input_schema)
    return None if error is None else str(error.message)


def _raw_schema_failure(option: GateOption, probe: Mapping[str, Any]) -> str | None:
    """Return why no surface can produce a required name, or ``None``.

    Only unproducible ``required`` names are fatal here. Everything else the
    schema states -- a pattern, a bound, a type -- is something the reviewer
    satisfies by typing a different value into the raw editor, so rejecting
    the gate for it at creation would refuse a gate that answers fine.
    """
    missing = _unproducible_required_names(option, probe)
    if not missing:
        return None
    return f"{missing[0]!r} is a required property"


def _unproducible_required_names(
    option: GateOption, probe: Mapping[str, Any]
) -> list[str]:
    required = option.input_schema.get("required")
    if not isinstance(required, list):
        return []
    return sorted(
        str(name) for name in required if isinstance(name, str) and name not in probe
    )


def _client_producible_input(option: GateOption) -> dict[str, Any]:
    """Return the richest input value a surface can submit for *option*.

    Declared ``inputs`` are what a surface renders, so each contributes its
    default or a representative value of its declared type. With no declared
    ``inputs`` the reviewer edits raw YAML/JSON instead, and every declared
    property that is not host-collected gets a control, so each contributes a
    value derived from its own ``default``/``enum``/``type``. The reviewer's
    note is added only when the option would really receive it -- the same
    ``properties``-based rule
    :mod:`sase.notification_gates.feedback_input` applies at execution -- so
    the probe never credits a client with a field it could not send.
    """
    probe: dict[str, Any] = (
        {
            input_field.id: _producible_value(input_field)
            for input_field in option.inputs
        }
        if option.inputs
        else _raw_schema_probe(option.input_schema)
    )
    if (
        option.feedback != "disabled"
        and FEEDBACK_INPUT_PROPERTY not in probe
        and _declares_feedback_property(option.input_schema)
    ):
        probe[FEEDBACK_INPUT_PROPERTY] = "feedback"
    return probe


def _raw_schema_probe(schema: Mapping[str, Any]) -> dict[str, Any]:
    """Return one representative value per property the raw editor renders."""
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return {}
    return {
        str(name): _property_sample_value(property_schema)
        for name, property_schema in properties.items()
        if name != FEEDBACK_INPUT_PROPERTY
    }


def _property_sample_value(property_schema: Any) -> Any:
    """Return a value the reviewer could plausibly type for one property."""
    if not isinstance(property_schema, Mapping):
        return "value"
    if "default" in property_schema:
        return property_schema["default"]
    if "const" in property_schema:
        return property_schema["const"]
    enum = property_schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]
    return _SCHEMA_TYPE_SAMPLES.get(_declared_type(property_schema), "value")


def _declared_type(property_schema: Mapping[str, Any]) -> str:
    declared = property_schema.get("type")
    if isinstance(declared, list):
        declared = next((item for item in declared if isinstance(item, str)), None)
    return declared if isinstance(declared, str) else ""


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


def _remedy(option: GateOption, probe: Mapping[str, Any]) -> str:
    """Explain what the author should change, in the author's own vocabulary."""
    missing = _unproducible_required_names(option, probe)
    if not missing:
        return (
            "Declare the input the command needs under 'inputs' so every "
            "surface can collect it."
        )
    named = ", ".join(repr(name) for name in missing)
    remedy = (
        f"Declare {named} under this option's 'inputs' so every surface "
        "collects it, or drop it from 'required'."
    )
    if not option.inputs:
        remedy += (
            " A raw input_schema can also declare it under 'properties', "
            "which is what the raw-schema editor renders a control from."
        )
    if FEEDBACK_INPUT_PROPERTY in missing:
        remedy += (
            " The reviewer's note reaches the command only when this "
            "option's 'feedback' mode is 'optional' or 'required'."
        )
    return remedy


__all__ = ["validate_custom_spec"]
