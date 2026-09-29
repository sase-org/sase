"""Header-count and fused-facet snapshot tests for the Node Finder row model."""

from __future__ import annotations

from sase.ace.tui.actions.agents._node_finder_snapshot import (
    build_node_finder_snapshot,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.node_finder import NodeFinderReason, NodeFinderRole
from sase.feature_flags.snapshot import override_flags
from tests.ace.tui._member_jump_navigation_helpers import (
    make_agent,
    make_agent_session,
    make_clan,
)
from tests.ace.tui._node_finder_snapshot_shared import (
    NodeFinderHarness,
    snapshot_node_rows,
)

__all__ = [
    "test_fused_facets_keep_counts_ancestors_and_reasons_across_grouping_modes",
    "test_snapshot_header_counts_match_brute_force_with_mixed_hidden_reasons",
]


def _is_snapshot_descendant(rows: list, node_pos: int, ancestor_pos: int) -> bool:
    current = rows[node_pos].parent_row
    seen: set[int] = set()
    while current is not None and current not in seen:
        if current == ancestor_pos:
            return True
        seen.add(current)
        current = rows[current].parent_row if 0 <= current < len(rows) else None
    return False


def test_snapshot_header_counts_match_brute_force_with_mixed_hidden_reasons() -> None:
    """Linear header counts stay exact with folds, query, and I-hidden rows."""
    projected, container = make_clan(3)
    sess_proj, _sroot, _schild = make_agent_session(in_clan=False)
    alpha = make_agent("alpha-one", tribe="alpha")
    beta = make_agent("beta-one", tribe="beta")
    visible = make_agent("visible", clan="research")
    hidden = make_agent("hidden", clan="research")
    hidden.hidden = True
    full = project_clan_tree([visible, hidden])
    visible_only = project_clan_tree([visible])
    complete = list(projected) + list(sess_proj) + [alpha, beta] + list(visible_only)
    app = NodeFinderHarness(complete, container)
    app._agents_local_with_children = full
    app._hideable_agents = [hidden]
    app.hide_non_run_agents = True
    app._agent_search_query = "member-0"
    with override_flags(agents_unified_query=False):
        app._refilter_agents()
        snap = build_node_finder_snapshot(app)

    rows = list(snap.rows)
    assert sum(1 for row in rows if row.role is not NodeFinderRole.NODE) >= 2

    def is_descendant(node_pos: int, ancestor_pos: int) -> bool:
        current = rows[node_pos].parent_row
        seen: set[int] = set()
        while current is not None and current not in seen:
            if current == ancestor_pos:
                return True
            seen.add(current)
            current = rows[current].parent_row if 0 <= current < len(rows) else None
        return False

    # Brute-force oracle: every header counts jumpable nodes beneath it.
    for pos, row in enumerate(rows):
        if row.role is NodeFinderRole.NODE:
            continue
        expected_jumpable = 0
        expected_hidden = 0
        for node_pos, node in enumerate(rows):
            if node.role is not NodeFinderRole.NODE or not node.jumpable:
                continue
            if node_pos == pos or is_descendant(node_pos, pos):
                expected_jumpable += 1
                if node.reasons:
                    expected_hidden += 1
        assert row.jumpable_count == expected_jumpable, f"header {pos}"
        assert row.hidden_count == expected_hidden, f"header {pos}"

    # Every kept header still has a kept node beneath it, and every kept
    # node's ancestors are kept.
    kept = set(range(len(rows)))
    node_positions = [pos for pos in kept if rows[pos].role is NodeFinderRole.NODE]
    assert node_positions
    for pos, row in enumerate(rows):
        if row.role is NodeFinderRole.NODE:
            continue
        assert any(
            node_pos == pos or is_descendant(node_pos, pos)
            for node_pos in node_positions
        ), f"header {pos} has no kept descendant"
    reasons_seen = {reason for row in rows for reason in row.reasons}
    assert NodeFinderReason.FOLDED in reasons_seen
    assert NodeFinderReason.QUERY in reasons_seen
    assert NodeFinderReason.NON_RUN in reasons_seen
    for pos in node_positions:
        current = rows[pos].parent_row
        seen: set[int] = set()
        while current is not None and current not in seen:
            assert current in kept, f"ancestor {current} of {pos} dropped"
            seen.add(current)
            current = rows[current].parent_row if 0 <= current < len(rows) else None


def test_fused_facets_keep_counts_ancestors_and_reasons_across_grouping_modes() -> None:
    """Fused per-open facets preserve rows and hidden reasons in every mode.

    The snapshot fuses repeated per-agent facet reads (identity,
    parent/depth, fold keys) once per open and shares one tree index across
    grouping, fold, and row construction. Grouping modes only re-banner the
    same rows, so the reachable node set, per-row hidden reasons, unmet fold
    counts, and header counts must be identical across modes.
    """
    projected, container = make_clan(3)
    sess_proj, _sroot, _schild = make_agent_session(in_clan=False)
    alpha = make_agent("alpha-one", tribe="alpha")
    beta = make_agent("beta-one", tribe="beta")
    gone = make_agent("gone")
    visible = make_agent("visible", clan="research")
    hidden = make_agent("hidden", clan="research")
    hidden.hidden = True
    full = project_clan_tree([visible, hidden])
    visible_only = project_clan_tree([visible])
    complete = (
        list(projected) + list(sess_proj) + [alpha, beta, gone] + list(visible_only)
    )
    modes = (
        GroupingMode.STANDARD,
        GroupingMode.BY_DATE,
        GroupingMode.BY_STATUS,
        GroupingMode.BY_MACHINE,
    )
    snaps = {}
    for mode in modes:
        app = NodeFinderHarness(list(complete), container)
        app._grouping_mode = mode
        app._agents_local_with_children = full
        app._hideable_agents = [hidden]
        app.hide_non_run_agents = True
        app._dismissed_agents = {gone.identity}
        app._agent_search_query = "member-0"
        with override_flags(agents_unified_query=False):
            app._refilter_agents()
            snaps[mode] = build_node_finder_snapshot(app)

    base = snaps[GroupingMode.STANDARD]
    base_nodes = {row.identity: row for row in snapshot_node_rows(base)}
    assert gone.identity not in base_nodes
    for mode in modes[1:]:
        snap = snaps[mode]
        assert snap.node_count == base.node_count, mode
        assert snap.hidden_count == base.hidden_count, mode
        assert snap.query_hidden_count == base.query_hidden_count, mode
        assert snap.hidden_by_i_count == base.hidden_by_i_count, mode
        nodes = {row.identity: row for row in snapshot_node_rows(snap)}
        assert set(nodes) == set(base_nodes), mode
        for identity, row in nodes.items():
            expected = base_nodes[identity]
            assert row.reasons == expected.reasons, (mode, identity)
            assert row.unmet_fold_count == expected.unmet_fold_count, (mode, identity)
            assert row.nearest_collapsed == expected.nearest_collapsed, (
                mode,
                identity,
            )
            assert row.jumpable == expected.jumpable, (mode, identity)

    for mode, snap in snaps.items():
        rows = list(snap.rows)
        for pos, row in enumerate(rows):
            if row.role is NodeFinderRole.NODE:
                continue
            expected_jumpable = 0
            expected_hidden = 0
            for node_pos, node in enumerate(rows):
                if node.role is not NodeFinderRole.NODE or not node.jumpable:
                    continue
                if node_pos == pos or _is_snapshot_descendant(rows, node_pos, pos):
                    expected_jumpable += 1
                    if node.reasons:
                        expected_hidden += 1
            assert row.jumpable_count == expected_jumpable, (mode, pos)
            assert row.hidden_count == expected_hidden, (mode, pos)
        for pos, row in enumerate(rows):
            if row.role is not NodeFinderRole.NODE:
                continue
            # Member rows parent to their tree container node, so chains
            # may pass through nodes: they must terminate at valid rows.
            current = row.parent_row
            seen: set[int] = set()
            steps = 0
            while current is not None and current not in seen:
                assert 0 <= current < len(rows), (mode, pos, current)
                assert steps < len(rows), (mode, pos)
                seen.add(current)
                steps += 1
                current = rows[current].parent_row
