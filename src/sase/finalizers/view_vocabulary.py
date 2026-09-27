"""Shared finalizer state vocabulary (plan §3.2, epic sase-1b2).

One glyph + word + color mapping so the Agents-tab glance surfaces and the
future ``sase final status`` view agree. Colors reuse the existing palette.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Deck accent candidate for ⊛ FINAL surfaces (plan D2; final-deck-shell
#: confirms it against Main/Files/Tools and clan magenta in a live capture).
FINAL_DECK_ACCENT = "#FF87D7"

#: Single-cell deck/instance glyph (plan D2).
FINAL_GLYPH = "⊛"

#: Running-state color, shared with the roster's running glyph.
FINALIZING_COLOR = "#FFD700"
SUCCESS_COLOR = "#5FD75F"
FAILURE_COLOR = "#FF5F5F"
REFUSED_COLOR = "#D75FFF"
WARNING_COLOR = "#FFAF5F"


@dataclass(frozen=True)
class FinalizerStateStyle:
    """Glyph, word, and color for one finalizer state."""

    glyph: str
    word: str
    color: str


#: Instance/run state styles keyed by the §3.2 word (plan C5 statuses map
#: below through :func:`instance_style`).
STATE_STYLES: dict[str, FinalizerStateStyle] = {
    "planned": FinalizerStateStyle(glyph="◌", word="planned", color="dim"),
    "declaration": FinalizerStateStyle(
        glyph="▶", word="declaration", color=FINALIZING_COLOR
    ),
    "running": FinalizerStateStyle(glyph="▶", word="running", color=FINALIZING_COLOR),
    "success": FinalizerStateStyle(glyph="✓", word="success", color=SUCCESS_COLOR),
    "failed": FinalizerStateStyle(glyph="✗", word="failed", color=FAILURE_COLOR),
    "refused": FinalizerStateStyle(glyph="⊘", word="refused", color=REFUSED_COLOR),
    "deferred": FinalizerStateStyle(glyph="⏸", word="deferred", color=WARNING_COLOR),
    "not triggered": FinalizerStateStyle(glyph="○", word="not triggered", color="dim"),
    "skipped": FinalizerStateStyle(glyph="○", word="skipped", color="dim"),
    "not run": FinalizerStateStyle(glyph="–", word="not run", color="dim"),
    "not reached": FinalizerStateStyle(glyph="–", word="not reached", color="dim"),
    "interrupted": FinalizerStateStyle(
        glyph="!", word="interrupted", color=WARNING_COLOR
    ),
    "unavailable": FinalizerStateStyle(
        glyph="⚠", word="unavailable", color=f"dim {WARNING_COLOR}"
    ),
}

#: C5 per-instance statuses to §3.2 style keys. ``waiting`` renders as the
#: ``planned`` calm state; ``after X`` waits keep the planned word.
INSTANCE_STATUS_STYLES: dict[str, str] = {
    "planned": "planned",
    "waiting": "planned",
    "running": "running",
    "success": "success",
    "failed": "failed",
    "refused": "refused",
    "deferred": "deferred",
    "not_triggered": "not triggered",
    "skipped": "skipped",
    "not_run": "not run",
}

#: C5 run phases to §3.2 style keys for the run-level word.
RUN_PHASE_STYLES: dict[str, str] = {
    "planned": "planned",
    "skipped": "skipped",
    "declaring": "declaration",
    "executing": "running",
    "settled": "success",
    "interrupted": "interrupted",
}


def instance_style(status: str | None) -> FinalizerStateStyle:
    """Return the shared style for a C5 per-instance *status*."""
    return STATE_STYLES[INSTANCE_STATUS_STYLES.get(status or "", "planned")]


__all__ = [
    "FINAL_DECK_ACCENT",
    "FINAL_GLYPH",
    "FINALIZING_COLOR",
    "FAILURE_COLOR",
    "REFUSED_COLOR",
    "STATE_STYLES",
    "FinalizerStateStyle",
    "SUCCESS_COLOR",
    "WARNING_COLOR",
    "instance_style",
]
