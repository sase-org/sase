"""The one rule that turns a reviewer's note into gate command input.

Compatibility shim. Before this module existed each surface decided for
itself whether the free-text note reached a command: ACE never copied it,
the mobile bridge copied it only when the literal option id ``feedback``
was selected, and Telegram copied it only when an option's schema listed
``feedback`` under ``required``. The same gate therefore answered
differently depending on where it was tapped. The rule now lives in the
executor so every caller -- including headless ones -- gets it for free.

Deletion trigger: once per-option declarative ``inputs`` land and the
built-ins that smuggle structured data through the note are retired,
``feedback`` becomes an ordinary declared input field that a surface
collects like any other, and this module goes away with the surfaces'
special casing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.notification_gates.models import GateOption

FEEDBACK_INPUT_PROPERTY = "feedback"


def _option_accepts_feedback_input(option: GateOption) -> bool:
    """Whether this option's command should receive the reviewer note as input.

    The test is the option's declared ``properties`` rather than its
    ``required`` list, so a command that merely accepts an optional note
    still receives one. An option whose schema does not declare the
    property is left alone: many built-ins close their input object with
    ``additionalProperties: false``, and injecting there would turn a
    valid answer into a schema failure.
    """
    properties = option.input_schema.get("properties")
    return isinstance(properties, Mapping) and FEEDBACK_INPUT_PROPERTY in properties


def apply_feedback_input(
    options: Sequence[GateOption],
    option_inputs: Mapping[str, Any],
    feedback: str | None,
) -> dict[str, Any]:
    """Return per-option inputs with the note injected wherever it is declared.

    Options absent from *option_inputs* keep no value; a value that is not
    a JSON object has nowhere to hold the note and is passed through
    unchanged, leaving the schema to reject it if it must.
    """
    resolved: dict[str, Any] = {
        option.id: option_inputs[option.id]
        for option in options
        if option.id in option_inputs
    }
    if feedback is None:
        return resolved
    for option in options:
        value = resolved.get(option.id)
        if not isinstance(value, Mapping) or not _option_accepts_feedback_input(option):
            continue
        resolved[option.id] = {**value, FEEDBACK_INPUT_PROPERTY: feedback}
    return resolved


__all__ = [
    "FEEDBACK_INPUT_PROPERTY",
    "apply_feedback_input",
]
