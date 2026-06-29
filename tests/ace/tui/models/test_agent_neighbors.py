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
    tag: str | None = None,
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
        tag=tag,
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


def test_parent_and_sub_hood_descendant_are_not_all_neighbors() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo")),
        AgentNeighborRow(1, 0, _agent("foo.bar")),
        AgentNeighborRow(2, 0, _agent("foo.bar.baz")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    # ``foo`` is dotless -> no hood, ``foo.bar`` lives in hood ``foo`` and
    # ``foo.bar.baz`` lives in hood ``foo.bar``: no two of them share a hood.
    assert index.neighbors_for(0) == ()
    assert index.neighbors_for(1) == ()
    assert index.neighbors_for(2) == ()


def test_index_groups_by_exact_hood_not_first_segment() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("foo.plan")),
        AgentNeighborRow(1, 0, _agent("foo.code")),
        AgentNeighborRow(2, 0, _agent("foo.review.pass1")),
        AgentNeighborRow(3, 0, _agent("foo.review.pass2")),
        AgentNeighborRow(4, 0, _agent("bar.plan")),
        AgentNeighborRow(5, 0, _agent("foo")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    # hood ``foo``: plan + code (NOT the deeper review.* agents nor dotless foo)
    assert index.neighbors_for(0) == (1,)
    assert index.neighbors_for(1) == (0,)
    # hood ``foo.review``: the two pass agents
    assert index.neighbors_for(2) == (3,)
    assert index.neighbors_for(3) == (2,)
    # ``bar.plan`` (hood ``bar``) and dotless ``foo`` have no neighbors
    assert index.neighbors_for(4) == ()
    assert index.neighbors_for(5) == ()


def test_index_excludes_dotless_names() -> None:
    index = AgentNeighborIndex.from_visible_rows(
        [
            AgentNeighborRow(0, 0, _agent("foo")),
            AgentNeighborRow(1, 0, _agent("foo")),
        ]
    )

    assert index.neighbors_for(0) == ()
    assert index.neighbors_for(1) == ()


def test_index_matches_case_insensitively() -> None:
    rows = [
        AgentNeighborRow(0, 0, _agent("Foo.plan")),
        AgentNeighborRow(1, 0, _agent("foo.code")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.neighbors_for(0) == (1,)
    assert index.neighbors_for(1) == (0,)


def test_agent_descendant_uses_dotted_boundary_prefix() -> None:
    assert is_agent_descendant("foo.bar.baz", "foo.bar") is True
    assert is_agent_descendant("Foo.Bar.Baz", "foo.bar") is True
    assert is_agent_descendant("foo.bar.baz.deep", "foo.bar") is True
    assert is_agent_descendant("foo.barbaz", "foo.bar") is False
    assert is_agent_descendant("foo.bar", "foo.bar") is False
    assert is_agent_descendant("foo..bar", "foo") is False
    assert is_agent_descendant("", "foo") is False


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
        AgentNeighborRow(2, 0, _agent("foo.untagged")),
        AgentNeighborRow(0, 1, _agent("foo.alpha")),
        AgentNeighborRow(1, 2, _agent("foo.zeta")),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.neighbors_for(2) == (0, 1)
    assert index.neighbors_for(0) == (2, 1)
    assert index.panel_idx_for(2) == 0
    assert index.panel_idx_for(0) == 1
    assert index.panel_idx_for(1) == 2
