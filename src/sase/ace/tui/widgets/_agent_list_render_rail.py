"""Pure node-rail vocabulary for the Agents-tab rail density.

Single source of truth for everything the rail draws: geometry constants,
the glyph and color vocabulary, fixed-width cell builders for agent rows,
banners, tribe titles, and overflow, plus the tooltip text helper and the
help-modal legend entries. Pure functions only — no Textual widget imports,
no disk I/O.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Mapping
from typing import TYPE_CHECKING, Any

from rich.cells import cell_len
from rich.text import Text

from sase.agent.status_buckets import agent_status_bucket

from ..models._agent_tree import agent_tree_depth
from ..models.agent import AgentType
from ..models.agent_groups import GroupingMode, banner_label
from ..models.agent_panels import agent_panel_label
from ..models.agent_relative_label import relative_agent_label
from ..models.agent_status import RUNNING_COLOR, STOPPED_COLOR, STOPPED_STATUS
from ..models.tribe_display import compose_tribe_identity_style
from ._agent_list_render_rail_names import (
    rail_middle_elide,
    rail_name_is_dimmed,
    rail_row_name,
)
from ._agent_list_styling import (
    _AGENT_SESSION_NAME_STYLE,
    _AGENT_TYPE_COLORS,
    _CLAN_NAME_STYLE,
    _GATE_FAILED_COUNT_GLYPH_STYLE,
    _GATE_GLYPH,
    _GATE_ROW_STYLE,
    _GATE_SETTLED_COUNT_GLYPH_STYLE,
    _MONITOR_GLYPH,
    _MONITOR_GLYPH_STYLE,
    _MONITOR_SETTLED_GLYPH_STYLE,
    _NAMED_PROC_GLYPH,
    _NAMED_PROC_GLYPH_STYLE,
    _STEP_TYPE_COLORS,
    _STEP_TYPE_GLYPHS,
    _TYPE_GLYPHS,
    TREE_DEPTH_COLORS,
)
from ..models.agent_session_members import (
    gate_row_is_settled,
    monitor_row_is_settled,
)

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.agent_groups import GroupRow
    from ..models.agent_panels import PanelKey
    from ..actions.agents._display_panel_titles import AgentPanelCounts

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

#: Bucket name → ``(glyph, style)`` for all seven status buckets. The TUI
#: rail and TUI banners share this map; the CLI ``AGENT_STATUS_BUCKET_GLYPHS``
#: map stays untouched.
RAIL_BUCKET_GLYPHS: dict[str, tuple[str, str]] = {
    "Stopped": ("?", RAIL_NEEDS_YOU_STYLE),
    "Failed": ("✗", RAIL_FAILED_STYLE),
    "Starting": ("◐", "bold #87D7FF"),
    "Running": ("▶", RUNNING_COLOR),
    "Queued": ("○", "#5F87FF"),
    "Waiting": ("◷", "#AF87FF"),
    # Done rows refine bold/dim by unread state in ``rail_agent_cells``;
    # the map keeps the unread (bold) rung.
    "Done": ("✓", "bold #5FD75F"),
}
RAIL_DONE_READ_STYLE = "dim #5FD75F"

# Static kind glyphs for the legend and for rows whose kind outranks status.
RAIL_MONITOR_GLYPH = _MONITOR_GLYPH
RAIL_GATE_GLYPH = _GATE_GLYPH
RAIL_WORKFLOW_GLYPH = "≡"
RAIL_STEP_GLYPH = "❯"
RAIL_PATCH_GLYPH = "❑"
RAIL_FOLD_GLYPH = "▸"
RAIL_MARKED_PIP = "▪"
RAIL_UNREAD_PIP = "•"

# Expanded-density tree connector vocabulary, reused single-cell.
_RAIL_BRANCH_GLYPH = "└"
_RAIL_GUIDE_GLYPH = "│"

# Tooltip collapsing: the expanded row's right-alignment pad run becomes
# two spaces so hover text stays compact.
_TOOLTIP_PAD_RUN = re.compile(r" {3,}")

# Agent-row tail: 3-cell right-aligned count ending at cell 16, 1-cell gap,
# 1-cell pip at cell 18.
_RAIL_COUNT_CELLS = 3


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


def row_kind_glyph(
    agent: Agent, *, is_expanded: bool = False
) -> tuple[str, str] | None:
    """Return the ``(glyph, style)`` kind badge for *agent*, if it has one.

    Mirrors the glyph selection in the expanded row prefix exactly — the
    prefix calls this helper so the two densities cannot drift. ``None``
    means the row shows its status glyph instead (plain agents, agent-type
    workflow steps, clan/session containers, and unknown display types
    whose expanded ``[X]`` badge cannot fit in one cell).

    Precedence: monitor > gate > named proc (depth 0 only) > workflow-step
    glyph > top-level type badge.
    """
    depth = agent_tree_depth(agent)
    if depth > 0:
        if agent.is_monitor:
            return (RAIL_MONITOR_GLYPH, monitor_glyph_style(agent))
        if agent.is_gate:
            return (RAIL_GATE_GLYPH, gate_glyph_style(agent))
        if agent.is_workflow_step_child:
            step_glyph = _STEP_TYPE_GLYPHS.get(agent.step_type or "")
            if step_glyph is not None:
                step_color = _STEP_TYPE_COLORS.get(agent.step_type or "", "#FFFFFF")
                return (step_glyph, f"bold {step_color}")
        return None
    if agent.is_monitor:
        return (RAIL_MONITOR_GLYPH, monitor_glyph_style(agent))
    if agent.is_gate:
        return (RAIL_GATE_GLYPH, gate_glyph_style(agent))
    if agent.is_named_proc:
        return (_NAMED_PROC_GLYPH, _NAMED_PROC_GLYPH_STYLE)
    if agent.is_clan_container or agent.is_agent_session_container_row:
        return None
    is_appears_as_agent = agent.appears_as_agent and not (
        agent.is_anonymous and is_expanded
    )
    if (
        is_appears_as_agent
        or agent_tree_depth(agent) > 0
        or agent.is_monitor
        or agent.is_gate
        or agent.is_named_proc
    ):
        return None
    display_type = agent.get_display_type(is_expanded=is_expanded)
    type_glyph = _TYPE_GLYPHS.get(display_type)
    if type_glyph is None:
        return None
    if agent.is_monitor:
        color = _MONITOR_GLYPH_STYLE.removeprefix("bold ")
    elif agent.is_gate:
        color = gate_glyph_style(agent).removeprefix("bold ")
    elif agent.is_named_proc:
        color = _NAMED_PROC_GLYPH_STYLE.removeprefix("bold ")
    elif is_appears_as_agent:
        color = _AGENT_TYPE_COLORS[AgentType.RUNNING]
    elif agent.is_workflow_step_child and agent.step_type in _STEP_TYPE_COLORS:
        color = _STEP_TYPE_COLORS[agent.step_type]
    else:
        color = _AGENT_TYPE_COLORS.get(agent.agent_type, "#FFFFFF")
    return (type_glyph, f"bold {color}")


def _tree_guide_cells(depth: int) -> Text:
    """Return the leading guide cells for a clamped *depth*.

    One ``│`` per ancestor level plus a terminal ``└``, each in its
    level's ``TREE_DEPTH_COLORS`` color.
    """
    text = Text()
    if depth <= 0:
        return text
    for level in range(depth - 1):
        text.append(
            _RAIL_GUIDE_GLYPH, style=TREE_DEPTH_COLORS[level % len(TREE_DEPTH_COLORS)]
        )
    text.append(
        _RAIL_BRANCH_GLYPH,
        style=TREE_DEPTH_COLORS[(depth - 1) % len(TREE_DEPTH_COLORS)],
    )
    return text


def _pad_cells(text: str, width: int) -> str:
    """Pad ASCII *text* on the right to *width* cells."""
    shortfall = width - cell_len(text)
    if shortfall <= 0:
        return text
    return text + " " * shortfall


def rail_agent_cells(
    agent: Agent,
    ctx: Mapping[str, Any],
    *,
    depth: int,
    anchor_name: str | None = None,
) -> Text:
    """Build the fixed-width rail cells for one agent row.

    Returns exactly ``RAIL_CONTENT_CELLS`` cells: guides, one glyph cell,
    the (possibly relative, middle-elided) name, a right-aligned ``×N``
    count ending at cell 16, and the pip at cell 18.

    - ``G`` is the jump-hint chip, else the kind glyph, else the status
      glyph (raw ``STOPPED`` maps to ``Ø``);
    - a 1-character hint replaces ``G``; a 2-character hint replaces ``G``
      and the following space, so the name column never moves;
    - ``×N`` shows only when ``ctx["folded_total"]`` is set (the folded
      total from the expanded row), capped at ``×99`` and tinted dim in
      the container color;
    - the pip is marked ``▪`` winning over unread ``•``;
    - settled-and-read names render dim.
    """
    clamped = min(max(depth, 0), RAIL_MAX_DEPTH)
    guides = _tree_guide_cells(clamped)
    hint = ctx.get("hint_char")
    hint_text = hint[:2] if isinstance(hint, str) and hint else ""
    is_unread = bool(ctx.get("is_unread"))
    is_marked = bool(ctx.get("is_marked"))

    kind = row_kind_glyph(agent, is_expanded=bool(ctx.get("is_expanded", False)))
    if kind is not None:
        glyph, glyph_style = kind
    elif agent.status == STOPPED_STATUS:
        glyph, glyph_style = "Ø", f"bold {STOPPED_COLOR}"
    else:
        bucket = agent_status_bucket(agent)
        glyph, style = RAIL_BUCKET_GLYPHS.get(bucket, RAIL_BUCKET_GLYPHS["Running"])
        if bucket == "Done" and not is_unread:
            style = RAIL_DONE_READ_STYLE
        glyph_style = style

    folded_total = ctx.get("folded_total")
    if folded_total is not None:
        try:
            total = int(folded_total)
        except (TypeError, ValueError):
            total = 0
        count_str = f"×{min(max(total, 0), RAIL_COUNT_CAP)}"
        if agent.is_clan_container:
            count_style = f"dim {_CLAN_NAME_STYLE}"
        elif agent.is_agent_session_container_row:
            count_style = f"dim {_AGENT_SESSION_NAME_STYLE}"
        else:
            count_style = "dim"
    else:
        count_str = ""
        count_style = ""

    if is_marked:
        pip, pip_style = RAIL_MARKED_PIP, RAIL_MARKED_PIP_STYLE
    elif is_unread:
        pip, pip_style = RAIL_UNREAD_PIP, RAIL_UNREAD_STYLE
    else:
        pip, pip_style = " ", ""

    full_name, name_style = rail_row_name(agent)
    relative = relative_agent_label(full_name, anchor_name)
    if relative and rail_name_is_dimmed(agent, is_unread=is_unread):
        name_style = (
            f"dim {name_style}" if not name_style.startswith("dim ") else name_style
        )

    name_budget = RAIL_CONTENT_CELLS - (clamped + 2) - _RAIL_COUNT_CELLS - 2
    shown = rail_middle_elide(relative, name_budget) if relative else ""
    name_cells = cell_len(shown)
    name_pad = " " * max(0, name_budget - name_cells)

    text = Text()
    text.append_text(guides)
    if hint_text:
        text.append(hint_text, style=RAIL_HINT_STYLE)
        if len(hint_text) == 1:
            text.append(" ")
    else:
        text.append(glyph, style=glyph_style)
        text.append(" ")
    if shown:
        text.append(shown, style=name_style)
    if name_pad:
        text.append(name_pad)
    if count_str:
        text.append(_pad_cells("", _RAIL_COUNT_CELLS - cell_len(count_str)), style="")
        text.append(count_str, style=count_style)
    else:
        text.append(" " * _RAIL_COUNT_CELLS)
    text.append(" ")
    if pip == " ":
        text.append(" ")
    else:
        text.append(pip, style=pip_style)
    return text


def _rail_urgency(
    agents: Collection[Agent],
    unread: Collection[Any],
) -> Text:
    """Return the 1-cell urgency roll-up shared by folded banners and titles.

    The ``?`` chip wins when any member needs the user (``Stopped``
    bucket), else a red ``✗`` when any member failed, else a gold ``•``
    when any member is unread, else a blank cell.
    """
    unread_ids = set(unread or ())
    buckets = [agent_status_bucket(agent) for agent in agents]
    if "Stopped" in buckets:
        return Text("?", style=RAIL_NEEDS_YOU_STYLE)
    if "Failed" in buckets:
        return Text("✗", style=RAIL_FAILED_STYLE)
    if any(agent.identity in unread_ids for agent in agents):
        return Text("•", style=RAIL_UNREAD_STYLE)
    return Text(" ")


def _top_level_members(group: GroupRow, agents: list[Agent]) -> list[Agent]:
    """Return the group's top-level (non-tree-child) member agents."""
    from ..models._agent_tree import agent_is_tree_child as _is_child

    members: list[Agent] = []
    for idx in group.agent_indices:
        if 0 <= idx < len(agents) and not _is_child(agents[idx]):
            members.append(agents[idx])
    return members


