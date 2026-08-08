"""The declared wake-time input both bead gates collect.

A bead gate that defers work needs one argument -- when to wake it -- and
before declarative inputs existed there was nowhere to put it. Both the
TaskTriage and BeadSnooze gates smuggled it through the gate's one free-text
feedback field, which no option command can see, so the host re-parsed the
note before persisting the response just to keep a typo from answering the
gate with an instruction it could not follow.

The duration is now an ordinary declared input: a preset ``enum`` covering
the durations a deferred task actually waits, plus a ``line`` field for the
full ``"<duration> [+<N>]"`` vocabulary
:mod:`sase.bead.snooze_time` accepts. The presets mirror
:class:`~sase.ace.tui.modals.bead_snooze_modal.BeadSnoozeModal`, so deferring
a bead from its panel and deferring it from its gate offer the same choices.

The value reaches the option command on stdin, and the command -- not the
host -- resolves it, so an unparsable duration fails the command and leaves
the gate pending exactly as the deleted host-side check did.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.bead.snooze_time import ACCEPTED_SNOOZE_FORMS, SnoozeTimeError

SNOOZE_DURATION_FIELD_ID = "duration"
SNOOZE_CUSTOM_DURATION_FIELD_ID = "custom_duration"
SNOOZE_CUSTOM_DURATION_CHOICE = "custom"
SNOOZE_DEFAULT_DURATION = "3d"

_SNOOZE_DURATION_CHOICES: tuple[tuple[str, str], ...] = (
    ("4h", "4 hours"),
    ("1d", "1 day"),
    (SNOOZE_DEFAULT_DURATION, "3 days"),
    ("7d", "1 week"),
    (SNOOZE_CUSTOM_DURATION_CHOICE, "Custom…"),
)

_CUSTOM_PLACEHOLDER = "e.g., 2h, 1d12h, or '3d +2' to also wake at 2 more +1s"


def snooze_duration_inputs() -> list[dict[str, Any]]:
    """Return the ``inputs`` declaration a deferring option carries.

    A pure function of nothing, because gate validation rebuilds the request
    spec from its payload and compares it byte for byte.
    """
    return [
        {
            "id": SNOOZE_DURATION_FIELD_ID,
            "label": "Wake after",
            "type": "enum",
            "required": True,
            "default": SNOOZE_DEFAULT_DURATION,
            "choices": [
                {"value": value, "label": label}
                for value, label in _SNOOZE_DURATION_CHOICES
            ],
        },
        {
            "id": SNOOZE_CUSTOM_DURATION_FIELD_ID,
            "label": "Custom wake time",
            "type": "line",
            "placeholder": _CUSTOM_PLACEHOLDER,
            "help": ACCEPTED_SNOOZE_FORMS,
        },
    ]


def snooze_duration_result_property() -> dict[str, Any]:
    """Return the result-schema fragment a deferring option's command emits."""
    return {"type": "string", "minLength": 1}


def resolve_snooze_duration(raw_input: Mapping[str, Any]) -> str:
    """Return the wake-time expression one submitted snooze input names.

    The custom field wins whenever it carries text, so choosing ``Custom…``
    and typing a duration and simply typing one over a preset both mean what
    the reviewer sees. The returned expression is already known to parse.

    Raises:
        SnoozeTimeError: If the submitted value is missing, of the wrong
            type, or names no usable wake time. The message always lists the
            accepted forms, because this is the one argument a mistyped
            snooze would otherwise lose.
    """
    from sase.bead.snooze_time import parse_snooze_request

    custom = raw_input.get(SNOOZE_CUSTOM_DURATION_FIELD_ID)
    if custom is not None and not isinstance(custom, str):
        raise SnoozeTimeError(
            f"{SNOOZE_CUSTOM_DURATION_FIELD_ID} must be a string; "
            f"{ACCEPTED_SNOOZE_FORMS}"
        )
    text = (custom or "").strip()
    if not text:
        preset = raw_input.get(SNOOZE_DURATION_FIELD_ID)
        if not isinstance(preset, str) or not preset:
            raise SnoozeTimeError(
                f"a snooze needs a wake time; {ACCEPTED_SNOOZE_FORMS}"
            )
        if preset == SNOOZE_CUSTOM_DURATION_CHOICE:
            raise SnoozeTimeError(
                "a custom snooze needs a wake time in "
                f"{SNOOZE_CUSTOM_DURATION_FIELD_ID}; {ACCEPTED_SNOOZE_FORMS}"
            )
        text = preset
    parse_snooze_request(text)
    return text


__all__ = [
    "SNOOZE_CUSTOM_DURATION_CHOICE",
    "SNOOZE_CUSTOM_DURATION_FIELD_ID",
    "SNOOZE_DEFAULT_DURATION",
    "SNOOZE_DURATION_FIELD_ID",
    "resolve_snooze_duration",
    "snooze_duration_inputs",
    "snooze_duration_result_property",
]
