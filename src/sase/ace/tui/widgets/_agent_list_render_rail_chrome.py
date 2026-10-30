"""Tribe-title, overflow, and tooltip chrome for the Agents-tab rail.

Panel titles and overflow subtitles stay within ``RAIL_TITLE_CELLS``.
Pure functions only — no Textual widget imports, no disk I/O.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from rich.cells import cell_len
from rich.text import Text

from ..models.agent_panels import agent_panel_label
from ..models.tribe_display import compose_tribe_identity_style
from ._agent_list_render_rail_names import rail_middle_elide
from ._agent_list_render_rail_vocab import (
    RAIL_COLLAPSED_MARK_DIM_STYLE,
    RAIL_COLLAPSED_MARK_STYLE,
    RAIL_FAILED_STYLE,
    RAIL_FOLD_GLYPH,
    RAIL_HINT_STYLE,
    RAIL_NEEDS_YOU_STYLE,
    RAIL_TITLE_CELLS,
    RAIL_UNREAD_STYLE,
)

if TYPE_CHECKING:
    from ..actions.agents._display_panel_titles import AgentPanelCounts
    from ..models.agent_panels import PanelKey

# Tooltip collapsing: the expanded row's right-alignment pad run becomes
# two spaces so hover text stays compact.
_TOOLTIP_PAD_RUN = re.compile(r" {3,}")


def rail_panel_title(
    *,
    key: PanelKey,
    hint: str | None = None,
    selected: bool = False,
    collapsed: bool = False,
    merged: bool = False,
    merged_title: str | None = None,
    icon: str = "",
    color: str = "",
    counts: AgentPanelCounts | None = None,
) -> Text:
    """Build the rail tribe title, at most ``RAIL_TITLE_CELLS`` cells.

    Left-aligned pieces mirror :func:`agent_panel_border_title`:

    1. ``[hint]`` while panel hints are up (never dropped);
    2. ``❖`` for whole-panel focus, or ``▸`` for a collapsed tribe;
    3. the configured tribe icon when its ``cell_len`` is at most 2;
    4. ``agent_panel_label(key)`` or ``All agents`` for merged panels;
    5. on collapsed tribes only, `` ×{lane_count}`` in dim;
    6. on collapsed tribes only, the urgency roll-up.

    When over budget, pieces drop in this order: mark, then icon, then
    ``×N``. The hint, the label (middle-elided, minimum 3 cells), and
    the roll-up are never dropped.
    """
    identity_style = compose_tribe_identity_style(color, bold=True)
    hint_text = hint[:2] if isinstance(hint, str) and hint else ""
    if selected and not collapsed:
        mark, mark_style = "❖", RAIL_COLLAPSED_MARK_STYLE
    elif collapsed:
        mark, mark_style = (
            RAIL_FOLD_GLYPH,
            RAIL_COLLAPSED_MARK_STYLE if selected else RAIL_COLLAPSED_MARK_DIM_STYLE,
        )
    else:
        mark, mark_style = "", ""
    use_icon = bool(icon) and not merged and Text(icon).cell_len <= 2
    if merged:
        label_text, label_style = merged_title or "All agents", "bold #AFFFFF"
    else:
        label_text, label_style = agent_panel_label(key), identity_style
    urgency_text, urgency_style = "", ""
    count_text = ""
    if collapsed and counts is not None:
        asking = getattr(counts, "asking", 0) or 0
        failed = getattr(counts, "failed", 0) or 0
        unread_count = getattr(counts, "unread", 0) or 0
        if asking:
            urgency_text, urgency_style = "?", RAIL_NEEDS_YOU_STYLE
        elif failed:
            urgency_text, urgency_style = "✗", RAIL_FAILED_STYLE
        elif unread_count:
            urgency_text, urgency_style = "•", RAIL_UNREAD_STYLE
        lane_count = getattr(counts, "lane_count", 0) or 0
        count_text = f" ×{lane_count}"

    def width(
        *,
        with_mark: bool,
        with_icon: bool,
        with_count: bool,
        label_cells: int,
    ) -> int:
        total = 0
        if hint_text:
            total += Text(hint_text).cell_len + 1
        if with_mark and mark:
            total += Text(mark).cell_len + 1
        if with_icon and use_icon:
            total += Text(icon).cell_len + 1
        total += label_cells
        if with_count and count_text:
            total += Text(count_text).cell_len
        if urgency_text:
            total += 1 + Text(urgency_text).cell_len
        return total

    use_mark = bool(mark)
    with_icon = use_icon
    with_count = bool(count_text)
    label_budget = RAIL_TITLE_CELLS - (
        width(
            with_mark=use_mark,
            with_icon=with_icon,
            with_count=with_count,
            label_cells=cell_len(label_text),
        )
        - cell_len(label_text)
    )
    if (
        width(
            with_mark=use_mark,
            with_icon=with_icon,
            with_count=with_count,
            label_cells=cell_len(label_text),
        )
        > RAIL_TITLE_CELLS
    ):
        use_mark = False
    if (
        width(
            with_mark=use_mark,
            with_icon=with_icon,
            with_count=with_count,
            label_cells=cell_len(label_text),
        )
        > RAIL_TITLE_CELLS
    ):
        with_icon = False
    if (
        width(
            with_mark=use_mark,
            with_icon=with_icon,
            with_count=with_count,
            label_cells=cell_len(label_text),
        )
        > RAIL_TITLE_CELLS
    ):
        with_count = False
    fixed = width(
        with_mark=use_mark,
        with_icon=with_icon,
        with_count=with_count,
        label_cells=0,
    )
    label_budget = max(3, RAIL_TITLE_CELLS - fixed)
    shown_label = rail_middle_elide(label_text, label_budget)

    title = Text()
    if hint_text:
        title.append(hint_text, style=RAIL_HINT_STYLE)
        title.append(" ")
    if use_mark and mark:
        title.append(mark, style=mark_style)
        title.append(" ")
    if with_icon and use_icon:
        title.append(icon, style=identity_style)
        title.append(" ")
    title.append(shown_label, style=label_style)
    if with_count and count_text:
        title.append(count_text, style="dim")
    if urgency_text:
        title.append(" ")
        title.append(urgency_text, style=urgency_style)
    return title


def rail_overflow_subtitle(above: int, below: int) -> Text:
    """Build the rail overflow subtitle, at most ``RAIL_TITLE_CELLS`` cells.

    ``▴N ▾M`` names the rows above and below the viewport, degrading to
    ``▴▾`` when both counts cannot fit, then to a single arrow. A lone
    side degrades to its bare arrow. Empty when everything fits.
    """
    above_count = max(0, int(above))
    below_count = max(0, int(below))
    if not above_count and not below_count:
        return Text("")
    if above_count and below_count:
        full = f"▴{above_count} ▾{below_count}"
        if Text(full).cell_len <= RAIL_TITLE_CELLS:
            return Text(full)
        degraded = "▴▾"
        if Text(degraded).cell_len <= RAIL_TITLE_CELLS:
            return Text(degraded)
        return Text("▴" if above_count >= below_count else "▾")
    if above_count:
        full = f"▴{min(above_count, 9999)}"
        if Text(full).cell_len <= RAIL_TITLE_CELLS:
            return Text(full)
        return Text("▴")
    full = f"▾{min(below_count, 9999)}"
    if Text(full).cell_len <= RAIL_TITLE_CELLS:
        return Text(full)
    return Text("▾")


def rail_tooltip_text(prompt: Text) -> Text | None:
    """Return the hover tooltip for a rail row's expanded *prompt*.

    The prompt's right-alignment pad run collapses to two spaces so the
    tooltip names the row without the alignment gap. Spacer and blank
    prompts give ``None``.
    """
    plain = prompt.plain
    if not plain.strip():
        return None
    return Text(_TOOLTIP_PAD_RUN.sub("  ", plain))


__all__ = [
    "rail_overflow_subtitle",
    "rail_panel_title",
    "rail_tooltip_text",
]
