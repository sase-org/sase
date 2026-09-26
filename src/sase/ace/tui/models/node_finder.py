"""Pure Node Finder row model, filtering, hints, and text helpers.

Free of Textual imports by design; UI-adjacent helpers behind Textual
import chains are imported lazily inside the functions that need them.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sase.core.fuzzy_facade import fuzzy_tier_score
from sase.project_display_names import humanize_cl_name

from ._agent_tree import agent_tree_title
from .agent import Agent, AgentType
from .agent_panels import agent_panel_label
from .agent_proc_shells import proc_shell_command_title

if TYPE_CHECKING:
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


#: Cached :func:`identity_kind_for_agent` without importing the Textual
#: widget chain at module load (this model stays Textual-free by design).
_IDENTITY_KIND_FN: Any = None

#: Cached kind style constants, bound lazily for the same reason. The
#: batch descriptor below reuses these instead of duplicating values.
_KIND_STYLES: dict[str, Any] | None = None


def _kind_styles() -> dict[str, Any]:
    """Return the shared kind label/accent constants, binding them once."""
    global _KIND_STYLES  # noqa: PLW0603
    styles = _KIND_STYLES
    if styles is None:
        from sase.ace.tui.widgets.prompt_panel._agent_display_agent_session import (
            SESSION_IDENTITY_COLOR,
        )
        from sase.ace.tui.widgets.prompt_panel._identity_header import (
            AGENT_FALLBACK_IDENTITY_COLOR,
            STEP_FALLBACK_IDENTITY_COLOR,
            WORKFLOW_IDENTITY_COLOR,
            _STEP_TYPE_COLORS,
        )
        from sase.ace.tui.widgets._agent_list_styling import (
            _AGENT_NAME_ANNOTATION_STYLE,
            _GATE_ROW_STYLE,
            _MONITOR_ROW_STYLE,
            _PROC_SHELL_ROW_STYLE,
        )

        styles = {
            "session": SESSION_IDENTITY_COLOR,
            "proc": _PROC_SHELL_ROW_STYLE,
            "agent_entry": _AGENT_NAME_ANNOTATION_STYLE,
            "gate": _GATE_ROW_STYLE,
            "monitor": _MONITOR_ROW_STYLE,
            "step_fallback": STEP_FALLBACK_IDENTITY_COLOR,
            "workflow": WORKFLOW_IDENTITY_COLOR,
            "agent": AGENT_FALLBACK_IDENTITY_COLOR,
            "step_colors": _STEP_TYPE_COLORS,
        }
        _KIND_STYLES = styles
    return styles


def node_finder_kind(agent: Agent) -> tuple[str, str]:
    """Return the kind label and accent color for *agent*."""
    if agent.is_clan_container:
        return ("CLAN", "#D75FFF")
    global _IDENTITY_KIND_FN  # noqa: PLW0603
    kind_fn = _IDENTITY_KIND_FN
    if kind_fn is None:
        from sase.ace.tui.widgets.prompt_panel._identity_header import (
            identity_kind_for_agent,
        )

        kind_fn = identity_kind_for_agent
        _IDENTITY_KIND_FN = kind_fn
    return kind_fn(agent)


def describe_node_finder_row(
    agent: Agent,
) -> tuple[bool, str, str, str, str]:
    """Return ``(jumpable, name, title, kind_label, kind_accent)`` for *agent*.

    Batch equivalent of :func:`node_finder_jumpable`, :func:`node_finder_name`,
    :func:`node_finder_title`, and :func:`node_finder_kind` that reads each
    agent property once. Snapshot building calls this per row instead of the
    four singles; the singles remain the behavior contract (see the
    differential test over every agent shape).
    """
    is_clan = agent.is_clan_container
    is_proc = agent.is_proc_shell
    is_wf_step = agent.is_workflow_step_child
    step_type = agent.step_type
    presented = agent.presented_agent_name
    agent_name = agent.agent_name
    display_name = agent.display_name
    cl_name = agent.cl_name
    # Each predicate below re-derives plan-chain role state, so read the
    # repeated ones once: snapshot building calls this per row.
    is_session_container = agent.is_agent_session_container_row
    is_monitor = agent.is_monitor
    is_gate = agent.is_gate
    is_agent_entry = agent.is_agent_entry
    if is_clan:
        name = (
            presented or agent.agent_clan or display_name or humanize_cl_name(cl_name)
        )
    elif is_proc:
        proc_label = agent.proc_label
        name = (
            proc_label
            or presented
            or agent_name
            or display_name
            or humanize_cl_name(cl_name)
        )
    else:
        name = presented or agent_name or display_name or humanize_cl_name(cl_name)

    if is_wf_step and step_type in ("bash", "python"):
        step_title = agent.step_name or display_name
        raw_title = step_title or None
    elif is_proc:
        raw_title = agent.proc_label or proc_shell_command_title(
            agent.proc_safe_preview
        )
    elif (
        not is_clan
        and not is_session_container
        and (
            is_monitor
            or is_gate
            or (is_wf_step and step_type == "agent")
            or agent.is_agent_session_member_child
        )
    ):
        raw_title = None
    else:
        raw_title = display_name or None
    if not raw_title or raw_title == name:
        title: str | None = None
    else:
        title = raw_title

    jumpable = not agent.is_pre_prompt_step and not (
        is_wf_step and step_type != "agent"
    )

    styles = _kind_styles()
    if is_clan:
        kind_label, kind_accent = "CLAN", "#D75FFF"
    elif is_session_container:
        kind_label, kind_accent = "SESSION", styles["session"]
    elif is_proc:
        kind_label, kind_accent = "PROC SHELL", styles["proc"]
    elif is_agent_entry:
        kind_label, kind_accent = "AGENT SHELL", styles["agent_entry"]
    elif is_gate:
        kind_label, kind_accent = "GATE", styles["gate"]
    elif is_monitor:
        kind_label, kind_accent = "MONITOR", styles["monitor"]
    elif is_wf_step and step_type:
        kind_label = "STEP"
        step_colors = styles["step_colors"]
        kind_accent = step_colors.get(step_type, styles["step_fallback"])
    elif (
        agent.agent_type is AgentType.WORKFLOW
        and not agent.is_workflow_child
        and not agent.appears_as_agent
    ):
        kind_label, kind_accent = "WORKFLOW", styles["workflow"]
    else:
        kind_label, kind_accent = "AGENT", styles["agent"]

    return (jumpable, name, title or "", kind_label, kind_accent)


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


# A row score is a ``(worst_tier, title_used, total_score)`` triple. Plain
# tuples keep batch scoring over thousands of rows off per-row allocation.
_RowScore = tuple[int, bool, int]


def _score_tokens(
    rows: tuple[NodeFinderRow, ...],
    candidates: list[int],
    tokens: tuple[str, ...],
) -> tuple[
    dict[int, _RowScore],
    dict[int, _RowScore],
    int | None,
    tuple[int, bool, int, int] | None,
    int | None,
    tuple[int, bool, int, int] | None,
]:
    """Score *tokens* over *candidates* with token-AND fuzzy matching.

    Each token takes the better of the name/title haystacks (ties keep
    the name), the contiguous pass keeps rows whose every token tiers
    0-2, and the any-match pass keeps every full-token match. Row titles
    repeat heavily across clan trees, so title scores memoize within the
    call. Best keys track in candidate order, matching insertion-order
    minimum.
    """
    contiguous: dict[int, _RowScore] = {}
    any_match: dict[int, _RowScore] = {}
    best_tight_pos: int | None = None
    best_tight_key: tuple[int, bool, int, int] | None = None
    best_loose_pos: int | None = None
    best_loose_key: tuple[int, bool, int, int] | None = None
    title_scores: dict[tuple[str, str], tuple[int, int] | None] = {}
    # Bind the scorer once: one token scores thousands of rows, so the
    # per-row module-global lookup is pure overhead.
    tier_score = fuzzy_tier_score
    for pos in candidates:
        row = rows[pos]
        if not row.jumpable:
            continue
        name = row.name
        title = row.title
        worst_contiguous = 0
        worst_any = 0
        used_title = False
        total = 0
        failed = False
        relaxed_only = False
        for token in tokens:
            name_tier_score = tier_score(token, name) if name else None
            if title:
                memo_key = (token, title)
                if memo_key in title_scores:
                    title_tier_score = title_scores[memo_key]
                else:
                    title_tier_score = tier_score(token, title)
                    title_scores[memo_key] = title_tier_score
            else:
                title_tier_score = None
            if name_tier_score is None:
                if title_tier_score is None:
                    failed = True
                    break
                tier, score = title_tier_score
                token_title_used = True
            elif title_tier_score is None:
                tier, score = name_tier_score
                token_title_used = False
            elif (title_tier_score[0], -title_tier_score[1]) < (
                name_tier_score[0],
                -name_tier_score[1],
            ):
                tier, score = title_tier_score
                token_title_used = True
            else:
                tier, score = name_tier_score
                token_title_used = False
            worst_any = max(worst_any, tier)
            used_title = used_title or token_title_used
            total += score
            if tier > 2:
                relaxed_only = True
            else:
                worst_contiguous = max(worst_contiguous, tier)
        if failed:
            continue
        loose: _RowScore = (worst_any, used_title, total)
        any_match[pos] = loose
        key = (worst_any, used_title, -total, pos)
        if best_loose_key is None or key < best_loose_key:
            best_loose_key = key
            best_loose_pos = pos
        if not relaxed_only:
            tight: _RowScore = (worst_contiguous, used_title, total)
            contiguous[pos] = tight
            if best_tight_key is None or key < best_tight_key:
                best_tight_key = key
                best_tight_pos = pos
    return (
        contiguous,
        any_match,
        best_tight_pos,
        best_tight_key,
        best_loose_pos,
        best_loose_key,
    )


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
    # Best match minimizes (worst tier, name-before-title, -score, order).
    # Tracked incrementally in candidate order so the later selection needs
    # no second pass over the matched rows.
    best_tight_pos: int | None = None
    best_tight_key: tuple[int, bool, int, int] | None = None
    best_loose_pos: int | None = None
    best_loose_key: tuple[int, bool, int, int] | None = None
    if tokens:
        (
            contiguous,
            any_match,
            best_tight_pos,
            best_tight_key,
            best_loose_pos,
            best_loose_key,
        ) = _score_tokens(rows, candidates, tokens)

    if not tokens:
        matched_positions = {pos for pos in candidates if rows[pos].jumpable}
        matched: dict[int, _RowScore] = {}
        relaxed = False
    elif contiguous:
        matched = contiguous
        matched_positions = set(matched)
        relaxed = False
    else:
        matched = any_match
        matched_positions = set(matched)
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

    best_pos: int | None
    if tokens:
        best_pos = best_tight_pos if contiguous else best_loose_pos
    else:
        if snapshot.here_row is not None and snapshot.here_row in matched_positions:
            best_pos = snapshot.here_row
        elif matched_positions:
            best_pos = min(matched_positions)
        else:
            best_pos = None

    if not matched_positions:
        return NodeFinderView(
            rows=(),
            best_index=None,
            relaxed=relaxed and bool(tokens),
            any_match=frozenset(),
            tokens=tokens,
            query=query,
        )

    if not tokens:
        full = _full_keep_view(
            snapshot,
            rows,
            matched_positions,
            any_identities,
            best_pos,
            relaxed,
            tokens,
            query,
        )
        if full is not None:
            return full
        matched = dict.fromkeys(matched_positions, (0, False, 0))
    elif len(matched) == snapshot.node_count:
        full = _full_keep_view(
            snapshot,
            rows,
            matched_positions,
            any_identities,
            best_pos,
            relaxed,
            tokens,
            query,
        )
        if full is not None:
            return full

    # One memoized ancestor chain per kept node replaces a per-header
    # scan over all kept nodes; the dict is shared with the header pass
    # below so each chain resolves once per filter call.
    chains: dict[int, list[int]] = {}
    keep: set[int] = set(matched)
    for pos in matched:
        keep.update(_ancestor_chain(rows, pos, chains))

    # Drop headers with no kept node rows beneath them. One ancestor walk
    # per kept node replaces a per-header scan over all kept nodes.
    kept_nodes = {pos for pos in keep if rows[pos].role is NodeFinderRole.NODE}
    headers_with_nodes = _headers_with_kept_descendants(rows, kept_nodes, chains)
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
        remapped_parent = new_index[parent] if parent is not None else None
        if row.role is NodeFinderRole.NODE and old not in matched:
            if row.jumpable or remapped_parent != row.parent_row:
                display_rows.append(
                    replace(row, parent_row=remapped_parent, jumpable=False)
                )
            else:
                display_rows.append(row)
        elif parent == row.parent_row and remapped_parent == row.parent_row:
            # The parent resolved to itself in the same slot: the row
            # already points at the right target, so reuse it as is.
            display_rows.append(row)
        else:
            display_rows.append(replace(row, parent_row=remapped_parent))
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


def _full_keep_view(
    snapshot: NodeFinderSnapshot,
    rows: tuple[NodeFinderRow, ...],
    matched_positions: set[int],
    any_identities: frozenset[AgentIdentity],
    best_pos: int | None,
    relaxed: bool,
    tokens: tuple[str, ...],
    query: str,
) -> NodeFinderView | None:
    """Return the filtered view directly when every row is kept.

    When all jumpable nodes match, the kept set is the whole snapshot
    exactly when every header shelters a kept node and every non-jumpable
    node is an ancestor of one (context). The ancestor walk stops as soon
    as every header and every non-jumpable node is accounted for, so
    full-tree queries skip per-row remapping and row copies entirely and
    reuse the snapshot rows as displayed. Returns ``None`` when the fast
    path does not apply so the caller falls back to the general display.
    """
    if len(matched_positions) != snapshot.node_count:
        return None
    total = len(rows)
    headers: set[int] = set()
    non_jumpable: set[int] = set()
    for pos, row in enumerate(rows):
        if row.role is not NodeFinderRole.NODE:
            headers.add(pos)
        elif not row.jumpable:
            non_jumpable.add(pos)
    if len(matched_positions) + len(headers) + len(non_jumpable) != total:
        # Jumpable nodes outside the match exist (a refinement-narrowed
        # candidate set): the kept set is partial, use the general path.
        return None
    pending_headers = set(headers)
    pending_non_jumpable = set(non_jumpable)
    for pos in matched_positions:
        current = rows[pos].parent_row
        seen = {pos}
        while current is not None and current not in seen:
            if not 0 <= current < total:
                break
            seen.add(current)
            if current in pending_headers:
                pending_headers.discard(current)
                if not pending_headers and not pending_non_jumpable:
                    break
            elif current in pending_non_jumpable:
                pending_non_jumpable.discard(current)
                if not pending_headers and not pending_non_jumpable:
                    break
            current = rows[current].parent_row
        if not pending_headers and not pending_non_jumpable:
            break
    if pending_headers or pending_non_jumpable:
        return None
    from sase.ace.tui.actions.navigation.jump_hints import build_jump_hint_maps

    context = frozenset(pos for pos in range(total) if pos not in matched_positions)
    hint_identities = [
        row.identity
        for pos, row in enumerate(rows)
        if row.jumpable and pos not in context and row.identity is not None
    ]
    overflow = len(hint_identities) > NODE_FINDER_HINT_CAPACITY
    hinted = hint_identities[:NODE_FINDER_HINT_CAPACITY]
    hint_to_identity, identity_to_hint = build_jump_hint_maps(hinted, prefix_free=True)
    return NodeFinderView(
        rows=rows,
        context=context,
        best_index=best_pos,
        relaxed=relaxed,
        hint_to_identity=dict(hint_to_identity),
        identity_to_hint=dict(identity_to_hint),
        overflow=overflow,
        any_match=any_identities,
        tokens=tokens,
        query=query,
    )


def _ancestor_chain(
    rows: tuple[NodeFinderRow, ...] | list[NodeFinderRow],
    pos: int,
    chains: dict[int, list[int]],
) -> list[int]:
    """Return *pos*'s strict ancestor positions, memoized in *chains*.

    Each row has a single ``parent_row``, so the walk is one deterministic
    chain; a resolved suffix splices in instead of re-walking. Cycle and
    bounds guards match the historical inline walks exactly, so counts and
    kept sets are unchanged.
    """
    cached = chains.get(pos)
    if cached is not None:
        return cached
    chain: list[int] = []
    seen: set[int] = set()
    total = len(rows)
    current = rows[pos].parent_row
    while current is not None and current not in seen:
        if not 0 <= current < total:
            break
        seen.add(current)
        chain.append(current)
        tail = chains.get(current)
        if tail is not None:
            for node in tail:
                if node in seen:
                    break
                seen.add(node)
                chain.append(node)
            break
        current = rows[current].parent_row
    chains[pos] = chain
    return chain


def _headers_with_kept_descendants(
    rows: tuple[NodeFinderRow, ...] | list[NodeFinderRow],
    kept_nodes: set[int],
    chains: dict[int, list[int]] | None = None,
) -> set[int]:
    """Return header positions with at least one kept node beneath them."""
    headers: set[int] = set()
    if chains is None:
        chains = {}
    for node_pos in kept_nodes:
        headers.update(_ancestor_chain(rows, node_pos, chains))
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
