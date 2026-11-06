"""Hijack recovery successor following for wait resolution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

#: Recovery states that keep a hijacked predecessor parked. Only a
#: ``resolved`` recovery follows its successor; pending/expired hijacks
#: never unblock a waiter on their own.
PARKED_HIJACK_RECOVERY_STATES = frozenset({"pending", "expired", "", None})

_MAX_FOLLOW_DEPTH = 10


def hijack_successor_for_done(
    done_data: Mapping[str, Any] | None,
) -> tuple[str | None, str | None]:
    """Return ``(successor, recovery_state)`` for one done marker.

    Only ``outcome: hijacked`` markers carry a recovery successor. Any
    other shape returns ``(None, None)`` so callers never follow a
    non-hijack verdict.
    """
    if not isinstance(done_data, Mapping):
        return None, None
    outcome = done_data.get("outcome")
    if not isinstance(outcome, str) or outcome.strip().lower() != "hijacked":
        return None, None
    recovery = done_data.get("recovery")
    if not isinstance(recovery, Mapping):
        return None, None
    successor = recovery.get("successor")
    state = recovery.get("state")
    successor_name = successor.strip() if isinstance(successor, str) else None
    state_name = state.strip() if isinstance(state, str) else None
    if not successor_name:
        return None, state_name
    return successor_name, state_name


def hijack_follow_is_parked(recovery_state: str | None) -> bool:
    """Return whether a hijack recovery state keeps waiters parked."""
    if recovery_state is None:
        return True
    return recovery_state.strip() in {"pending", "expired", ""}


def follow_hijack_successor_chain(
    start: str,
    successor_of: Any,
    *,
    max_depth: int = _MAX_FOLLOW_DEPTH,
) -> tuple[str, bool, str | None]:
    """Follow a hijack successor chain from *start*.

    *successor_of* maps a name to its resolved recovery successor (or
    ``None`` when the name is not a resolved hijack). Returns
    ``(final_name, parked, reason)`` where ``parked`` is True when the
    chain ends in a cycle, a missing successor, or a parked hijack, and
    ``reason`` names the stop (``"cycle"``, ``"missing"``, ``"parked"``,
    or ``None`` when the final name is a real wait target).
    """
    seen = {start}
    current = start
    for _ in range(max(0, max_depth)):
        try:
            nxt = successor_of(current)
        except Exception:
            return current, True, "missing"
        if not isinstance(nxt, str) or not nxt.strip():
            return current, False, None
        nxt = nxt.strip()
        if nxt in seen:
            return current, True, "cycle"
        seen.add(nxt)
        current = nxt
    return current, True, "cycle"
