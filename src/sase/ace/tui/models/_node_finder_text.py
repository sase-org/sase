"""Node Finder display helpers: glyphs, navigation, and status text.

Split from :mod:`sase.ace.tui.models.node_finder`: pure helpers that
render one filtered row's hidden-reason glyph, step the cursor across
jumpable rows, and build the preview's why-hidden and Enter-action
status lines.
"""

from __future__ import annotations

from .agent_panels import agent_panel_label
from ._node_finder_types import (
    REASON_PRECEDENCE,
    NodeFinderReason,
    NodeFinderRow,
    NodeFinderView,
)

_REASON_GLYPH: dict[NodeFinderReason, str] = {
    NodeFinderReason.QUERY: "⊘",
    NodeFinderReason.NON_RUN: "◌",
    NodeFinderReason.PANEL: "▭",
    NodeFinderReason.BANNER: "≡",
    NodeFinderReason.FOLDED: "▸",
}


def node_finder_glyph(row: NodeFinderRow) -> str:
    """Return the single why-hidden glyph for *row* (``""`` when visible)."""
    if row.is_here:
        return "◆"
    for reason in REASON_PRECEDENCE:
        if reason in row.reasons:
            return _REASON_GLYPH[reason]
    return ""


def next_jumpable_index(view: NodeFinderView, index: int, direction: int) -> int:
    """Return the next jumpable row index from *index*, wrapping around."""
    total = len(view.rows)
    if total == 0:
        return index
    step = 1 if direction >= 0 else -1
    current = index
    for _ in range(total):
        current = (current + step) % total
        row = view.rows[current]
        if row.jumpable and current not in view.context:
            return current
    return index


def node_finder_reason_text(row: NodeFinderRow, query: str) -> str:
    """Build the preview's why-hidden status lines for *row*."""
    if row.is_here:
        return "◆ You are here"
    lines: list[str] = []
    for reason in REASON_PRECEDENCE:
        if reason not in row.reasons:
            continue
        if reason is NodeFinderReason.QUERY:
            lines.append(f"⊘ Hidden by the Agents query ‹{query}›")
        elif reason is NodeFinderReason.NON_RUN:
            lines.append("◌ Hidden by I (hide non-run agents)")
        elif reason is NodeFinderReason.PANEL:
            lines.append(f"▭ Inside hidden panel {agent_panel_label(row.panel_key)}")
        elif reason is NodeFinderReason.BANNER:
            label = row.group_label or "its group"
            lines.append(f"≡ Inside collapsed group {label}")
        elif reason is NodeFinderReason.FOLDED:
            target = row.nearest_collapsed or "a collapsed fold"
            lines.append(f"▸ Inside collapsed {target}")
    return "\n".join(lines)


def node_finder_action_text(row: NodeFinderRow, query: str) -> str:
    """Build the preview's Enter-action status line for *row*."""
    _ = query
    if not row.reasons:
        return "⏎ selects it"
    parts: list[str] = []
    if NodeFinderReason.QUERY in row.reasons:
        parts.append("clears the Agents query")
    if NodeFinderReason.NON_RUN in row.reasons:
        parts.append("shows agents hidden by I")
    if NodeFinderReason.PANEL in row.reasons:
        parts.append(f"opens {agent_panel_label(row.panel_key)}")
    if NodeFinderReason.BANNER in row.reasons:
        parts.append("opens its group")
    if NodeFinderReason.FOLDED in row.reasons:
        count = row.unmet_fold_count
        parts.append(f"expands {count} fold{'s' if count != 1 else ''}")
    return "⏎ " + ", ".join(parts) + ", then selects it"
