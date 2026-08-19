"""Shared monitor status-label contract.

Owns the read-side default labels, the 20-character clamp, pair
normalization, the 12-color pair-accent palette, and the state-aware
style/glyph/effective-label rule. Importable from the monitor core, both
CLIs, the integrations layer, and the TUI: this module has no ``rich``
dependency and does not import :mod:`sase.ace`.

The defaults are what a pre-change or externally written record projects
to. They are not what a new monitor gets by omission.

Palette construction (regenerate from this recipe, do not restyle by
eye): 12 hues spaced evenly across the OKLCH arc ``50°..350°``, each
chroma-solved to a shared WCAG relative luminance of **0.50**. The
reserved wedge ``350°..50°`` is the red band that
:data:`MONITOR_STATUS_FAILURE_STYLE` owns. 0.50 is the center of the
band the agent list's existing status colors already occupy (``#5FD75F``
0.519, ``#FFAF5F`` 0.528, ``#00D7AF`` 0.517, ``#FFAF00`` 0.519), so a
monitor status token reads at the same visual weight as ``RUNNING`` or
``DONE`` beside it. Every entry clears a contrast ratio of at least
**8.7** against the app's dark shell surfaces (``#121212`` / ``#1E1E1E``).

Like every other agent-list status color in this repo, this band is
tuned for the dark shell and only reaches ~1.4:1 against the light
surfaces ``#E0E0E0`` / ``#D8D8D8``. Matching ``PROJECT_ACCENTS``' dual-
surface 0.196 band instead would make monitor statuses visibly darker
than every status beside them. Dark-surface parity was chosen; revisit
only if the whole agent-status palette moves.

A pair's accent is hash-only (see :func:`sase.palette_hash.hash_palette_index`).
Two different pairs can collide on one color. That is acceptable: the
words still differ, and a color that depended on which other monitors
were visible would change when the user switched tabs.
"""

from __future__ import annotations

from dataclasses import dataclass

from sase.palette_hash import hash_palette_index

DEFAULT_MONITOR_START_STATUS = "MONITORING"
DEFAULT_MONITOR_STOP_STATUS = "MONITORED"
MONITOR_STATUS_MAX_CHARS = 20
MONITOR_STATUS_ELLIPSIS = "…"
MONITOR_STATUS_FAILURE_STYLE = "bold #FF5F5F"

# Unit separator so ``FOO``+``BARBAZ`` and ``FOOBAR``+``BAZ`` cannot share a key.
_MONITOR_STATUS_PAIR_KEY_SEP = "\x1f"

_TERMINAL_MONITOR_STATES = frozenset(
    {"completed", "failed", "timeout", "stopped", "lost"}
)
_FAILURE_MONITOR_STATES = frozenset({"failed", "timeout", "lost"})
_SETTLED_OK_MONITOR_STATES = frozenset({"completed", "stopped"})

# Outcome glyphs. Timeout matches ``MONITOR_TIMEOUT_GLYPH``; lost matches
# ``_MONITOR_STALLED_GLYPH``. Both stay as character literals so this module
# does not import :mod:`sase.monitor_state` (which re-exports
# :data:`DEFAULT_MONITOR_STOP_STATUS` from here).
_MONITOR_STATUS_GLYPHS: dict[str, str] = {
    "running": "",
    "completed": "✓",
    "stopped": "⊘",
    "timeout": "⧖",
    "lost": "⚠",
    "failed": "✗",
}

MONITOR_STATUS_ACCENTS: tuple[str, ...] = (
    "#FEA775",  # oklch h=50.0
    "#F8AD08",  # oklch h=77.3
    "#CCBF08",  # oklch h=104.5
    "#81D005",  # oklch h=131.8
    "#0BD68B",  # oklch h=159.1
    "#00D2C4",  # oklch h=186.4
    "#0BCDEC",  # oklch h=213.6
    "#6FC4FF",  # oklch h=240.9
    "#A1BAFF",  # oklch h=268.2
    "#C4B0FE",  # oklch h=295.5
    "#F39CFE",  # oklch h=322.7
    "#FF9ECD",  # oklch h=350.0
)


@dataclass(frozen=True, slots=True)
class MonitorStatusPair:
    """Ordered ``(start, stop)`` label pair that identifies one monitor kind."""

    start: str
    stop: str

    @property
    def key(self) -> str:
        """Case-insensitive identity used to pick the pair's accent."""
        return f"{self.start.upper()}{_MONITOR_STATUS_PAIR_KEY_SEP}{self.stop.upper()}"


