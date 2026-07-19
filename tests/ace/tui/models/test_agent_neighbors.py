"""Tests for the Agents-tab neighbor index model (dotted-name hoods)."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import build_agent_tree
from sase.ace.tui.models.agent_hoods import (
    AgentNeighborIndex,
    AgentNeighborRow,
    agent_hood,
    is_agent_descendant,
)


def _agent(
    name: str | None,
    *,
    status: str = "RUNNING",
    tribe: str | None = None,
    suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/r/proj/proj.sase",
        status=status,
        start_time=datetime(2026, 5, 23, 12, 0, 0),
        raw_suffix=suffix or name,
        agent_name=name,
        tribe=tribe,
    )


def _rows_from_tree(
    agents: list[Agent], registry: AgentGroupFoldRegistry
) -> list[AgentNeighborRow]:
    tree = build_agent_tree(agents, fold_registry=registry)
    return [
        AgentNeighborRow(entry.agent_idx, 0, agents[entry.agent_idx])
        for entry in tree
        if entry.kind == "agent" and entry.agent_idx is not None
    ]


def test_agent_hood_is_immediate_dotted_namespace() -> None:
    assert agent_hood(_agent("foo.bar")) == "foo"
    assert agent_hood(_agent("foo.bar.baz")) == "foo.bar"
    assert agent_hood(_agent("foo.bar.baz.qux")) == "foo.bar.baz"


def test_agent_hood_is_none_for_dotless_names() -> None:
    assert agent_hood(_agent("foo")) is None


def test_agent_hood_rejects_empty_or_malformed_names() -> None:
    assert agent_hood(_agent("")) is None
    assert agent_hood(_agent(".bar")) is None
    assert agent_hood(_agent("foo.")) is None
    assert agent_hood(_agent("foo..bar")) is None
    assert agent_hood(_agent("foo.bar..baz")) is None
    assert agent_hood(_agent(None)) is None


def test_agent_hood_matches_case_insensitively() -> None:
    assert agent_hood(_agent("Foo.plan")) == "foo"
    assert agent_hood(_agent("foo.Code")) == "foo"
    assert agent_hood(_agent("Foo.Bar.baz")) == "foo.bar"


def test_neighbors_share_the_same_immediate_hood() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo.bar")),
        AgentNeighborRow(1, 0, _agent("foo.baz")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.neighbors_for(0) == (1,)
    assert index.neighbors_for(1) == (0,)


def test_deeper_agents_are_neighbors_within_their_sub_hood() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo.bar.baz")),
        AgentNeighborRow(1, 0, _agent("foo.bar.qux")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.neighbors_for(0) == (1,)
    assert index.neighbors_for(1) == (0,)


def test_prefix_relations_are_excluded_from_hood_neighbor_groups() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo")),
        AgentNeighborRow(1, 0, _agent("foo.bar")),
        AgentNeighborRow(2, 0, _agent("foo.bar.baz")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.neighbors_for(0) == ()
    assert index.neighbors_for(1) == ()
    assert index.neighbors_for(2) == ()
    assert index.descendants_for(0) == (1, 2)
    assert index.ancestors_for(2) == (1, 0)


def test_index_groups_by_deepest_shared_hood() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo.plan")),
        AgentNeighborRow(1, 0, _agent("foo.code")),
        AgentNeighborRow(2, 0, _agent("foo.review.pass1")),
        AgentNeighborRow(3, 0, _agent("foo.review.pass2")),
        AgentNeighborRow(4, 0, _agent("bar.plan")),
        AgentNeighborRow(5, 0, _agent("foo")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.hood_neighbor_groups_for(0) == (("foo", (1, 2, 3)),)
    assert index.neighbors_for(0) == (1, 2, 3)
    assert index.hood_neighbor_groups_for(2) == (
        ("foo.review", (3,)),
        ("foo", (0, 1)),
    )
    assert index.neighbors_for(2) == (3, 0, 1)
    assert index.ancestors_for(0) == (5,)
    assert index.descendants_for(5) == (1, 0, 2, 3)
    assert index.neighbors_for(4) == ()
    assert index.neighbors_for(5) == ()


def test_index_groups_duplicate_dotless_names_in_own_name_hood() -> None:
    index = AgentNeighborIndex.from_visible_rows(
        [
            AgentNeighborRow(0, 0, _agent("foo")),
            AgentNeighborRow(1, 0, _agent("foo")),
        ]
    )

    assert index.hood_neighbor_groups_for(0) == (("foo", (1,)),)
    assert index.hood_neighbor_groups_for(1) == (("foo", (0,)),)


def test_index_matches_case_insensitively() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("Foo.plan")),
        AgentNeighborRow(1, 0, _agent("foo.code")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.neighbors_for(0) == (1,)
    assert index.neighbors_for(1) == (0,)


def test_agent_descendant_uses_dotted_or_family_boundary_prefix() -> None:
    assert is_agent_descendant("foo.bar.baz", "foo.bar") is True
    assert is_agent_descendant("Foo.Bar.Baz", "foo.bar") is True
    assert is_agent_descendant("foo.bar.baz.deep", "foo.bar") is True
    assert is_agent_descendant("foo.bar--check", "foo.bar") is True
    assert is_agent_descendant("fam--plan--check", "fam--plan") is True
    assert is_agent_descendant("foo.barbaz", "foo.bar") is False
    assert is_agent_descendant("deployer2", "deploy") is False
    assert is_agent_descendant("foo.bar", "foo.bar") is False
    assert is_agent_descendant("foo..bar", "foo") is False
    assert is_agent_descendant("", "foo") is False


def test_non_prefix_name_overlap_can_still_share_a_shallower_hood() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo.bar")),
        AgentNeighborRow(1, 0, _agent("foo.barbaz")),
        AgentNeighborRow(2, 0, _agent("foobar.child")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.ancestors_for(1) == ()
    assert index.descendants_for(0) == ()
    assert index.hood_neighbor_groups_for(0) == (("foo", (1,)),)
    assert index.neighbors_for(2) == ()


def test_index_tracks_visible_descendants_for_dotless_and_dotted_agents() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo")),
        AgentNeighborRow(1, 0, _agent("foo.bar")),
        AgentNeighborRow(2, 0, _agent("foo.bar.baz")),
        AgentNeighborRow(3, 0, _agent("foo.barbaz")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.descendants_for(0) == (1, 2, 3)
    assert index.descendants_for(1) == (2,)
    assert index.descendants_for(2) == ()
    assert index.descendant_count(0) == 3
    assert index.descendant_count(1) == 1


def test_index_tracks_visible_ancestors_nearest_first() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("0aa")),
        AgentNeighborRow(1, 0, _agent("0aa.cld")),
        AgentNeighborRow(2, 0, _agent("0aa.cld.f1")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.ancestors_for(2) == (1, 0)
    assert index.ancestor_count(2) == 2
    assert index.ancestors_for(1) == (0,)
    assert index.ancestors_for(0) == ()


def test_index_tracks_family_chain_ancestors_and_descendants() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("fam")),
        AgentNeighborRow(1, 0, _agent("fam--plan")),
        AgentNeighborRow(2, 0, _agent("fam--plan--check")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.ancestors_for(2) == (1, 0)
    assert index.descendants_for(0) == (1, 2)
    assert index.descendants_for(1) == (2,)
    assert index.neighbors_for(0) == ()
    assert index.neighbors_for(1) == ()


def test_index_tracks_ancestors_case_insensitively() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("Foo")),
        AgentNeighborRow(1, 0, _agent("foo.Bar")),
        AgentNeighborRow(2, 0, _agent("FOO.BAR.Baz")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.ancestors_for(2) == (1, 0)


def test_index_does_not_report_agent_as_its_own_ancestor() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo")),
        AgentNeighborRow(1, 0, _agent("foo.bar")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.ancestors_for(0) == ()
    assert 1 not in index.ancestors_for(1)


def test_index_ancestor_lookup_excludes_non_rendered_rows() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo", status="STARTING")),
        AgentNeighborRow(1, 0, _agent("foo.bar")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.ancestors_for(1) == ()
    assert index.ancestor_count(1) == 0


def test_index_ancestor_lookup_ignores_non_visible_prefix_rows() -> None:
    rows = [
        AgentNeighborRow(1, 0, _agent("foo.bar")),
        AgentNeighborRow(2, 0, _agent("foo.bar.baz")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.ancestors_for(2) == (1,)


def test_index_descendant_count_includes_dismissed_kin() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo.bar")),
        AgentNeighborRow(1, 0, _agent("foo.bar.visible")),
        AgentNeighborRow(2, 0, _agent("foo.barbaz")),
    ]
    dismissed = [
        _agent("foo.bar.dismissed"),
        _agent("foo.bar.dismissed.deep"),
        _agent("foo.barbaz.dismissed"),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows, dismissed_agents=dismissed)

    assert index.descendants_for(0) == (1,)
    assert index.descendant_count(0) == 3


def test_index_descendant_count_includes_dismissed_family_chain() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("fam--plan")),
        AgentNeighborRow(1, 0, _agent("fam--plan--visible")),
    ]
    dismissed = [_agent("fam--plan--dismissed")]

    index = AgentNeighborIndex.from_visible_rows(rows, dismissed_agents=dismissed)

    assert index.descendants_for(0) == (1,)
    assert index.descendant_count(0) == 2


def test_index_assigns_duplicate_nephew_and_cousin_to_closest_hood() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("a.b.c")),
        AgentNeighborRow(1, 0, _agent("a.b.d.e")),
        AgentNeighborRow(2, 0, _agent("a.z.1")),
        AgentNeighborRow(3, 0, _agent("a.b.c")),
        AgentNeighborRow(4, 0, _agent("a.b.d")),
        AgentNeighborRow(5, 0, _agent("a.bx")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.hood_neighbor_groups_for(0) == (
        ("a.b.c", (3,)),
        ("a.b", (1, 4)),
        ("a", (2, 5)),
    )
    assert index.neighbors_for(0) == (3, 1, 4, 2, 5)


def test_family_mates_need_prefix_or_dotted_hood_relation() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("fam--plan")),
        AgentNeighborRow(1, 0, _agent("fam--fix")),
        AgentNeighborRow(2, 0, _agent("clan.fam--plan")),
        AgentNeighborRow(3, 0, _agent("clan.fam--fix")),
        AgentNeighborRow(4, 0, _agent("clan.fam--plan--check")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    # Top-level family mates share neither a boundary prefix nor a dotted hood.
    assert index.neighbors_for(0) == ()
    assert index.neighbors_for(1) == ()
    assert index.hood_neighbor_groups_for(2) == (("clan", (3,)),)
    assert index.descendants_for(2) == (4,)


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
