"""Status-label helpers for gate shell members."""

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
    effective_turn_status,
    turn_status_glyph,
    turn_status_pair,
    turn_status_style,
)


class _GateStatusPair(TurnStatusPair):
    """Ordered ``(pending, settled)`` label pair for one gate shell."""


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
    """Clamp both gate-shell status labels, filling omitted halves."""
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
            noun="gate shell status",
        ),
    )


def gate_status_style(
    pair: TurnStatusPair,
    *,
    gate_state: str | None,
    accent: str | None = None,
) -> str:
    """Return the Rich style for a gate status token."""
    if gate_state in _FAILURE_GATE_STATES:
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


def gate_status_glyph(gate_state: str | None) -> str:
    """Return the outcome glyph for ``gate_state``, or ``""`` if none."""
    return turn_status_glyph(gate_state, glyphs=_GATE_STATUS_GLYPHS)


def effective_gate_status(
    pair: TurnStatusPair,
    *,
    gate_state: str | None,
    settled: bool,
) -> str:
    """Return the label a surface should show for this pair and state."""
    return effective_turn_status(
        pair,
        shell_state=gate_state,
        settled=settled,
        terminal_states=_TERMINAL_GATE_STATES,
    )


__all__ = [
    "DEFAULT_GATE_TURN_PENDING_STATUS",
    "DEFAULT_GATE_TURN_SETTLED_STATUS",
    "GATE_STATUS_ACCENTS",
    "GATE_STATUS_FAILURE_STYLE",
    "effective_gate_status",
    "gate_status_glyph",
    "gate_status_pair",
    "gate_status_style",
]
