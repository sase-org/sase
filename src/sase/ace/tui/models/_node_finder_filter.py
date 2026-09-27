"""Node Finder token-AND fuzzy filtering over a snapshot.

Split from :mod:`sase.ace.tui.models.node_finder`: scores query tokens
over jumpable rows with a contiguous pass plus a relaxed fallback, then
projects the kept rows (with context headers) into a filtered view with
jump-hint maps.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from sase.core.fuzzy_facade import fuzzy_tier_score

from ._node_finder_types import (
    NODE_FINDER_HINT_CAPACITY,
    NodeFinderRole,
    NodeFinderRow,
    NodeFinderSnapshot,
    NodeFinderView,
)

if TYPE_CHECKING:
    from ._node_finder_types import AgentIdentity


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
    # Empty queries never narrow by refinement (a refinement needs a longer
    # or extended token tuple), so the node scan below covers the whole
    # roster and the position list is never built.
    node_positions: list[int] = []
    if tokens:
        node_positions = [
            i for i, row in enumerate(rows) if row.role is NodeFinderRole.NODE
        ]

    candidates = node_positions
    if (
        tokens
        and previous is not None
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
        # One pass over the roster replaces the position list plus the
        # matched/identity scans: without tokens every candidate is a node
        # position and refinement never narrows, so jumpable nodes are
        # exactly the matched set and their identities the any-match set.
        matched_positions = set()
        _any_list: list[AgentIdentity] = []
        for _pos, _row in enumerate(rows):
            if _row.role is NodeFinderRole.NODE and _row.jumpable:
                matched_positions.add(_pos)
                _identity = _row.identity
                if _identity is not None:
                    _any_list.append(_identity)
        any_identities = frozenset(_any_list)
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
    # Without tokens the fused scan above already set ``any_identities``.

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

    # The partition check above proved every non-matched position is a
    # header or a non-jumpable node, so their union is exactly the
    # context set without scanning the range against the match set.
    context = frozenset(headers | non_jumpable)
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
