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

from rich.text import Text

from sase.agent.status_buckets import agent_status_bucket

from ..models._agent_clan import clan_members
from ..models._agent_tree import agent_is_tree_child, agent_tree_depth
from ..models.agent import AgentType
from ..models.agent_groups import GroupingMode, banner_label
from ..models.agent_nodes import is_agents_tab_agent_node
from ..models.agent_panels import agent_panel_label
from ..models.agent_session_members import (
    gate_row_is_settled,
    monitor_row_is_settled,
)
from ..models.agent_status import RUNNING_COLOR, STOPPED_COLOR, STOPPED_STATUS
from ..models.tribe_display import compose_tribe_identity_style
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
    _NAME_ROOT_BANNER_BRANCH_STYLE,
    _NAME_ROOT_BANNER_LABEL_STYLE,
    _NAMED_PROC_GLYPH,
    _NAMED_PROC_GLYPH_STYLE,
    _PATCH_BANNER_BAR_STYLE,
    _PROJECT_BANNER_BAR_STYLE,
    _STEP_TYPE_COLORS,
    _STEP_TYPE_GLYPHS,
    _TYPE_GLYPHS,
    TREE_DEPTH_COLORS,
)

if TYPE_CHECKING:
    from ..models.agent import Agent
    from ..models.agent_groups import GroupRow
    from ..models.agent_panels import PanelKey
    from ..actions.agents._display_panel_titles import AgentPanelCounts

# Total rail width in cells: 2 tribe-panel border cells + 1 selection
# gutter (where the highlight bar lands) + 6 content cells.
NODE_RAIL_WIDTH = 9
# Fixed content width every rail row builder returns.
RAIL_CONTENT_CELLS = 6
# Maximum tribe-title width inside the rail border.
RAIL_TITLE_CELLS = 5
# Tree guides clamp here so a row's cells never depend on deep nesting.
RAIL_MAX_DEPTH = 2
# Container member counts saturate here (two count cells).
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
# Expanded banner rule vocabulary: heavy for L0, light below.
_RAIL_HEAVY_RULE = "━"
_RAIL_THIN_RULE = "─"

# Tooltip collapsing: the expanded row's right-alignment pad run becomes
# two spaces so hover text stays compact.
_TOOLTIP_PAD_RUN = re.compile(r" {3,}")


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
        or agent_is_tree_child(agent)
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


def _container_member_count(agent: Agent) -> tuple[int, str] | None:
    """Return ``(count, style)`` for clan/session container rows.

    Counts come from the same member sources as the expanded row's member
    chip and fold state: clan members for clan containers, direct session
    follow-ups for agent-session containers.
    """
    if agent.is_clan_container:
        seen: set[Any] = set()
        for member in clan_members(agent):
            seen.add(member.identity)
        return (len(seen), _CLAN_NAME_STYLE)
    if agent.is_agent_session_container_row:
        seen_followups: set[Any] = set()
        for member in agent.followup_agents:
            if is_agents_tab_agent_node(member):
                seen_followups.add(member.identity)
        return (len(seen_followups), _AGENT_SESSION_NAME_STYLE)
    return None


def _tree_guide_cells(depth: int) -> Text:
    """Return the leading ``│``/``└`` guide cells for a clamped *depth*."""
    text = Text()
    if depth <= 0:
        return text
    if depth == 1:
        text.append(_RAIL_BRANCH_GLYPH, style=TREE_DEPTH_COLORS[0])
        return text
    text.append(_RAIL_GUIDE_GLYPH, style=TREE_DEPTH_COLORS[0])
    text.append(_RAIL_BRANCH_GLYPH, style=TREE_DEPTH_COLORS[1 % len(TREE_DEPTH_COLORS)])
    return text


