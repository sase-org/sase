"""Row, chrome, and layout helpers for the Node Finder modal."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from rich.text import Text

from sase.core.fuzzy_facade import fuzzy_match
from sase.core.time import local_now
from sase.gate_shell.state import GATE_GLYPH
from sase.monitor_state import MONITOR_GLYPH

from ..models.agent import Agent, AgentType, format_compact_duration
from ..models.agent_panels import agent_panel_label
from ..models.agent_status import STOPPED_COLOR, STOPPED_STATUS
from ..models.node_finder import (
    NodeFinderRole,
    NodeFinderRow,
    NodeFinderSnapshot,
    NodeFinderView,
    node_finder_glyph,
)
from ..models.tribe_display import tribe_identity_style
from ..widgets._agent_list_styling import TREE_DEPTH_COLORS
from ..widgets._completion_match_highlight import append_highlighted
from .pane_entry_jump import apply_jump_hint_prefix

_GLYPH_STYLE: dict[str, str] = {
    "◆": "bold #FFFF00",
    "⊘": "#FF5F87",
    "◌": "dim",
    "▭": "#AF87FF",
    "≡": "#87D7FF",
    "▸": "#FFD75F",
}
_STATUS_STYLE: dict[str, str] = {
    "RUNNING": "#00D7AF",
    "DONE": "dim #87D7FF",
    "FAILED": "#FF5F5F",
    "KILLED": "#FF8C00",
    STOPPED_STATUS: STOPPED_COLOR,
    "QUEUED": "#5F87FF",
    "WAITING": "#AF87FF",
    "WORKFLOW": "#AF87FF",
    "COMPLETED": "dim #87D7FF",
}
_HINT_ACTIVE = "bold #FFFF00"
_HINT_DIM = "dim #FFFF00"
_HINT_REMAINING = "bold underline #FFFF00"
_PROC_GLYPH = "⚙"
_WORKFLOW_GLYPH = "≡"
_FLASH_STYLE = "bold #FF8700"
_LAYOUT_WIDE = ""
_LAYOUT_MEDIUM = "-medium"
_LAYOUT_NARROW = "-narrow"

_HINTS_LEGEND = '0-Z jump · tab / search · ^n ^p move · ⏎ jump · "" back · esc close'
_SEARCH_LEGEND = (
    "type to filter · tab hints · ⏎ jump · ^n ^p move · ^u clear · esc hints"
)
EMPTY_PREVIEW = "esc / tab back to hints · ^u clear"


def layout_class_for_width(width: int) -> str:
    """Return the responsive container class for *width* columns."""
    if width >= 140:
        return _LAYOUT_WIDE
    if width >= 100:
        return _LAYOUT_MEDIUM
    return _LAYOUT_NARROW


def show_status_column(layout_class: str) -> bool:
    """Return whether the list should render the right-aligned status column."""
    return layout_class == _LAYOUT_WIDE


def hint_column_width(view: NodeFinderView) -> int:
    """Return the fixed hint-gutter width for the live hint set."""
    if not view.identity_to_hint:
        return 1
    return max(len(hint) for hint in view.identity_to_hint.values())


def render_mode_pill(search_mode: bool) -> Text:
    """Render the HINTS / SEARCH mode pill."""
    if search_mode:
        return Text(" SEARCH ", style="bold black on #87D7FF")
    return Text(" HINTS ", style="bold black on #FFFF00")


def render_scope_strip(
    snapshot: NodeFinderSnapshot,
    view: NodeFinderView,
    *,
    search_mode: bool,
) -> Text:
    """Render the dim completeness strip beside the mode pill."""
    text = Text(style="dim")
    if search_mode:
        matched = sum(
            1
            for index, row in enumerate(view.rows)
            if row.jumpable and index not in view.context
        )
        text.append(f"{matched} of {snapshot.node_count}")
        if view.relaxed:
            text.append(" · relaxed")
        return text
    parts = [f"{snapshot.node_count} nodes", f"{snapshot.hidden_count} hidden"]
    if snapshot.query:
        parts.append(f"{snapshot.query_hidden_count} ⊘")
    if snapshot.hidden_by_i_count:
        parts.append(f"{snapshot.hidden_by_i_count} ◌")
    if snapshot.query_incomplete:
        parts.append("history partial")
    if snapshot.hint_overflow:
        parts.append("type to narrow")
    text.append(" · ".join(parts))
    return text


def render_legend(*, search_mode: bool) -> Text:
    """Render the mode-specific footer legend."""
    return Text(_SEARCH_LEGEND if search_mode else _HINTS_LEGEND, style="dim")


def render_flash_slot(*, pending: str = "", flash: str = "") -> Text:
    """Render the right-hand pending / invalid-key slot."""
    if flash:
        return Text(flash, style=_FLASH_STYLE)
    if pending:
        return Text(f"{pending}…", style=_HINT_ACTIVE)
    return Text("")


def empty_match_label(query: str) -> Text:
    """Return the disabled list row used when a finder query matches nothing."""
    return Text(f"No nodes match ‹{query}›", style="dim")


def last_child_indices(rows: Sequence[NodeFinderRow]) -> set[int]:
    """Return the displayed indices that close their sibling group.

    Computing this once per list rebuild keeps per-row tree guides O(depth)
    instead of O(rows); pass the result to :func:`render_row_prompt`.
    """
    children: dict[int | None, list[int]] = {}
    for index, row in enumerate(rows):
        children.setdefault(row.parent_row, []).append(index)
    return {sibs[-1] for sibs in children.values() if sibs}


def render_row_prompt(
    view: NodeFinderView,
    index: int,
    *,
    search_mode: bool,
    pending: str,
    show_status: bool,
    hint_width: int,
    last_child: set[int] | None = None,
) -> Text:
    """Compose one OptionList prompt: hint gutter plus cached body."""
    row = view.rows[index]
    body = _render_row_body(view, index, show_status=show_status, last_child=last_child)
    hint = view.identity_to_hint.get(row.identity) if row.identity is not None else None
    gutter = _render_hint_gutter(
        hint,
        width=hint_width,
        search_mode=search_mode,
        pending=pending,
    )
    prompt = Text(no_wrap=True, overflow="ellipsis")
    prompt.append_text(gutter)
    prompt.append_text(body)
    return prompt


def _render_hint_gutter(
    hint: str | None,
    *,
    width: int,
    search_mode: bool,
    pending: str,
) -> Text:
    """Render a fixed-width ``[h]`` gutter, or blank padding when there is no hint."""
    if not hint:
        return Text(" " * (width + 3))
    if search_mode:
        return _padded_hint(hint, width, style=_HINT_DIM)
    if pending:
        if not hint.startswith(pending):
            return _padded_hint(hint, width, style="dim")
        return _pending_hint(hint, pending, width)
    decorated = apply_jump_hint_prefix(Text(""), hint)
    pad = width - len(hint)
    if pad > 0:
        decorated.append(" " * pad)
    return decorated


def _render_row_body(
    view: NodeFinderView,
    index: int,
    *,
    show_status: bool,
    last_child: set[int] | None = None,
) -> Text:
    """Render everything after the hint gutter for one displayed row."""
    row = view.rows[index]
    if row.role is NodeFinderRole.PANEL:
        return _render_panel_header(row)
    if row.role is NodeFinderRole.GROUP:
        return _render_group_header(row)
    return _render_node_body(
        view, index, show_status=show_status, last_child=last_child
    )


def _render_panel_header(row: NodeFinderRow) -> Text:
    label = agent_panel_label(row.panel_key)
    text = Text(no_wrap=True, overflow="ellipsis")
    glyph = "▭ " if row.hidden_count and row.hidden_count >= row.jumpable_count else ""
    text.append(
        f"{label} {glyph}", style=tribe_identity_style(row.panel_key, bold=True)
    )
    text.append("─" * 4, style="dim")
    counts = f" {row.jumpable_count}"
    if row.hidden_count:
        counts += f" · {row.hidden_count} hidden"
    text.append(counts, style="dim")
    return text


def _render_group_header(row: NodeFinderRow) -> Text:
    text = Text(no_wrap=True, overflow="ellipsis")
    text.append(row.group_label or "group", style="dim")
    return text


def _render_node_body(
    view: NodeFinderView,
    index: int,
    *,
    show_status: bool,
    last_child: set[int] | None = None,
) -> Text:
    row = view.rows[index]
    hidden = bool(row.reasons) and not row.is_here
    color = row.kind_accent or "#87AFFF"
    name_style = f"dim {color}" if hidden else color
    text = Text(no_wrap=True, overflow="ellipsis")
    glyph = node_finder_glyph(row)
    if glyph:
        text.append(f"{glyph} ", style=_GLYPH_STYLE.get(glyph, color))
    else:
        text.append("  ")
    text.append(_type_glyph(row.agent), style=name_style)
    text.append(_tree_prefix(view.rows, index, last_child))
    runs = _name_match_runs(row.name, view.tokens)
    append_highlighted(
        text,
        row.name,
        runs,
        base_style=name_style,
        match_style=f"bold underline {color}",
    )
    if show_status:
        status, age = _status_age(row.agent)
        if status:
            text.append("  ")
            text.append(status, style=_STATUS_STYLE.get(status, "dim"))
        if age:
            text.append(f" {age}", style="dim")
    return text


def _type_glyph(agent: Agent | None) -> str:
    if agent is None:
        return ""
    if agent.is_monitor:
        return f"{MONITOR_GLYPH} "
    if agent.is_gate:
        return f"{GATE_GLYPH} "
    if agent.is_proc_shell:
        return f"{_PROC_GLYPH} "
    if agent.agent_type is AgentType.WORKFLOW and not agent.is_workflow_step_child:
        return f"{_WORKFLOW_GLYPH} "
    return ""


def _tree_prefix(
    rows: Sequence[NodeFinderRow],
    index: int,
    last_child: set[int] | None = None,
) -> Text:
    row = rows[index]
    if row.role is not NodeFinderRole.NODE:
        return Text("")
    if last_child is None:
        last_child = last_child_indices(rows)
    ancestors: list[int] = []
    current = row.parent_row
    seen: set[int] = set()
    while current is not None and current not in seen and 0 <= current < len(rows):
        seen.add(current)
        if rows[current].role is not NodeFinderRole.PANEL:
            ancestors.append(current)
        current = rows[current].parent_row
    ancestors.reverse()
    text = Text()
    if not ancestors:
        return text
    for ancestor in ancestors[:-1]:
        color = _depth_color(rows[ancestor].depth)
        if ancestor in last_child:
            text.append("   ", style=color)
        else:
            text.append("│  ", style=color)
    color = _depth_color(row.depth)
    text.append("└ " if index in last_child else "├ ", style=color)
    return text


def _depth_color(depth: int) -> str:
    if depth <= 0:
        return TREE_DEPTH_COLORS[0]
    return TREE_DEPTH_COLORS[(depth - 1) % len(TREE_DEPTH_COLORS)]


def _name_match_runs(name: str, tokens: tuple[str, ...]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    for token in tokens:
        match = fuzzy_match(token, name)
        if match is not None:
            runs.extend(match.runs)
    return runs


def _status_age(agent: Agent | None) -> tuple[str, str]:
    if agent is None:
        return "", ""
    status = agent.status or ""
    age = ""
    started = agent.start_time
    if isinstance(started, datetime):
        age = format_compact_duration(max(0.0, (local_now() - started).total_seconds()))
    return status, age


def _padded_hint(hint: str, width: int, *, style: str) -> Text:
    text = Text()
    text.append("[", style="dim")
    text.append(f"{hint:<{width}}", style=style)
    text.append("] ", style="dim")
    return text


def _pending_hint(hint: str, pending: str, width: int) -> Text:
    text = Text()
    text.append("[", style="dim")
    text.append(pending, style="dim")
    text.append(hint[len(pending) :], style=_HINT_REMAINING)
    text.append(" " * (width - len(hint)), style="")
    text.append("] ", style="dim")
    return text


__all__ = [
    "EMPTY_PREVIEW",
    "empty_match_label",
    "hint_column_width",
    "last_child_indices",
    "layout_class_for_width",
    "render_flash_slot",
    "render_legend",
    "render_mode_pill",
    "render_row_prompt",
    "render_scope_strip",
    "show_status_column",
]
