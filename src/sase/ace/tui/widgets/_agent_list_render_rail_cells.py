"""Fixed-width agent and banner cell builders for the Agents-tab rail.

Kind badges, tree guides, folded counts, and banner prefixes assemble
into exactly ``RAIL_CONTENT_CELLS`` cells. Pure functions only — no
Textual widget imports, no disk I/O.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from typing import TYPE_CHECKING, Any

from rich.cells import cell_len
from rich.text import Text

from sase.agent.status_buckets import agent_status_bucket

from ..models._agent_tree import agent_tree_depth
from ..models.agent import AgentType
from ..models.agent_groups import GroupingMode, banner_label
from ..models.agent_relative_label import relative_agent_label
from ..models.agent_status import STOPPED_COLOR, STOPPED_STATUS
from ._agent_list_render_rail_names import (
    rail_middle_elide,
    rail_name_is_dimmed,
    rail_row_name,
)
from ._agent_list_render_rail_vocab import (
    RAIL_BUCKET_GLYPHS,
    RAIL_CONTENT_CELLS,
    RAIL_COUNT_CAP,
    RAIL_DONE_READ_STYLE,
    RAIL_FAILED_STYLE,
    RAIL_GATE_GLYPH,
    RAIL_HINT_STYLE,
    RAIL_MARKED_PIP,
    RAIL_MARKED_PIP_STYLE,
    RAIL_MAX_DEPTH,
    RAIL_MONITOR_GLYPH,
    RAIL_NEEDS_YOU_STYLE,
    RAIL_UNREAD_PIP,
    RAIL_UNREAD_STYLE,
    gate_glyph_style,
    monitor_glyph_style,
)
from ._agent_list_styling import (
    _AGENT_SESSION_NAME_STYLE,
    _AGENT_TYPE_COLORS,
    _CLAN_NAME_STYLE,
    _MONITOR_GLYPH_STYLE,
    _NAMED_PROC_GLYPH,
    _NAMED_PROC_GLYPH_STYLE,
    _STEP_TYPE_COLORS,
    _STEP_TYPE_GLYPHS,
    _TYPE_GLYPHS,
    TREE_DEPTH_COLORS,
)

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.agent_groups import GroupRow

# Expanded-density tree connector vocabulary, reused single-cell.
_RAIL_BRANCH_GLYPH = "└"
_RAIL_GUIDE_GLYPH = "│"

# Agent-row tail: 3-cell right-aligned count ending at cell 16, 1-cell gap,
# 1-cell pip at cell 18.
_RAIL_COUNT_CELLS = 3


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


__all__ = [
    "rail_agent_cells",
    "rail_banner_cells",
    "row_kind_glyph",
]