def rail_agent_cells(
    agent: Agent,
    ctx: Mapping[str, Any],
    *,
    depth: int,
) -> Text:
    """Build the fixed-width rail cells for one agent row.

    Returns exactly ``RAIL_CONTENT_CELLS`` cells from the agent and its
    ``_row_render_ctx`` entry (``hint_char``, ``is_unread``, ``is_marked``):

    - depth 0: ``G c c · · p``; depth 1: ``└ G c c · p``; depth 2+ clamps
      to ``│ └ G c c p`` (guides in ``TREE_DEPTH_COLORS``);
    - ``G`` is the jump-hint chip, else the kind glyph for non-agent
      nodes, else the status glyph (raw ``STOPPED`` maps to ``Ø``);
    - ``c`` is the clan/session member count (capped at 99, tinted by
      container kind), else blank;
    - ``p`` is the pip: marked ``▪`` wins over unread ``•``.

    A 1-character hint replaces ``G``; a 2-character hint also takes the
    first count cell (the count keeps its final digit).
    """
    clamped = min(max(depth, 0), RAIL_MAX_DEPTH)
    text = _tree_guide_cells(clamped)
    hint = ctx.get("hint_char")
    hint_text = hint[:2] if isinstance(hint, str) and hint else ""
    is_unread = bool(ctx.get("is_unread"))
    is_marked = bool(ctx.get("is_marked"))

    # The fold state matches the expanded row's prompt input so the kind
    # badge agrees with the expanded density in both fold states.
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

    member_count = _container_member_count(agent)
    count_text = ""
    count_style = ""
    if member_count is not None:
        count_text = f"{min(member_count[0], RAIL_COUNT_CAP):2d}"
        count_style = member_count[1]

    if is_marked:
        pip, pip_style = RAIL_MARKED_PIP, RAIL_MARKED_PIP_STYLE
    elif is_unread:
        pip, pip_style = RAIL_UNREAD_PIP, RAIL_UNREAD_STYLE
    else:
        pip, pip_style = " ", ""

    if hint_text:
        text.append(hint_text, style=RAIL_HINT_STYLE)
        if len(hint_text) == 2:
            # The hint takes the first count cell; the count keeps its
            # final digit so containers still read as counted.
            text.append(count_text[1:] if count_text else " ", style=count_style)
        else:
            text.append(count_text or "  ", style=count_style or "")
    else:
        text.append(glyph, style=glyph_style)
        text.append(count_text or "  ", style=count_style or "")
    # Guides + glyph-or-hint + count lanes always occupy ``clamped + 3``
    # cells: a 2-character hint takes the first count cell while the count
    # keeps its final digit, so the width math stays uniform.
    fill = RAIL_CONTENT_CELLS - (clamped + 3) - 1
    if fill > 0:
        text.append(" " * fill)
    if pip == " ":
        text.append(" ")
    else:
        text.append(pip, style=pip_style)
    return text


def _banner_lead(
    label: str,
    *,
    level: int,
    mode: GroupingMode,
    group_has_children: bool,
    is_patch_banner: bool,
) -> tuple[str, str]:
    """Return the ``(lead, style)`` cell for a banner row.

    ``BY_STATUS`` L0 and ``BY_MACHINE`` L1 banners lead with the rail
    bucket glyph so one visual language spans both densities; every other
    banner leads with the label's first character as written.
    """
    if level == 0 and mode is GroupingMode.BY_STATUS and label in RAIL_BUCKET_GLYPHS:
        return RAIL_BUCKET_GLYPHS[label]
    if level == 1 and mode is GroupingMode.BY_MACHINE and label in RAIL_BUCKET_GLYPHS:
        return RAIL_BUCKET_GLYPHS[label]
    lead = label[:1] if label else "?"
    if level == 0:
        return (lead, _PROJECT_BANNER_BAR_STYLE)
    if is_patch_banner or group_has_children:
        return (lead, _PATCH_BANNER_BAR_STYLE)
    return (lead, _NAME_ROOT_BANNER_LABEL_STYLE)


def _banner_rule_char(level: int) -> str:
    """Return the heavy (L0) or thin (deeper) banner rule character."""
    return _RAIL_HEAVY_RULE if level == 0 else _RAIL_THIN_RULE


