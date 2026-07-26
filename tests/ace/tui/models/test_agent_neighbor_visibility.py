"""Tests for neighbor indexing across visible and prospective agent rows."""

from __future__ import annotations

from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_hoods import AgentNeighborIndex, AgentNeighborRow

from ._agent_neighbors_helpers import _agent, _rows_from_tree


def test_index_excludes_non_rendered_starting_rows() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo.plan")),
        AgentNeighborRow(1, 0, _agent("foo.starting", status="STARTING")),
        AgentNeighborRow(2, 0, _agent("foo.code")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.neighbors_for(0) == (2,)
    assert index.neighbors_for(1) == ()
    assert index.neighbors_for(2) == (0,)


def test_index_excludes_agents_hidden_by_collapsed_groups() -> None:
    agents = [
        _agent("foo.plan"),
        _agent("foo.code"),
        _agent("bar.plan"),
    ]
    registry = AgentGroupFoldRegistry()
    registry.collapse(("proj", "demo", "foo"))

    index = AgentNeighborIndex.from_visible_rows(_rows_from_tree(agents, registry))

    assert index.neighbors_for(0) == ()
    assert index.neighbors_for(1) == ()
    assert index.neighbors_for(2) == ()


def test_index_preserves_visible_render_order_across_panels() -> None:
    rows = [
        AgentNeighborRow(2, 0, _agent("foo.no_tribe")),
        AgentNeighborRow(0, 1, _agent("foo.alpha")),
        AgentNeighborRow(1, 2, _agent("foo.zeta")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.neighbors_for(2) == (0, 1)
    assert index.neighbors_for(0) == (2, 1)
    assert index.panel_idx_for(2) == 0
    assert index.panel_idx_for(0) == 1
    assert index.panel_idx_for(1) == 2


def test_index_includes_identity_stable_prospective_rows() -> None:
    origin = _agent("foo.plan", suffix="origin")
    hidden = _agent("foo.code", suffix="hidden", tribe="alpha")
    index = AgentNeighborIndex.from_visible_rows(
        [
            AgentNeighborRow(0, 0, origin, panel_key=None, display_order=0),
            AgentNeighborRow(
                None,
                1,
                hidden,
                panel_key="alpha",
                display_order=1,
                clan_fold_key="clan:workers:g1",
            ),
        ]
    )

    assert index.neighbors_for(0) == ()
    assert index.neighbor_count(0) == 1
    assert index.neighbor_targets_for(origin.identity) == (
        index.target_for_identity(hidden.identity),
    )
    target = index.target_for_identity(hidden.identity)
    assert target is not None
    assert target.global_idx is None
    assert target.panel_key == "alpha"
    assert target.is_prospective


def test_index_deduplicates_visible_and_prospective_identity() -> None:
    origin = _agent("foo.plan", suffix="origin")
    target = _agent("foo.code", suffix="target")
    visible = AgentNeighborRow(1, 0, target, display_order=1)
    stale_prospective = AgentNeighborRow(
        None,
        0,
        target,
        display_order=0,
        clan_fold_key="clan:workers:g1",
    )
    index = AgentNeighborIndex.from_visible_rows(
        [
            AgentNeighborRow(0, 0, origin, display_order=0),
            stale_prospective,
            visible,
        ]
    )

    assert index.neighbor_count(0) == 1
    assert index.neighbors_for(0) == (1,)
    assert index.target_for_identity(target.identity) == visible


def test_index_orders_hidden_neighbors_across_panels_by_display_order() -> None:
    origin = _agent("foo.plan", suffix="origin")
    alpha = _agent("foo.alpha", suffix="alpha", tribe="alpha")
    zeta = _agent("foo.zeta", suffix="zeta", tribe="zeta")
    index = AgentNeighborIndex.from_visible_rows(
        [
            AgentNeighborRow(0, 0, origin, display_order=0),
            AgentNeighborRow(
                None,
                2,
                zeta,
                panel_key="zeta",
                display_order=2,
                clan_fold_key="clan:zeta:g1",
            ),
            AgentNeighborRow(
                None,
                1,
                alpha,
                panel_key="alpha",
                display_order=1,
                clan_fold_key="clan:alpha:g1",
            ),
        ]
    )

    assert [row.identity for row in index.neighbor_targets_for(origin.identity)] == [
        alpha.identity,
        zeta.identity,
    ]
