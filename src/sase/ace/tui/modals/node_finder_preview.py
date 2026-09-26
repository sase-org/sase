"""I/O-free Node Finder preview rendering.

The modal calls :func:`render_node_finder_preview` directly from its highlight
handler.  Keep this module limited to already-loaded row and snapshot data:
the companion ``node_finder_preview_loader`` owns every artifact read.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from rich.text import Text

from sase.procs.text_bounding import tail_text_by_lines_and_chars

from ..models._agent_clan import ClanStatusCounts
from ..models._agent_clan_sections import (
    clan_relative_label,
    clan_section_member_rows,
)
from ..models.agent import AgentType
from ..models.fold_state import FoldLevel
from ..models.node_finder import (
    NodeFinderRole,
    NodeFinderRow,
    NodeFinderSnapshot,
    node_finder_action_text,
    node_finder_reason_text,
)
from ..models.tribe_display import tribe_identity_style
from ..widgets.prompt_panel._agent_display_clan_identity import (
    build_clan_compact_lines,
)
from ..widgets.prompt_panel._identity_header_compact import (
    build_agent_compact_lines,
    build_workflow_compact_lines,
)

if TYPE_CHECKING:
    from ..models.agent import Agent


_RULE_WIDTH = 34
_SOFT_TEXT_STYLE = "#87D7FF"
_STATUS_STYLE = "bold #D7D7FF"


def render_node_finder_preview(
    row: NodeFinderRow,
    snapshot: NodeFinderSnapshot,
    query: str,
) -> Text:
    """Render the synchronous, entirely in-memory preview for *row*.

    This deliberately does not look up artifacts, stat paths, or hydrate a
    projected row.  The Tier 1 loader fills the fixed prompt/reply slots after
    the modal has painted this result.
    """

    if row.role is not NodeFinderRole.NODE or row.agent is None:
        return Text("Select a node to inspect it.", style="dim")

    agent = row.agent
    text = Text()
    _append_kind_chip(text, row)
    # Tier 0 shows member statuses, labels, and activity only. The full
    # clan aggregation (digests, errors, variables, bead/plan indexes)
    # serves the Agents panel, not this preview: resolving the same member
    # rows directly keeps first paint off that per-member digest work.
    clan_rows = clan_section_member_rows(agent) if agent.is_clan_container else None
    _append_identity(text, agent, clan_rows=clan_rows)
    _append_breadcrumb(text, row, snapshot)
    _append_navigation_status(text, row, query)
    _append_kind_section(text, row, snapshot, clan_rows=clan_rows)
    if _has_tier1_source(row):
        _append_tier1_skeleton(text)
    return text


def _append_kind_chip(text: Text, row: NodeFinderRow) -> None:
    text.append((row.kind_label or "NODE").upper(), style=f"bold {row.kind_accent}")
    text.append("  ", style="")
    text.append(row.name, style=f"bold {row.kind_accent}")
    text.append("\n")


def _append_identity(
    text: Text,
    agent: Agent,
    clan_rows: tuple[Agent, ...] | None = None,
) -> None:
    if agent.is_clan_container:
        if clan_rows is None:
            clan_rows = clan_section_member_rows(agent)
        counts = Counter(member.display_status for member in clan_rows)
        text.append_text(
            build_clan_compact_lines(
                agent=agent,
                counts=_clan_counts(counts),
                agent_count=len(clan_rows),
                agent_session_count=sum(
                    1 for member in clan_rows if member.agent_session
                ),
                # The preview describes current data, not an interactive fold.
                fold_level=_collapsed_fold_level(),
            )
        )
    elif agent.agent_type is AgentType.WORKFLOW and not agent.is_workflow_child:
        text.append_text(build_workflow_compact_lines(agent=agent))
    else:
        text.append_text(build_agent_compact_lines(agent=agent))
    text.append("\n")


def _clan_counts(counts: Counter[str]) -> ClanStatusCounts:
    """Map the in-memory display labels to the clan compact-line counts."""

    normalized = Counter({status.title(): count for status, count in counts.items()})
    return ClanStatusCounts(
        awaiting=normalized["Stopped"],
        running=normalized["Running"],
        queued=normalized["Queued"],
        waiting=normalized["Waiting"],
        failed=normalized["Failed"],
        unread=normalized["Unread"],
        done=normalized["Done"],
    )


def _collapsed_fold_level() -> FoldLevel:
    """Use the neutral fold position for a non-interactive preview."""

    return FoldLevel.COLLAPSED


def _snapshot_position(snapshot: NodeFinderSnapshot, row: NodeFinderRow) -> int | None:
    """Return *row*'s position in the snapshot rows by identity.

    Filtered views carry display-coordinate parents (remapped to the
    visible list), so ancestor and child lookups must resolve through the
    snapshot's own coordinates. Identities are unique per snapshot and
    survive view copies, which value equality does not.
    """
    identity = row.identity
    if row.role is not NodeFinderRole.NODE or identity is None:
        return None
    for pos, candidate in enumerate(snapshot.rows):
        if candidate.identity == identity and candidate.role is NodeFinderRole.NODE:
            return pos
    return None


def _append_breadcrumb(
    text: Text,
    row: NodeFinderRow,
    snapshot: NodeFinderSnapshot,
) -> None:
    path: list[NodeFinderRow] = []
    start = _snapshot_position(snapshot, row)
    if start is not None:
        current = snapshot.rows[start]
        seen: set[int] = {start}
        while current.parent_row is not None and current.parent_row not in seen:
            parent_index = current.parent_row
            seen.add(parent_index)
            if not 0 <= parent_index < len(snapshot.rows):
                break
            current = snapshot.rows[parent_index]
            if current.role is NodeFinderRole.NODE:
                path.append(current)
        path.reverse()

    text.append(
        "@" + (row.panel_key or "default"), style=tribe_identity_style(row.panel_key)
    )
    for ancestor in path:
        text.append(" ▸ ", style="dim")
        text.append(ancestor.name, style="")
    text.append(" ▸ ", style="dim")
    text.append(row.name, style="bold")
    text.append("\n")


def _append_navigation_status(text: Text, row: NodeFinderRow, query: str) -> None:
    why = node_finder_reason_text(row, query)
    if why:
        text.append(why, style=_STATUS_STYLE)
    else:
        text.append("Visible in Agents", style="dim")
    text.append("\n")
    text.append(node_finder_action_text(row, query), style=_STATUS_STYLE)
    text.append("\n")


def _append_kind_section(
    text: Text,
    row: NodeFinderRow,
    snapshot: NodeFinderSnapshot,
    clan_rows: tuple[Agent, ...] | None = None,
) -> None:
    agent = row.agent
    assert agent is not None
    if agent.is_agent_session_container_row:
        _append_session_shells(text, row, snapshot)
    elif agent.is_clan_container:
        if clan_rows is None:
            clan_rows = clan_section_member_rows(agent)
        _append_clan_members(text, agent, clan_rows=clan_rows)
    elif agent.is_monitor or agent.is_proc_shell:
        _append_proc_details(text, agent)
    elif agent.is_gate:
        _append_gate_details(text, agent)
    elif agent.agent_type is AgentType.WORKFLOW and not agent.is_workflow_child:
        _append_workflow_steps(text, row, snapshot)


def _append_section_header(
    text: Text, label: str, accent: str = _SOFT_TEXT_STYLE
) -> None:
    text.append(label, style=f"bold {accent}")
    text.append(" " + "─" * max(3, _RULE_WIDTH - len(label)), style=f"dim {accent}")
    text.append("\n")


def _append_session_shells(
    text: Text,
    row: NodeFinderRow,
    snapshot: NodeFinderSnapshot,
) -> None:
    _append_section_header(text, "SHELLS", row.kind_accent)
    children = _child_rows(snapshot, row)
    if not children:
        text.append("No loaded shells.", style="dim")
        text.append("\n")
        return
    for child in children:
        if child.agent is None:
            continue
        shell = child.agent
        text.append("• ", style="dim")
        text.append(child.name, style=f"bold {child.kind_accent}")
        text.append(f" · {child.kind_label.lower()} · ", style="dim")
        text.append(shell.display_status, style=_STATUS_STYLE)
        runtime = shell.duration_display
        if runtime and runtime != "?":
            text.append(f" · {runtime}", style="dim")
        text.append("\n")


def _append_clan_members(
    text: Text,
    agent: Agent,
    clan_rows: tuple[Agent, ...] | None = None,
) -> None:
    if clan_rows is None:
        clan_rows = clan_section_member_rows(agent)
    clan_name = agent.agent_clan or agent.display_name
    _append_section_header(text, "MEMBERS", "#D75FFF")
    counts = Counter(member.display_status for member in clan_rows)
    if counts:
        text.append(
            " · ".join(
                f"{count} {status.lower()}" for status, count in sorted(counts.items())
            ),
            style="dim",
        )
        text.append("\n")
    for member in clan_rows[:12]:
        text.append("• ", style="dim")
        text.append(clan_relative_label(member, clan_name), style="bold")
        text.append(f" · {member.display_status}", style=_STATUS_STYLE)
        if member.activity:
            text.append(f" · {member.activity}", style="dim")
        text.append("\n")
    remaining = len(clan_rows) - 12
    if remaining > 0:
        text.append(f"… {remaining} more members", style="dim")
        text.append("\n")


def _append_proc_details(text: Text, agent: Agent) -> None:
    _append_section_header(text, "PROCESS", "#FFAF5F")
    label = agent.monitor_label or agent.proc_label or agent.display_name
    command = agent.monitor_command or agent.proc_safe_preview
    text.append(label, style="bold")
    text.append(
        f" · {agent.monitor_state or agent.proc_status or agent.display_status}",
        style=_STATUS_STYLE,
    )
    exit_code = agent.monitor_exit_code
    if exit_code is not None:
        text.append(
            f" · exit {exit_code}", style="dim" if exit_code == 0 else "bold red"
        )
    text.append("\n")
    if command:
        text.append(command, style=_SOFT_TEXT_STYLE)
        text.append("\n")
    if agent.proc_log_tail:
        _append_section_header(text, "OUTPUT · tail", "#FFAF5F")
        tail = tail_text_by_lines_and_chars(agent.proc_log_tail, 12, 4_096)
        if tail.omitted_lines:
            text.append(f"… {tail.omitted_lines} earlier lines\n", style="dim")
        text.append(tail.text.rstrip())
        text.append("\n")


def _append_gate_details(text: Text, agent: Agent) -> None:
    _append_section_header(text, "GATE", "#AF87FF")
    text.append(
        agent.gate_label or agent.gate_kind or agent.gate_id or "gate", style="bold"
    )
    text.append(f" · {agent.gate_state or agent.display_status}", style=_STATUS_STYLE)
    text.append("\n")


def _append_workflow_steps(
    text: Text,
    row: NodeFinderRow,
    snapshot: NodeFinderSnapshot,
) -> None:
    children = _child_rows(snapshot, row)
    _append_section_header(text, "STEPS", "#AF87D7")
    counts = Counter(
        child.agent.display_status for child in children if child.agent is not None
    )
    if not counts:
        text.append("No loaded steps.", style="dim")
        text.append("\n")
        return
    text.append(
        " · ".join(
            f"{count} {status.lower()}" for status, count in sorted(counts.items())
        ),
        style="dim",
    )
    text.append("\n")


def _child_rows(
    snapshot: NodeFinderSnapshot, row: NodeFinderRow
) -> tuple[NodeFinderRow, ...]:
    parent = _snapshot_position(snapshot, row)
    if parent is None:
        return ()
    return tuple(
        candidate
        for candidate in snapshot.rows
        if candidate.parent_row == parent and candidate.role is NodeFinderRole.NODE
    )


def _has_tier1_source(row: NodeFinderRow) -> bool:
    """Avoid importing the worker module on every preview paint."""

    agent = row.agent
    if agent is None:
        return False
    if (
        agent.is_clan_container
        or agent.is_monitor
        or agent.is_gate
        or agent.is_proc_shell
    ):
        return False
    if agent.is_agent_session_container_row:
        return any(_is_agent_shell(member) for member in agent.followup_agents)
    return _is_agent_shell(agent)


def _is_agent_shell(agent: Agent) -> bool:
    return agent.is_agent_entry


def _append_tier1_skeleton(text: Text) -> None:
    _append_section_header(text, "PROMPT")
    text.append("⋯ loading\n⋯ loading\n", style="dim")
    _append_section_header(text, "REPLY · tail")
    text.append("⋯ loading\n⋯ loading", style="dim")


__all__ = ["render_node_finder_preview"]