def rail_urgency(
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

    Returns exactly ``RAIL_CONTENT_CELLS`` cells:

    - expanded L0: lead + heavy rule (``s━━━━━``);
    - expanded L1+: lead + thin rule in the tier color (``p─────``);
    - folded: fold mark, lead, rule, count, roll-up (``▸b━━4?``),
      with the count right-aligned to end at cell 4.

    A hint chip replaces the fold mark and lead. ``mark_state`` is
    accepted for API parity with the expanded banner (marks stay visible
    in the expanded density) and does not alter the 6-cell layout.
    """
    del mark_state
    label = banner_label(group)
    hint_text = hint[:2] if isinstance(hint, str) and hint else ""
    is_patch_banner = (
        group.level == 1
        and mode is GroupingMode.STANDARD
        and len(group.group_key) == 2
        and any(agent.cl_name for agent in agents)
    )
    lead, lead_style = _banner_lead(
        label,
        level=group.level,
        mode=mode,
        group_has_children=group.has_child_groups,
        is_patch_banner=is_patch_banner,
    )
    rule = _banner_rule_char(group.level)
    text = Text()
    if not group.is_collapsed:
        if hint_text:
            text.append(hint_text, style=RAIL_HINT_STYLE)
            text.append(rule * (RAIL_CONTENT_CELLS - len(hint_text)), style=lead_style)
        else:
            text.append(lead, style=lead_style)
            text.append(rule * (RAIL_CONTENT_CELLS - 1), style=lead_style)
        return text
    members = _top_level_members(group, agents)
    count_text = f"{min(len(members), RAIL_COUNT_CAP)}"
    urgency = rail_urgency(members, unread)
    if hint_text:
        text.append(hint_text, style=RAIL_HINT_STYLE)
        head = len(hint_text)
    else:
        text.append(RAIL_FOLD_GLYPH, style=lead_style)
        text.append(lead, style=lead_style)
        head = 2
    # The count ends at cell 4; the roll-up owns cell 5.
    count_start = RAIL_CONTENT_CELLS - 1 - len(count_text)
    text.append(rule * max(0, count_start - head), style=lead_style)
    text.append(count_text, style=lead_style)
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

    Pieces in display order mirror :func:`agent_panel_border_title`:

    1. ``[hint]`` while panel hints are up (never dropped);
    2. ``❖`` for whole-panel focus, or ``▸`` for a collapsed tribe
       (gold when selected);
    3. the configured tribe icon when its ``cell_len`` is at most 2,
       else the tribe's uppercase bold initial in its identity color;
       the merged panel shows ``All``;
    4. on collapsed tribes only, the urgency roll-up.

    When over budget, pieces drop in this order: mark, urgency,
    identity (reduced to its single-cell initial).
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
    if merged:
        identity, identity_style_full = "All", "bold #AFFFFF"
        identity_initial = "A"
    elif icon and Text(icon).cell_len <= 2:
        identity, identity_style_full = icon, identity_style
        label = agent_panel_label(key).lstrip("@")
        identity_initial = label[:1].upper() if label else "?"
    else:
        label = agent_panel_label(key).lstrip("@")
        identity_initial = label[:1].upper() if label else "?"
        identity, identity_style_full = identity_initial, identity_style
    urgency = ""
    urgency_style = ""
    if collapsed and counts is not None:
        asking = getattr(counts, "asking", 0) or 0
        failed = getattr(counts, "failed", 0) or 0
        unread_count = getattr(counts, "unread", 0) or 0
        if asking:
            urgency, urgency_style = "?", RAIL_NEEDS_YOU_STYLE
        elif failed:
            urgency, urgency_style = "✗", RAIL_FAILED_STYLE
        elif unread_count:
            urgency, urgency_style = "•", RAIL_UNREAD_STYLE

    def width(*parts: str) -> int:
        return sum(Text(part).cell_len for part in parts if part)

    # Drop order: mark, urgency, identity (reduced to its initial).
    use_mark = mark
    use_urgency = urgency
    use_identity = identity
    use_identity_style = identity_style_full
    if width(hint_text, use_mark, use_identity, use_urgency) > RAIL_TITLE_CELLS:
        use_mark = ""
    if width(hint_text, use_mark, use_identity, use_urgency) > RAIL_TITLE_CELLS:
        use_urgency = ""
    if width(hint_text, use_mark, use_identity, use_urgency) > RAIL_TITLE_CELLS:
        use_identity = identity_initial
        use_identity_style = identity_style
    title = Text()
    if hint_text:
        title.append(hint_text, style=RAIL_HINT_STYLE)
    if use_mark:
        title.append(use_mark, style=mark_style)
    if use_identity:
        title.append(use_identity, style=use_identity_style)
    if use_urgency:
        title.append(use_urgency, style=urgency_style)
    return title


def rail_overflow_subtitle(above: int, below: int) -> Text:
    """Build the rail overflow subtitle, at most 5 cells.

    ``▴N▾M`` names the rows above and below the viewport, degrading to
    ``▴▾`` when both counts cannot fit, or a single ``▴N`` / ``▾M`` arrow
    when only one side overflows. Empty when everything fits.
    """
    above_count = max(0, int(above))
    below_count = max(0, int(below))
    if not above_count and not below_count:
        return Text("")
    if above_count and below_count:
        full = f"▴{above_count}▾{below_count}"
        if Text(full).cell_len <= RAIL_TITLE_CELLS:
            return Text(full)
        return Text("▴▾")
    if above_count:
        return Text(f"▴{min(above_count, 9999)}")
    return Text(f"▾{min(below_count, 9999)}")


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
    (Text("?", style=RAIL_NEEDS_YOU_STYLE), "needs you — stopped for input or review"),
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
    (Text(RAIL_FOLD_GLYPH, style=_NAME_ROOT_BANNER_BRANCH_STYLE), "folded group"),
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
    "rail_urgency",
    "row_kind_glyph",
]