def rail_banner_cells(
    group: GroupRow,
    agents: list[Agent],
    *,
    mode: GroupingMode = GroupingMode.STANDARD,
    unread: Collection[Any] = (),
    hint: str | None = None,
    mark_state: str = "none",
) -> Text:
    """Build the fixed-width rail cells for one banner row.

    Returns exactly ``RAIL_CONTENT_CELLS`` cells: the shared expanded
    prefix vocabulary, the middle-elided label, and the heavy (L0) or
    light rule in the expanded rule style (always at least 1 cell).
    Folded banners add the top-level member count ``×N`` in the shared
    count column and the 1-cell urgency roll-up in the pip column; the
    ``▸`` fold mark is retired, so ``×N`` means "folded, N inside".

    A hint chip plus a space replaces the prefix, or is prepended when
    the prefix is empty. ``mark_state`` is accepted for API parity with
    the expanded banner and does not alter the layout.
    """
    del mark_state
    from ._agent_list_render_banner import banner_prefix_segments

    label = banner_label(group)
    hint_text = hint[:2] if isinstance(hint, str) and hint else ""
    prefix_segments, rule_char, label_style, rule_style = banner_prefix_segments(
        group, agents, mode
    )

    text = Text()
    if hint_text:
        text.append(hint_text, style=RAIL_HINT_STYLE)
        text.append(" ")
        prefix_cells = cell_len(hint_text) + 1
        prefix_styles: list[tuple[str, str]] = []
    else:
        prefix_cells = 0
        prefix_styles = []
        for segment_text, segment_style in prefix_segments:
            if segment_text:
                text.append(segment_text, style=segment_style)
                prefix_cells += cell_len(segment_text)
                prefix_styles.append((segment_text, segment_style))

    if not group.is_collapsed:
        label_budget = RAIL_CONTENT_CELLS - prefix_cells - 2
        shown_label = rail_middle_elide(label, label_budget) if label_budget > 0 else ""
        if shown_label:
            text.append(shown_label, style=label_style)
        text.append(" ", style=rule_style)
        rule_len = RAIL_CONTENT_CELLS - prefix_cells - cell_len(shown_label) - 1
        text.append(rule_char * max(1, rule_len), style=rule_style)
        return text

    members = _top_level_members(group, agents)
    count_str = f"×{min(len(members), RAIL_COUNT_CAP)}"
    urgency = _rail_urgency(members, unread)
    label_budget = RAIL_CONTENT_CELLS - prefix_cells - 1 - 1 - _RAIL_COUNT_CELLS - 1 - 1
    shown_label = rail_middle_elide(label, label_budget) if label_budget > 0 else ""
    if shown_label:
        text.append(shown_label, style=label_style)
    text.append(" ", style=rule_style)
    rule_len = (
        RAIL_CONTENT_CELLS
        - prefix_cells
        - cell_len(shown_label)
        - 1
        - _RAIL_COUNT_CELLS
        - 1
        - 1
    )
    text.append(rule_char * max(1, rule_len), style=rule_style)
    text.append(
        _pad_cells("", _RAIL_COUNT_CELLS - cell_len(count_str)), style=rule_style
    )
    text.append(count_str, style=rule_style)
    text.append(" ")
    text.append_text(urgency)
    return text


def rail_panel_title(
    *,
    key: PanelKey,
    hint: str | None = None,
    selected: bool = False,
    collapsed: bool = False,
    merged: bool = False,
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
            "▸",
            RAIL_COLLAPSED_MARK_STYLE if selected else RAIL_COLLAPSED_MARK_DIM_STYLE,
        )
    else:
        mark, mark_style = "", ""
    use_icon = bool(icon) and not merged and Text(icon).cell_len <= 2
    if merged:
        label_text, label_style = "All agents", "bold #AFFFFF"
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
    "RAIL_CONTENT_CELLS",
    "RAIL_COUNT_CAP",
    "RAIL_DONE_READ_STYLE",
    "RAIL_HINT_STYLE",
    "RAIL_LEGEND",
    "RAIL_MAX_DEPTH",
    "RAIL_NEEDS_YOU_STYLE",
    "RAIL_TITLE_CELLS",
    "gate_glyph_style",
    "monitor_glyph_style",
    "rail_agent_cells",
    "rail_banner_cells",
    "rail_overflow_subtitle",
    "rail_panel_title",
    "rail_tooltip_text",
    "row_kind_glyph",
]