def clamp_monitor_status(value: str) -> str:
    """Strip ``value`` and return at most :data:`MONITOR_STATUS_MAX_CHARS` chars.

    Over-length input is truncated to ``MAX - 1`` characters plus
    :data:`MONITOR_STATUS_ELLIPSIS`, so the result is exactly ``MAX``
    characters. Empty (after strip) and multi-line values raise
    :class:`ValueError`: truncation handles length, not a missing or
    broken label.
    """
    if "\n" in value or "\r" in value:
        raise ValueError("monitor status must be a single line")
    stripped = value.strip()
    if not stripped:
        raise ValueError("monitor status must be non-empty")
    if len(stripped) <= MONITOR_STATUS_MAX_CHARS:
        return stripped
    return stripped[: MONITOR_STATUS_MAX_CHARS - 1] + MONITOR_STATUS_ELLIPSIS


def clamp_monitor_status_or_default(value: str | None, *, default: str) -> str:
    """Return a clamped status, or ``default`` for missing/invalid input.

    Read paths use this to project historical records that may omit a
    label, exceed the new cap, or contain junk. It never raises.
    """
    if value is None:
        return default
    try:
        return clamp_monitor_status(value)
    except ValueError:
        return default


def monitor_status_pair(start: str | None, stop: str | None) -> MonitorStatusPair:
    """Clamp both halves, filling each missing half from its default.

    Displayed text keeps the author's casing; only :attr:`MonitorStatusPair.key`
    uppercases, so ``Testing`` and ``TESTING`` are one identity.
    """
    return MonitorStatusPair(
        start=clamp_monitor_status_or_default(
            start, default=DEFAULT_MONITOR_START_STATUS
        ),
        stop=clamp_monitor_status_or_default(stop, default=DEFAULT_MONITOR_STOP_STATUS),
    )


def monitor_status_accent(pair: MonitorStatusPair) -> str:
    """Return the deterministic hex accent for ``pair``."""
    return MONITOR_STATUS_ACCENTS[
        hash_palette_index(pair.key, len(MONITOR_STATUS_ACCENTS))
    ]


def monitor_status_style(pair: MonitorStatusPair, *, monitor_state: str | None) -> str:
    """Return the Rich style for a status token in ``monitor_state``.

    Failure states (``failed`` / ``timeout`` / ``lost``) keep
    :data:`MONITOR_STATUS_FAILURE_STYLE` regardless of the pair accent.
    ``running`` and any unknown or missing state are bold accent; a
    clean settlement (``completed`` / ``stopped``) is the bare accent.
    """
    if monitor_state in _FAILURE_MONITOR_STATES:
        return MONITOR_STATUS_FAILURE_STYLE
    accent = monitor_status_accent(pair)
    if monitor_state in _SETTLED_OK_MONITOR_STATES:
        return accent
    return f"bold {accent}"


def monitor_status_glyph(monitor_state: str | None) -> str:
    """Return the outcome glyph for ``monitor_state``, or ``""`` if none."""
    if monitor_state is None:
        return ""
    return _MONITOR_STATUS_GLYPHS.get(monitor_state, "")


def effective_monitor_status(
    pair: MonitorStatusPair,
    *,
    monitor_state: str | None,
    settled: bool,
) -> str:
    """Return the label a surface should show for this pair and state.

    Terminal ``monitor_state`` values and a ``settled`` record both
    project to ``pair.stop``; anything still live projects to
    ``pair.start``.
    """
    if settled or monitor_state in _TERMINAL_MONITOR_STATES:
        return pair.stop
    return pair.start


__all__ = [
    "DEFAULT_MONITOR_START_STATUS",
    "DEFAULT_MONITOR_STOP_STATUS",
    "MONITOR_STATUS_ACCENTS",
    "MONITOR_STATUS_ELLIPSIS",
    "MONITOR_STATUS_FAILURE_STYLE",
    "MONITOR_STATUS_MAX_CHARS",
    "MonitorStatusPair",
    "clamp_monitor_status",
    "clamp_monitor_status_or_default",
    "effective_monitor_status",
    "monitor_status_accent",
    "monitor_status_glyph",
    "monitor_status_pair",
    "monitor_status_style",
]
