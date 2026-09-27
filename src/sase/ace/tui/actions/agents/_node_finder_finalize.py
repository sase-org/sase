"""Omission and header-count finalization for the Node Finder snapshot.

Split from :mod:`_node_finder_snapshot`: drops unkept rows, remaps
parent positions, and counts jumpable/hidden nodes per header.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ...models.node_finder import NodeFinderReason, NodeFinderRole, NodeFinderRow

if TYPE_CHECKING:
    from ...models.agent import AgentType

    AgentIdentity = tuple[AgentType, str, str | None]


def evolve_row(row: NodeFinderRow, **changes: Any) -> NodeFinderRow:
    """Return *row* with *changes* applied via :func:`dataclasses.replace`."""
    return replace(row, **changes)


def _ancestor_chain(
    rows: list[NodeFinderRow], pos: int, chains: dict[int, list[int]]
) -> list[int]:
    """Return *pos*'s strict ancestor positions, memoized in *chains*.

    Each row has a single ``parent_row``, so the walk is one deterministic
    chain; a resolved suffix splices in instead of re-walking. Cycle
    (stop at the first repeated position) and bounds guards match the
    historical per-node walks exactly, so header sets and counts are
    unchanged.
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
    rows: list[NodeFinderRow],
    kept_nodes: set[int],
    chains: dict[int, list[int]] | None = None,
) -> set[int]:
    """Return header positions that have at least one kept node beneath them."""
    if chains is None:
        chains = {}
    headers: set[int] = set()
    for node_pos in kept_nodes:
        headers.update(_ancestor_chain(rows, node_pos, chains))
    return headers


def _accumulate_header_counts(
    rows: list[NodeFinderRow],
    chains: dict[int, list[int]] | None = None,
) -> dict[int, tuple[int, int]]:
    """Count jumpable/hidden nodes beneath each header in one linear pass."""
    if chains is None:
        chains = {}
    jumpable_counts: dict[int, int] = {}
    hidden_counts: dict[int, int] = {}
    headers: list[int] = []
    for pos, row in enumerate(rows):
        if row.role is NodeFinderRole.NODE:
            continue
        headers.append(pos)
        jumpable_counts[pos] = 0
        hidden_counts[pos] = 0
    header_set = set(headers)
    for node_pos, node in enumerate(rows):
        if node.role is not NodeFinderRole.NODE or not node.jumpable:
            continue
        hidden = bool(node.reasons)
        if node_pos in header_set:
            jumpable_counts[node_pos] += 1
            if hidden:
                hidden_counts[node_pos] += 1
        for ancestor in _ancestor_chain(rows, node_pos, chains):
            if ancestor in header_set:
                jumpable_counts[ancestor] += 1
                if hidden:
                    hidden_counts[ancestor] += 1
    return {pos: (jumpable_counts[pos], hidden_counts[pos]) for pos in headers}


