"""Pure Node Finder row model, filtering, hints, and text helpers.

Free of Textual imports by design; UI-adjacent helpers behind Textual
import chains are imported lazily inside the functions that need them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sase.core.fuzzy_facade import fuzzy_match
from sase.project_display_names import humanize_cl_name

from ._agent_tree import agent_tree_title
from .agent_panels import agent_panel_label

if TYPE_CHECKING:
    from .agent import Agent, AgentType

    AgentIdentity = tuple[AgentType, str, str | None]


class NodeFinderReason(StrEnum):
    """Why one Node Finder row is hidden from the Agents tab."""

    FOLDED = "folded"
    BANNER = "banner"
    PANEL = "panel"
    QUERY = "query"
    NON_RUN = "non_run"


#: Most-global hider wins the single row glyph:
#: ``QUERY > NON_RUN > PANEL > BANNER > FOLDED``.
REASON_PRECEDENCE: tuple[NodeFinderReason, ...] = (
    NodeFinderReason.QUERY,
    NodeFinderReason.NON_RUN,
    NodeFinderReason.PANEL,
    NodeFinderReason.BANNER,
    NodeFinderReason.FOLDED,
)

_REASON_GLYPH: dict[NodeFinderReason, str] = {
    NodeFinderReason.QUERY: "⊘",
    NodeFinderReason.NON_RUN: "◌",
    NodeFinderReason.PANEL: "▭",
    NodeFinderReason.BANNER: "≡",
    NodeFinderReason.FOLDED: "▸",
}

#: Rows past this many jumpable rows carry no hint; the view flags overflow.
NODE_FINDER_HINT_CAPACITY = 62 * 62


class NodeFinderRole(StrEnum):
    """Structural role of one Node Finder row."""

    PANEL = "panel"
    GROUP = "group"
    NODE = "node"


@dataclass(frozen=True, slots=True)
class NodeFinderRow:
    """One row in the Node Finder snapshot, in tree order."""

    role: NodeFinderRole = NodeFinderRole.NODE
    identity: AgentIdentity | None = None
    agent: Agent | None = None
    name: str = ""
    title: str = ""
    kind_label: str = ""
    kind_accent: str = ""
    depth: int = 0
    panel_key: str | None = None
    parent_row: int | None = None
    jumpable: bool = False
    reasons: frozenset[NodeFinderReason] = frozenset()
    unmet_fold_count: int = 0
    nearest_collapsed: str = ""
    group_label: str = ""
    is_here: bool = False
    jumpable_count: int = 0
    hidden_count: int = 0


@dataclass(frozen=True, slots=True)
class NodeFinderSnapshot:
    """Fixed row set captured when the finder opens."""

    rows: tuple[NodeFinderRow, ...] = ()
    here_row: int | None = None
    node_count: int = 0
    hidden_count: int = 0
    query_hidden_count: int = 0
    query: str = ""
    query_incomplete: bool = False
    hidden_by_i_count: int = 0
    hint_overflow: bool = False
    focused_panel_key: str | None = None


@dataclass(frozen=True, slots=True)
class NodeFinderView:
    """One filtered projection of a snapshot, in tree order."""

    rows: tuple[NodeFinderRow, ...] = ()
    context: frozenset[int] = frozenset()
    best_index: int | None = None
    relaxed: bool = False
    hint_to_identity: dict[str, AgentIdentity] = field(default_factory=dict)
    identity_to_hint: dict[AgentIdentity, str] = field(default_factory=dict)
    overflow: bool = False
    any_match: frozenset[AgentIdentity] = frozenset()
    tokens: tuple[str, ...] = ()
    query: str = ""


def node_finder_name(agent: Agent) -> str:
    """Return the name the Agents row shows for *agent*."""
    if agent.is_clan_container:
        return (
            agent.presented_agent_name
            or agent.agent_clan
            or agent.display_name
            or humanize_cl_name(agent.cl_name)
        )
    if agent.is_proc_shell:
        return (
            agent.proc_label
            or agent.presented_agent_name
            or agent.agent_name
            or agent.display_name
            or humanize_cl_name(agent.cl_name)
        )
    return (
        agent.presented_agent_name
        or agent.agent_name
        or agent.display_name
        or humanize_cl_name(agent.cl_name)
    )


def node_finder_title(agent: Agent) -> str | None:
    """Return the displayed title when it differs from the name."""
    title = agent_tree_title(agent)
    if not title or title == node_finder_name(agent):
        return None
    return title


def node_finder_kind(agent: Agent) -> tuple[str, str]:
    """Return the kind label and accent color for *agent*."""
    if agent.is_clan_container:
        return ("CLAN", "#D75FFF")
    from sase.ace.tui.widgets.prompt_panel._identity_header import (
        identity_kind_for_agent,
    )

    return identity_kind_for_agent(agent)


def node_finder_jumpable(agent: Agent) -> bool:
    """Return whether *agent* can ever be a Node Finder jump target."""
    if agent.is_pre_prompt_step:
        return False
    if agent.is_workflow_step_child and agent.step_type != "agent":
        return False
    return True


def node_finder_glyph(row: NodeFinderRow) -> str:
    """Return the single why-hidden glyph for *row* (``""`` when visible)."""
    if row.is_here:
        return "◆"
    for reason in REASON_PRECEDENCE:
        if reason in row.reasons:
            return _REASON_GLYPH[reason]
    return ""


def _tokenize(query: str) -> tuple[str, ...]:
    return tuple(token for token in query.split() if token)


@dataclass(frozen=True, slots=True)
class _TokenMatch:
    tier: int
    score: int
    title_used: bool


def _match_token(token: str, name: str, title: str) -> _TokenMatch | None:
    """Match one token against the better of the name/title haystacks."""
    name_match = fuzzy_match(token, name) if name else None
    title_match = fuzzy_match(token, title) if title else None
    if name_match is None:
        if title_match is None:
            return None
        return _TokenMatch(title_match.tier, title_match.score, True)
    if title_match is None:
        return _TokenMatch(name_match.tier, name_match.score, False)
    if (title_match.tier, -title_match.score) < (name_match.tier, -name_match.score):
        return _TokenMatch(title_match.tier, title_match.score, True)
    return _TokenMatch(name_match.tier, name_match.score, False)


@dataclass(frozen=True, slots=True)
class _RowScore:
    worst_tier: int
    title_used: bool
    total_score: int


def _score_row(
    row: NodeFinderRow, tokens: tuple[str, ...]
) -> tuple[_RowScore | None, _RowScore | None]:
    """Return ``(contiguous_score, any_score)``; ``None`` fails that pass."""
    worst_contiguous = 0
    worst_any = 0
    title_used = False
    total = 0
    for position, token in enumerate(tokens):
        match = _match_token(token, row.name, row.title)
        if match is None:
            return None, None
        worst_any = max(worst_any, match.tier)
        title_used = title_used or match.title_used
        total += match.score
        if match.tier > 2:
            # Relaxed-only token: the contiguous pass fails here, but the
            # any-match pass continues with later tokens.
            for rest in tokens[position + 1 :]:
                rest_match = _match_token(rest, row.name, row.title)
                if rest_match is None:
                    return None, None
                worst_any = max(worst_any, rest_match.tier)
                title_used = title_used or rest_match.title_used
                total += rest_match.score
            return None, _RowScore(worst_any, title_used, total)
        worst_contiguous = max(worst_contiguous, match.tier)
    score = _RowScore(worst_contiguous, title_used, total)
    return score, _RowScore(worst_any, title_used, total)


def _is_refinement(previous: tuple[str, ...], tokens: tuple[str, ...]) -> bool:
    """Return whether *tokens* narrows *previous* monotonically."""
    if not previous:
        return bool(tokens)
    if len(tokens) == len(previous):
        return (
            tokens[:-1] == previous[:-1]
            and tokens[-1] != previous[-1]
            and tokens[-1].startswith(previous[-1])
        )
    return len(tokens) == len(previous) + 1 and tokens[: len(previous)] == previous


def filter_node_finder(
    snapshot: NodeFinderSnapshot,
    query: str,
    *,
    previous: NodeFinderView | None = None,
) -> NodeFinderView:
    """Token-AND fuzzy filter with a contiguous pass and a relaxed fallback."""
    from sase.ace.tui.actions.navigation.jump_hints import build_jump_hint_maps

    tokens = _tokenize(query)
    rows = snapshot.rows
    node_positions = [
        i for i, row in enumerate(rows) if row.role is NodeFinderRole.NODE
    ]

    candidates = node_positions
    if (
        previous is not None
        and _is_refinement(previous.tokens, tokens)
        and previous.any_match
    ):
        narrowed = {i for i in node_positions if rows[i].identity in previous.any_match}
        # Both passes are monotone under refinement, so this restriction is exact.
        if narrowed:
            candidates = sorted(narrowed)

    contiguous: dict[int, _RowScore] = {}
    any_match: dict[int, _RowScore] = {}
    for pos in candidates:
        row = rows[pos]
        if not row.jumpable:
            continue
        tight, loose = _score_row(row, tokens)
        if loose is not None:
            any_match[pos] = loose
        if tight is not None:
            contiguous[pos] = tight

    if not tokens:
        matched = {
            pos: _RowScore(0, False, 0) for pos in candidates if rows[pos].jumpable
        }
        relaxed = False
    elif contiguous:
        matched = contiguous
        relaxed = False
    else:
        matched = any_match
        relaxed = True

    if tokens:
        any_identities = frozenset(
            identity
            for pos in any_match
            if (identity := rows[pos].identity) is not None
        )
    else:
        any_identities = frozenset(
            identity
            for pos in candidates
            if rows[pos].jumpable and (identity := rows[pos].identity) is not None
        )

    # Best match minimizes (worst tier, name-before-title, -score, order).
    best_pos: int | None = None
    best_key: tuple[int, bool, int, int] | None = None
    for pos, score in matched.items():
        key = (score.worst_tier, score.title_used, -score.total_score, pos)
        if best_key is None or key < best_key:
            best_key = key
            best_pos = pos

    if not tokens:
        if snapshot.here_row is not None and snapshot.here_row in matched:
            best_pos = snapshot.here_row
        elif matched:
            best_pos = min(matched)

    if not matched:
        return NodeFinderView(
            rows=(),
            best_index=None,
            relaxed=relaxed and bool(tokens),
            any_match=frozenset(),
            tokens=tokens,
            query=query,
        )

    keep: set[int] = set(matched)
    for pos in matched:
        current = rows[pos].parent_row
        seen = {pos}
        while current is not None and current not in seen:
            seen.add(current)
            keep.add(current)
            current = rows[current].parent_row if 0 <= current < len(rows) else None

    # Drop headers with no kept node rows beneath them. One ancestor walk
    # per kept node replaces a per-header scan over all kept nodes.
    kept_nodes = {pos for pos in keep if rows[pos].role is NodeFinderRole.NODE}
    headers_with_nodes = _headers_with_kept_descendants(rows, kept_nodes)
    excluded_headers = {
        pos
        for pos in keep
        if rows[pos].role is not NodeFinderRole.NODE and pos not in headers_with_nodes
    }
    keep -= excluded_headers

    ordered = sorted(keep)
    new_index = {old: new for new, old in enumerate(ordered)}
    display_rows: list[NodeFinderRow] = []
    for old in ordered:
        row = rows[old]
        parent = row.parent_row
        while parent is not None and parent not in new_index:
            parent = rows[parent].parent_row if 0 <= parent < len(rows) else None
        if row.role is NodeFinderRole.NODE and old not in matched:
            display_rows.append(replace(row, parent_row=parent, jumpable=False))
        else:
            display_rows.append(replace(row, parent_row=parent))
    matched_display = {new_index[pos] for pos in matched if pos in new_index}
    context = {new for new in range(len(display_rows)) if new not in matched_display}

    hint_identities = [
        row.identity
        for new, row in enumerate(display_rows)
        if row.jumpable and new not in context and row.identity is not None
    ]
    overflow = len(hint_identities) > NODE_FINDER_HINT_CAPACITY
    hinted = hint_identities[:NODE_FINDER_HINT_CAPACITY]
    hint_to_identity, identity_to_hint = build_jump_hint_maps(hinted, prefix_free=True)

    best_index = (
        new_index[best_pos] if best_pos is not None and best_pos in new_index else None
    )
    return NodeFinderView(
        rows=tuple(display_rows),
        context=frozenset(context),
        best_index=best_index,
        relaxed=relaxed,
        hint_to_identity=dict(hint_to_identity),
        identity_to_hint=dict(identity_to_hint),
        overflow=overflow,
        any_match=any_identities,
        tokens=tokens,
        query=query,
    )


def _headers_with_kept_descendants(
    rows: tuple[NodeFinderRow, ...] | list[NodeFinderRow],
    kept_nodes: set[int],
) -> set[int]:
    """Return header positions with at least one kept node beneath them."""
    headers: set[int] = set()
    for node_pos in kept_nodes:
        current = rows[node_pos].parent_row
        seen: set[int] = set()
        while current is not None and current not in seen:
            if not 0 <= current < len(rows):
                break
            seen.add(current)
            headers.add(current)
            current = rows[current].parent_row
    return headers


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


__all__ = [
    "NODE_FINDER_HINT_CAPACITY",
    "NodeFinderReason",
    "NodeFinderRole",
    "NodeFinderRow",
    "NodeFinderSnapshot",
    "NodeFinderView",
    "REASON_PRECEDENCE",
    "filter_node_finder",
    "next_jumpable_index",
    "node_finder_action_text",
    "node_finder_glyph",
    "node_finder_jumpable",
    "node_finder_kind",
    "node_finder_name",
    "node_finder_reason_text",
    "node_finder_title",
]
