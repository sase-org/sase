"""Size and shape bounds for reviewer-authored gate input.

Submitted input lands in the durable ``response.json`` and on a trusted
command's stdin, so it cannot be unbounded now that a reviewer authors it
rather than a producing agent. These bounds are enforced at submission and
are the same numbers a later creation-time check reports to an author.
"""

from __future__ import annotations

from sase.notification_gates.durability import canonical_json_bytes
from sase.notification_gates.models import GateError

MAX_INPUT_BYTES = 64 * 1024
MAX_INPUT_DEPTH = 16
MAX_OBJECT_PROPERTIES = 128
MAX_ARRAY_ITEMS = 512


def check_input_bounds(value: object, target: str) -> None:
    """Reject input that is too large, too deep, or too wide."""
    encoded = canonical_json_bytes(value)
    if len(encoded) > MAX_INPUT_BYTES:
        raise GateError(
            "input_too_large",
            target,
            f"input is {len(encoded)} bytes; at most {MAX_INPUT_BYTES} are allowed",
        )
    _check_shape(value, target)


def _check_shape(value: object, target: str) -> None:
    pending: list[tuple[object, int]] = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if isinstance(current, dict):
            _reject_deeper_than_limit(depth, target)
            if len(current) > MAX_OBJECT_PROPERTIES:
                raise GateError(
                    "input_too_large",
                    target,
                    f"input object has {len(current)} properties; at most "
                    f"{MAX_OBJECT_PROPERTIES} are allowed",
                )
            pending.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            _reject_deeper_than_limit(depth, target)
            if len(current) > MAX_ARRAY_ITEMS:
                raise GateError(
                    "input_too_large",
                    target,
                    f"input array has {len(current)} items; at most "
                    f"{MAX_ARRAY_ITEMS} are allowed",
                )
            pending.extend((item, depth + 1) for item in current)


def _reject_deeper_than_limit(depth: int, target: str) -> None:
    if depth >= MAX_INPUT_DEPTH:
        raise GateError(
            "input_too_large",
            target,
            f"input nests deeper than {MAX_INPUT_DEPTH} levels",
        )


__all__ = [
    "MAX_ARRAY_ITEMS",
    "MAX_INPUT_BYTES",
    "MAX_INPUT_DEPTH",
    "MAX_OBJECT_PROPERTIES",
    "check_input_bounds",
]
