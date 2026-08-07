"""Reserved keys shared by gate action validation and the gate modals.

A gate action may declare the key a surface binds for it. Creation rejects a
key the shared modals already own, so an author learns about the collision
when they write the gate rather than when a reviewer presses a key and the
modal cancels instead of running their action. Validation and the modals read
the reserved set from here so the two can never drift.

Collisions with *user-configured* modal keymaps cannot be known at creation
time; a surface resolves those at render time by reassigning from
``GATE_ACTION_FALLBACK_KEYS`` and displaying the key it actually bound.
"""

from __future__ import annotations

from sase.notification_gates.model_validation import GateError

RESERVED_GATE_ACTION_KEYS = frozenset(
    {
        # Static gate-modal bindings, single-character forms only: a declared
        # key is one printable character, so "escape", "ctrl+d", and "ctrl+u"
        # can never be requested.
        "q",
        "d",
        "g",
        "G",
        # Numbered branch selectors.
        *(str(digit) for digit in range(1, 10)),
    }
)

GATE_ACTION_FALLBACK_KEYS = tuple(
    key
    for key in "abcefhilmnoprstuvwxyzABCDEFHIJKLMNOPQRSTUVWXYZ"
    if key not in RESERVED_GATE_ACTION_KEYS
)


def validate_gate_action_key(value: object, target: str) -> str | None:
    """Return one declared action key, or reject a reserved or malformed one."""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 1 or not value.isprintable():
        raise GateError(
            "invalid_operation",
            target,
            f"{target} must be a single printable character",
        )
    if value in RESERVED_GATE_ACTION_KEYS:
        raise GateError(
            "reserved_action_key",
            target,
            f"key {value!r} is reserved by the gate modals: "
            + ", ".join(sorted(RESERVED_GATE_ACTION_KEYS)),
        )
    return value


__all__ = [
    "GATE_ACTION_FALLBACK_KEYS",
    "RESERVED_GATE_ACTION_KEYS",
    "validate_gate_action_key",
]