def apply_snapshot_omission(
    rows: list[NodeFinderRow],
    dismissed: set[AgentIdentity],
    rendered: set[AgentIdentity],
    descendant_of_jumpable: set[AgentIdentity],
) -> tuple[
    list[NodeFinderRow],
    dict[AgentIdentity, int],
    dict[int, list[int]] | None,
]:
    """Drop unkept rows and remap parent positions.

    Dismissed rows, rows whose hider is unknown (not rendered and no
    computed reason), and non-jumpable steps without a jumpable descendant
    never get a hint, so they stay out. ``descendant_of_jumpable`` was
    collected in the row loop. Returns ``(rows, index_by_identity,
    counts_chains)`` where ``counts_chains`` carries the memoized ancestor
    chains when positions are stable and ``None`` after a remap.
    """
    # Omission pass: dismissed rows, rows whose hider is unknown (not
    # rendered and no computed reason), and non-jumpable steps without a
    # jumpable descendant never get a hint, so they stay out.
    # ``descendant_of_jumpable`` was collected in the row loop above.
    keep = [True] * len(rows)
    for pos, row in enumerate(rows):
        if row.role is not NodeFinderRole.NODE:
            continue
        if row.identity in dismissed:
            keep[pos] = False
        elif not row.jumpable and row.identity not in descendant_of_jumpable:
            keep[pos] = False
        elif not row.reasons and row.identity not in rendered:
            keep[pos] = False

    kept_nodes = {
        pos
        for pos, row in enumerate(rows)
        if keep[pos] and row.role is NodeFinderRole.NODE
    }
    # One memoized ancestor chain per node shared with the header-count
    # pass below; positions are stable when nothing is omitted.
    chains: dict[int, list[int]] = {}
    headers_with_nodes = _headers_with_kept_descendants(rows, kept_nodes, chains)
    for pos, row in enumerate(rows):
        if not keep[pos] or row.role is NodeFinderRole.NODE:
            continue
        if pos not in headers_with_nodes:
            keep[pos] = False

    kept_positions = [pos for pos, kept in enumerate(keep) if kept]
    new_index = {old: new for new, old in enumerate(kept_positions)}
    counts_chains: dict[int, list[int]] | None = chains
    if len(kept_positions) != len(rows):
        # Remapping renumbers positions, so the header-count pass resolves
        # its own chains over the final row set.
        counts_chains = None
        remapped: list[NodeFinderRow] = []
        for old in kept_positions:
            row = rows[old]
            parent_pos = row.parent_row
            while parent_pos is not None and parent_pos not in new_index:
                parent_pos = (
                    rows[parent_pos].parent_row if 0 <= parent_pos < len(rows) else None
                )
            if parent_pos == row.parent_row and (
                parent_pos is None or new_index[parent_pos] == parent_pos
            ):
                # The parent resolved to itself in the same slot: the row
                # already points at the right target, so reuse it as is.
                remapped.append(row)
            else:
                remapped.append(
                    evolve_row(
                        row,
                        parent_row=(
                            new_index[parent_pos] if parent_pos is not None else None
                        ),
                    )
                )
        rows = remapped
    index_by_identity = {
        row.identity: pos
        for pos, row in enumerate(rows)
        if row.role is NodeFinderRole.NODE and row.identity is not None
    }
    return rows, index_by_identity, counts_chains


def count_snapshot_headers(
    rows: list[NodeFinderRow],
    counts_chains: dict[int, list[int]] | None,
    clean_keep: bool,
) -> tuple[dict[int, tuple[int, int]], int, int, int, int]:
    """Count headers and node totals over the final row set.

    Each jumpable node contributes to every header above it in one
    ancestor walk instead of scanning all nodes once per header. On the
    clean-keep path positions never moved, so one reverse pass accumulates
    each subtree total into its parent with no chain memo: rows are in
    preorder (every parent precedes its children, including node-to-node
    tree parents, which must already be indexed to become a parent), so
    visiting children first propagates each node's own jumpable/hidden
    unit up through every header above it — the same sums the chain walks
    produce. Returns ``(header_counts, node_count, hidden, query_hidden,
    hidden_by_i_count)``.
    """
    node_count = 0
    hidden = 0
    query_hidden = 0
    hidden_by_i_count = 0
    if clean_keep:
        jumpable_subtree = [0] * len(rows)
        hidden_subtree = [0] * len(rows)
        for pos in range(len(rows) - 1, -1, -1):
            row = rows[pos]
            if row.role is NodeFinderRole.NODE and row.jumpable:
                node_count += 1
                row_reasons = row.reasons
                if row_reasons:
                    hidden += 1
                    if NodeFinderReason.QUERY in row_reasons:
                        query_hidden += 1
                    if NodeFinderReason.NON_RUN in row_reasons:
                        hidden_by_i_count += 1
                    jumpable_subtree[pos] += 1
                    hidden_subtree[pos] += 1
                else:
                    jumpable_subtree[pos] += 1
            parent_pos = row.parent_row
            if parent_pos is not None and 0 <= parent_pos < len(rows):
                jumpable_subtree[parent_pos] += jumpable_subtree[pos]
                hidden_subtree[parent_pos] += hidden_subtree[pos]
        header_counts = {
            pos: (jumpable_subtree[pos], hidden_subtree[pos])
            for pos, row in enumerate(rows)
            if row.role is not NodeFinderRole.NODE
        }
    else:
        header_counts = _accumulate_header_counts(rows, counts_chains)
        # The clean-keep linear pass above already tallied the node totals
        # alongside the header counts; other paths count here.
        for row in rows:
            if row.role is not NodeFinderRole.NODE or not row.jumpable:
                continue
            node_count += 1
            row_reasons = row.reasons
            if not row_reasons:
                continue
            hidden += 1
            if NodeFinderReason.QUERY in row_reasons:
                query_hidden += 1
            if NodeFinderReason.NON_RUN in row_reasons:
                hidden_by_i_count += 1
    return header_counts, node_count, hidden, query_hidden, hidden_by_i_count


__all__ = [
    "apply_snapshot_omission",
    "count_snapshot_headers",
    "evolve_row",
]
