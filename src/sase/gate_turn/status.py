"""Status-label helpers for gate turn members."""

from __future__ import annotations

from typing import cast

from sase.notification_gates.model_turn import (
    DEFAULT_GATE_TURN_PENDING_STATUS,
    DEFAULT_GATE_TURN_SETTLED_STATUS,
    GATE_TURN_STATUS_ELLIPSIS,
    GATE_TURN_STATUS_MAX_CHARS,
)
from sase.turns.status import (
    TurnStatusPair,
    clamp_turn_status,
    effective_turn_status,
    turn_status_glyph,
    turn_status_pair,
    turn_status_style,
)


class _GateStatusPair(TurnStatusPair):
    """Ordered ``(pending, settled)`` label pair for one gate turn."""


GATE_STATUS_ACCENTS: tuple[str, ...] = (
    "#FEA775",
    "#F8AD08",
    "#CCBF08",
    "#81D005",
    "#0BD68B",
    "#00D2C4",
    "#0BCDEC",
    "#6FC4FF",
    "#A1BAFF",
    "#C4B0FE",
    "#F39CFE",
    "#FF9ECD",
)
GATE_STATUS_FAILURE_STYLE = "bold #FF5F5F"
_TERMINAL_GATE_STATES = frozenset(
    {"answered", "completed", "failed", "timeout", "stopped", "lost"}
)
_FAILURE_GATE_STATES = frozenset({"failed", "timeout", "lost"})
_SETTLED_OK_GATE_STATES = frozenset({"answered", "completed", "stopped"})
_GATE_STATUS_GLYPHS: dict[str, str] = {
    "pending": "",
    "settling": "",
    "answered": "✓",
    "completed": "✓",
    "stopped": "⊘",
    "timeout": "⧖",
    "lost": "⚠",
    "failed": "✗",
}


def gate_status_pair(start: str | None, stop: str | None) -> TurnStatusPair:
    """Clamp both gate-turn status labels, filling omitted halves."""
    return cast(
        TurnStatusPair,
        turn_status_pair(
            start,
            stop,
            default_start=DEFAULT_GATE_TURN_PENDING_STATUS,
            default_stop=DEFAULT_GATE_TURN_SETTLED_STATUS,
            max_chars=GATE_TURN_STATUS_MAX_CHARS,
            ellipsis=GATE_TURN_STATUS_ELLIPSIS,
            pair_type=_GateStatusPair,
            noun="gate turn status",
        ),
    )


#: Suffix marking a non-terminal gate whose accepted execution failed.
#: Kept short so the combined label stays within
#: ``GATE_TURN_STATUS_MAX_CHARS``.
FAILURE_LABEL_SUFFIX = " ✗"


def _has_active_failure(
    gate_state: str | None, settled: bool, has_failure: bool
) -> bool:
    return bool(has_failure) and not settled and gate_state not in _TERMINAL_GATE_STATES


def gate_status_style(
    pair: TurnStatusPair,
    *,
    gate_state: str | None,
    accent: str | None = None,
    has_failure: bool = False,
) -> str:
    """Return the Rich style for a gate status token."""
    if gate_state in _FAILURE_GATE_STATES:
        return GATE_STATUS_FAILURE_STYLE
    if has_failure and gate_state not in _TERMINAL_GATE_STATES:
        return GATE_STATUS_FAILURE_STYLE
    if gate_state in _SETTLED_OK_GATE_STATES:
        return "#9E9E9E"
    if accent:
        return f"bold {accent}"
    return turn_status_style(
        pair,
        shell_state=gate_state,
        accents=GATE_STATUS_ACCENTS,
        failure_states=_FAILURE_GATE_STATES,
        settled_ok_states=frozenset(),
        failure_style=GATE_STATUS_FAILURE_STYLE,
    )


def gate_status_glyph(gate_state: str | None, *, has_failure: bool = False) -> str:
    """Return the outcome glyph for ``gate_state``, or ``""`` if none."""
    if has_failure and gate_state not in _TERMINAL_GATE_STATES:
        return "✗"
    return turn_status_glyph(gate_state, glyphs=_GATE_STATUS_GLYPHS)


def effective_gate_status(
    pair: TurnStatusPair,
    *,
    gate_state: str | None,
    settled: bool,
    has_failure: bool = False,
) -> str:
    """Return the label a surface should show for this pair and state."""
    base = effective_turn_status(
        pair,
        shell_state=gate_state,
        settled=settled,
        terminal_states=_TERMINAL_GATE_STATES,
    )
    if not _has_active_failure(gate_state, settled, has_failure):
        return base
    if base.endswith(FAILURE_LABEL_SUFFIX):
        return base
    candidate = f"{base}{FAILURE_LABEL_SUFFIX}"
    if len(candidate) <= GATE_TURN_STATUS_MAX_CHARS:
        return candidate
    trimmed = base[: max(0, GATE_TURN_STATUS_MAX_CHARS - len(FAILURE_LABEL_SUFFIX))]
    trimmed = trimmed.rstrip()
    candidate = f"{trimmed}{FAILURE_LABEL_SUFFIX}"
    return clamp_turn_status(
        candidate,
        max_chars=GATE_TURN_STATUS_MAX_CHARS,
        ellipsis=GATE_TURN_STATUS_ELLIPSIS,
        noun="gate turn status",
    )


__all__ = [
    "DEFAULT_GATE_TURN_PENDING_STATUS",
    "DEFAULT_GATE_TURN_SETTLED_STATUS",
    "FAILURE_LABEL_SUFFIX",
    "GATE_STATUS_ACCENTS",
    "GATE_STATUS_FAILURE_STYLE",
    "effective_gate_status",
    "gate_status_glyph",
    "gate_status_pair",
    "gate_status_style",
]
