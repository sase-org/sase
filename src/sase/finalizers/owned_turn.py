"""Environment marker for provider turns owned by host finalizers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
import os

SASE_FINALIZER_OWNED_TURN_ENV = "SASE_FINALIZER_OWNED_TURN"

#: Values that count as an active finalizer-owned turn (same truthy parsing
#: the gate-turn copy historically used).
_ACTIVE_VALUES = frozenset({"1", "true", "yes", "on"})


def finalizer_owned_turn_is_active(
    env: Mapping[str, str] | None = None,
) -> bool:
    """Return whether the current provider turn is owned by a host finalizer."""
    import os

    current = os.environ if env is None else env
    value = (current.get(SASE_FINALIZER_OWNED_TURN_ENV) or "").strip().lower()
    return value in _ACTIVE_VALUES


def finalizer_owned_turn_refusal(
    command: str,
    *,
    inline_hint: str | None = None,
) -> str:
    """Build the refusal message for a turn-ending handoff in a finalizer turn."""
    message = (
        f"{command} is refused inside a host finalizer turn: this turn cannot "
        "end the agent run, so the handoff could never hand off. Finish the "
        "finalizer's task in this turn, or report the blocker in your response "
        "so the host records the failure."
    )
    if inline_hint:
        message += f" {inline_hint}"
    return message


@contextmanager
def finalizer_owned_turn() -> Iterator[None]:
    """Mark the current provider invocation as owned by a host finalizer."""

    previous = os.environ.get(SASE_FINALIZER_OWNED_TURN_ENV)
    os.environ[SASE_FINALIZER_OWNED_TURN_ENV] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(SASE_FINALIZER_OWNED_TURN_ENV, None)
        else:
            os.environ[SASE_FINALIZER_OWNED_TURN_ENV] = previous


__all__ = [
    "SASE_FINALIZER_OWNED_TURN_ENV",
    "finalizer_owned_turn",
    "finalizer_owned_turn_is_active",
    "finalizer_owned_turn_refusal",
]
