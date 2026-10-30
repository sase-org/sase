"""Glyph, style, and geometry vocabulary for the Agents-tab node rail.

Kind-badge styles, bucket glyphs, and the help-modal legend live here so
row-cell and chrome builders share one source of truth. Pure functions
only — no Textual widget imports, no disk I/O.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

from ..models.agent_groups import MONITORING_STATUS_GROUP
from ..models.agent_status import RUNNING_COLOR, STOPPED_COLOR
from ..models.agent_session_members import (
    gate_row_is_settled,
    monitor_row_is_settled,
)
from ._agent_list_styling import (
    _GATE_FAILED_COUNT_GLYPH_STYLE,
    _GATE_GLYPH,
    _GATE_ROW_STYLE,
    _GATE_SETTLED_COUNT_GLYPH_STYLE,
    _MONITOR_GLYPH,
    _MONITOR_GLYPH_STYLE,
    _MONITOR_SETTLED_GLYPH_STYLE,
)

if TYPE_CHECKING:
    from ..models.agent import Agent

# Total rail width in cells: 2 tribe-panel border cells + 1 selection
# gutter (where the highlight bar lands) + 19 content cells.
NODE_RAIL_WIDTH = 22
# Fixed content width every rail row builder returns.
RAIL_CONTENT_CELLS = 19
# Maximum tribe-title width inside the rail border.
RAIL_TITLE_CELLS = 18
# Tree guides clamp here; relative names stay short.
RAIL_MAX_DEPTH = 3
# Container member counts saturate here.
RAIL_COUNT_CAP = 99

# Reverse amber chip for rows that need the user; deliberately distinct
# from the gold unread pip.
RAIL_NEEDS_YOU_STYLE = "bold #1a1a1a on #FFAF00"
# Transient jump-hint chip, same yellow as the expanded ``[hint]`` prefix.
RAIL_HINT_STYLE = "bold #1a1a1a on #FFFF00"
# Gold unread pip; amber stays reserved for the needs-you chip so the two
# never read as each other.
RAIL_UNREAD_STYLE = "bold #FFD700"
RAIL_MARKED_PIP_STYLE = "bold #00D700"
RAIL_FAILED_STYLE = "bold #FF5F5F"
RAIL_COLLAPSED_MARK_STYLE = "#FFD75F"
RAIL_COLLAPSED_MARK_DIM_STYLE = "#AFAFAF"

# Static kind glyph for monitor rows, also used for the grouping-only
# Monitoring bucket banner. Defined before the bucket map so the map can
# reference it.
RAIL_MONITOR_GLYPH = _MONITOR_GLYPH

#: Bucket name → ``(glyph, style)`` for all status buckets. The TUI
#: rail and TUI banners share this map; the CLI ``AGENT_STATUS_BUCKET_GLYPHS``
#: map stays untouched.
RAIL_BUCKET_GLYPHS: dict[str, tuple[str, str]] = {
    "Stopped": ("?", RAIL_NEEDS_YOU_STYLE),
    "Failed": ("✗", RAIL_FAILED_STYLE),
    "Starting": ("◐", "bold #87D7FF"),
    "Running": ("▶", RUNNING_COLOR),
    # Grouping-only label that ``agent_status_bucket`` never returns, so the
    # per-row rail glyph lookup in ``rail_agent_cells`` is unaffected.
    MONITORING_STATUS_GROUP: (RAIL_MONITOR_GLYPH, _MONITOR_GLYPH_STYLE),
    "Queued": ("○", "#5F87FF"),
    "Waiting": ("◷", "#AF87FF"),
    # Done rows refine bold/dim by unread state in ``rail_agent_cells``;
    # the map keeps the unread (bold) rung.
    "Done": ("✓", "bold #5FD75F"),
}
RAIL_DONE_READ_STYLE = "dim #5FD75F"

# Static kind glyphs for the legend and for rows whose kind outranks status.
RAIL_GATE_GLYPH = _GATE_GLYPH
RAIL_WORKFLOW_GLYPH = "≡"
RAIL_STEP_GLYPH = "❯"
RAIL_PATCH_GLYPH = "❑"
RAIL_FOLD_GLYPH = "▸"
RAIL_MARKED_PIP = "▪"
RAIL_UNREAD_PIP = "•"


def monitor_glyph_style(agent: Agent) -> str:
    """Return the row gear style for a monitor turn.

    Shares ``monitor_row_is_settled`` with the ``⚙N`` lane counts so a grey
    gear on a row and the grey count it feeds can never disagree.
    """
    return (
        _MONITOR_SETTLED_GLYPH_STYLE
        if monitor_row_is_settled(agent)
        else _MONITOR_GLYPH_STYLE
    )


def gate_glyph_style(agent: Agent) -> str:
    """Return the row glyph style for a gate turn."""
    if agent.gate_state in {"failed", "timeout", "lost"}:
        return _GATE_FAILED_COUNT_GLYPH_STYLE
    if gate_row_is_settled(agent):
        return _GATE_SETTLED_COUNT_GLYPH_STYLE
    if agent.gate_accent:
        return f"bold {agent.gate_accent}"
    return _GATE_ROW_STYLE


#: Ordered ``(glyph, meaning)`` pairs backing the help-modal node-rail
#: legend. Glyphs carry their rail styles.
RAIL_LEGEND: tuple[tuple[Text, str], ...] = (
    (Text("?", style=RAIL_NEEDS_YOU_STYLE), "needs you — input or review"),
    (Text("✗", style=RAIL_FAILED_STYLE), "failed"),
    (Text("▶", style=f"bold {RUNNING_COLOR}"), "running"),
    (Text("◐", style="bold #87D7FF"), "starting"),
    (Text("○", style="#5F87FF"), "queued"),
    (Text("◷", style="#AF87FF"), "waiting"),
    (Text("✓", style="bold #5FD75F"), "done"),
    (Text("Ø", style=f"bold {STOPPED_COLOR}"), "user-stopped"),
    (Text(RAIL_MONITOR_GLYPH, style=_MONITOR_GLYPH_STYLE), "monitor / named proc"),
    (Text(RAIL_GATE_GLYPH, style=_GATE_ROW_STYLE), "gate turn"),
    (Text(RAIL_WORKFLOW_GLYPH, style="bold #FF87D7"), "workflow"),
    (Text(RAIL_STEP_GLYPH, style="bold #FFAF5F"), "bash / python step"),
    (Text(RAIL_PATCH_GLYPH, style="bold #FF87D7"), "Patch"),
    (Text("×N"), "folded — N inside"),
    (Text(".x"), "name continues its parent's"),
    (Text("✓", style=RAIL_DONE_READ_STYLE), "done and read (dim name)"),
    (Text(RAIL_MARKED_PIP, style=RAIL_MARKED_PIP_STYLE), "marked"),
    (Text(RAIL_UNREAD_PIP, style=RAIL_UNREAD_STYLE), "unread"),
)


__all__ = [
    "NODE_RAIL_WIDTH",
    "RAIL_BUCKET_GLYPHS",
    "RAIL_COLLAPSED_MARK_DIM_STYLE",
    "RAIL_COLLAPSED_MARK_STYLE",
    "RAIL_CONTENT_CELLS",
    "RAIL_COUNT_CAP",
    "RAIL_DONE_READ_STYLE",
    "RAIL_FAILED_STYLE",
    "RAIL_FOLD_GLYPH",
    "RAIL_GATE_GLYPH",
    "RAIL_HINT_STYLE",
    "RAIL_LEGEND",
    "RAIL_MARKED_PIP",
    "RAIL_MARKED_PIP_STYLE",
    "RAIL_MAX_DEPTH",
    "RAIL_MONITOR_GLYPH",
    "RAIL_NEEDS_YOU_STYLE",
    "RAIL_PATCH_GLYPH",
    "RAIL_STEP_GLYPH",
    "RAIL_TITLE_CELLS",
    "RAIL_UNREAD_PIP",
    "RAIL_UNREAD_STYLE",
    "RAIL_WORKFLOW_GLYPH",
    "gate_glyph_style",
    "monitor_glyph_style",
]
