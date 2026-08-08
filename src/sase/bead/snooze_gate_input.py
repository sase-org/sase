"""The declared wake-time input both bead gates collect.

A bead gate that defers work needs one argument -- when to wake it -- and
before declarative inputs existed there was nowhere to put it. Both the
TaskTriage and BeadSnooze gates smuggled it through the gate's one free-text
feedback field, which no option command can see, so the host re-parsed the
note before persisting the response just to keep a typo from answering the
gate with an instruction it could not follow.

The wake time is now one ordinary declared line input. It carries the full
``"<wake-time> [+<N>]"`` vocabulary :mod:`sase.bead.snooze_time` accepts, so a
reviewer can type a relative duration, an absolute timestamp, and optionally
one +1 wake threshold in the same place.

The value reaches the option command on stdin, and the command -- not the
host -- resolves it, so an unparsable wake time fails the command and leaves
the gate pending exactly as the deleted host-side check did.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.bead.snooze_time import ACCEPTED_SNOOZE_FORMS, SnoozeTimeError

SNOOZE_DURATION_FIELD_ID = "duration"

_LEGACY_CUSTOM_DURATION_FIELD_ID = "custom_duration"
_LEGACY_CUSTOM_DURATION_CHOICE = "custom"
_SNOOZE_DURATION_PLACEHOLDER = "e.g., 3d, 2026-08-09T09:00:00-04:00, or 3d +2"
_SNOOZE_DURATION_HELP = (
    f"{ACCEPTED_SNOOZE_FORMS}; append +N to also wake after N more +1 reports"
)


def snooze_duration_inputs() -> list[dict[str, Any]]:
    """Return the ``inputs`` declaration a deferring option carries.

    A pure function of nothing, because gate validation rebuilds the request
    spec from its payload and compares it byte for byte.
    """
    return [
        {
            "id": SNOOZE_DURATION_FIELD_ID,
            "label": "Wake time",
            "type": "line",
            "required": True,
            "placeholder": _SNOOZE_DURATION_PLACEHOLDER,
            "help": _SNOOZE_DURATION_HELP,
        },
    ]


def _legacy_custom_duration(raw_input: Mapping[str, Any]) -> str | None:
    """Return the old two-field custom duration, when a pending bundle uses it."""
    preset = raw_input.get(SNOOZE_DURATION_FIELD_ID)
    if preset != _LEGACY_CUSTOM_DURATION_CHOICE:
        return None
    custom = raw_input.get(_LEGACY_CUSTOM_DURATION_FIELD_ID)
    if not isinstance(custom, str) or not custom.strip():
        raise SnoozeTimeError(
            "a custom snooze needs a wake time in "
            f"{_LEGACY_CUSTOM_DURATION_FIELD_ID}; {ACCEPTED_SNOOZE_FORMS}"
        )
    return custom.strip()


def snooze_duration_result_property() -> dict[str, Any]:
    """Return the result-schema fragment a deferring option's command emits."""
    return {"type": "string", "minLength": 1}


def resolve_snooze_duration(raw_input: Mapping[str, Any]) -> str:
    """Return the wake-time expression one submitted snooze input names.

    New gates submit a single required ``duration`` line. The narrow legacy
    branch keeps already-persisted two-field bundles answerable during rollout:
    if their old enum selected ``custom``, the old ``custom_duration`` companion
    is parsed instead. The returned expression is already known to parse.

    Raises:
        SnoozeTimeError: If the submitted value is missing, of the wrong
            type, or names no usable wake time. The message always lists the
            accepted forms, because this is the one argument a mistyped
            snooze would otherwise lose.
    """
    from sase.bead.snooze_time import parse_snooze_request

    text = _legacy_custom_duration(raw_input)
    if text is None:
        duration = raw_input.get(SNOOZE_DURATION_FIELD_ID)
        if not isinstance(duration, str):
            raise SnoozeTimeError(
                f"{SNOOZE_DURATION_FIELD_ID} must be a string; {ACCEPTED_SNOOZE_FORMS}"
            )
        text = duration.strip()
    parse_snooze_request(text)
    return text


__all__ = [
    "SNOOZE_DURATION_FIELD_ID",
    "resolve_snooze_duration",
    "snooze_duration_inputs",
    "snooze_duration_result_property",
]
