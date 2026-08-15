"""Tests for family-sase-agent behavior in the agent neighbor index."""

from __future__ import annotations

from sase.ace.tui.models.agent_hoods import (
    AgentNeighborIndex,
    AgentNeighborRow,
    agent_hood,
    sase_agent_name,
    agent_name_key,
    agent_owns_sase_agent,
)
from sase.core.agent_identity_facade import agent_name_in_hood

from ._agent_neighbors_helpers import _agent, _family_member, _family_root


def test_lane_name_is_the_family_base_for_a_family_root_entry() -> None:
    root = _family_root("fam")
    member = _family_member("fam", role="code", parent=root)
    single = _agent("fam.helper")
    clan = _agent("workers")
    clan.is_clan_container = True

    assert root.presented_identity_name == "fam--plan"
    assert sase_agent_name(root) == "fam"
    assert agent_name_key(root) == "fam"
    # Members are not lanes; they keep their raw ``--`` key.
    assert sase_agent_name(member) == "fam--code"
    assert agent_name_key(member) == "fam--code"
    assert sase_agent_name(single) == "fam.helper"
    assert agent_name_key(single) == "fam.helper"
    assert sase_agent_name(clan) is None
    assert agent_name_key(clan) is None


def test_lane_name_key_still_rejects_malformed_and_empty_names() -> None:
    assert sase_agent_name(_agent(None)) is None
    assert agent_name_key(_agent(None)) is None
    assert agent_name_key(_agent("")) is None
    assert agent_name_key(_agent(".bar")) is None
    assert agent_name_key(_agent("foo..bar")) is None
    assert agent_name_key(_agent("Foo.Bar")) == "foo.bar"

    empty_family = _family_root("fam")
    empty_family.agent_family = None
    empty_family.agent_name = None
    empty_family.refresh_raw_presented_agent_name()
    assert sase_agent_name(empty_family) is None


def test_lane_name_leaves_agent_hood_unchanged_for_family_roots() -> None:
    assert agent_hood(_family_root("visual.worker")) == "visual"
    assert agent_hood(_agent("visual.worker")) == "visual"
    assert agent_hood(_family_root("fam")) is None
    assert agent_hood(_agent("fam")) is None


def test_top_level_family_lane_joins_the_hood_matching_its_name() -> None:
    root = _family_root("fam")
    helper = _agent("fam.helper")
    other = _agent("fam.other")
    rows = [
        AgentNeighborRow(0, 0, root),
        AgentNeighborRow(1, 0, helper),
        AgentNeighborRow(2, 0, other),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.descendants_for(0) == (1, 2)
    assert index.ancestors_for(1) == (0,)
    assert index.ancestors_for(2) == (0,)
    assert index.neighbors_for(1) == (2,)
    assert index.neighbors_for(2) == (1,)


def test_nested_family_lane_is_an_ancestor_of_its_dotted_hood_mates() -> None:
    root = _family_root("a.b")
    helper = _agent("a.b.helper")
    outer = _agent("a.other")
    rows = [
        AgentNeighborRow(0, 0, root),
        AgentNeighborRow(1, 0, helper),
        AgentNeighborRow(2, 0, outer),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.ancestors_for(1) == (0,)
    assert index.descendants_for(0) == (1,)
    # The family and its hood-mate now meet in ``a.b``, not only in ``a``.
    assert index.hood_neighbor_groups_for(1) == (("a", (2,)),)
    assert index.hood_neighbor_groups_for(0) == (("a", (2,)),)


def test_lane_hood_membership_agrees_with_the_core_identity_rule() -> None:
    root = _family_root("visual.worker")
    member = _family_member("visual.worker", role="impl", parent=root)
    rows_by_agent = [
        root,
        member,
        _agent("visual.helper"),
        _agent("visual.worker.notes"),
        _agent("other.bench"),
    ]
    index = AgentNeighborIndex.from_visible_rows(
        [AgentNeighborRow(idx, 0, agent) for idx, agent in enumerate(rows_by_agent)]
    )
    # Family member children are not lanes and intentionally keep their raw
    # ``--`` key, so parity is scoped to the lane rows.
    lane_indices = [
        idx for idx, agent in enumerate(rows_by_agent) if agent_owns_sase_agent(agent)
    ]
    assert lane_indices == [0, 2, 3, 4]

    hoods = {
        ".".join(name.split(".")[:depth])
        for idx in lane_indices
        if (name := agent_name_key(rows_by_agent[idx])) is not None
        for depth in range(1, len(name.split(".")) + 1)
    }

    for idx in lane_indices:
        name = sase_agent_name(rows_by_agent[idx]) or ""
        related = {
            *index.ancestors_for(idx),
            *index.descendants_for(idx),
            *index.neighbors_for(idx),
        } & set(lane_indices)
        for other in lane_indices:
            if other == idx:
                continue
            other_name = sase_agent_name(rows_by_agent[other]) or ""
            shares_hood = any(
                agent_name_in_hood(name, hood) and agent_name_in_hood(other_name, hood)
                for hood in hoods
            )
            assert (other in related) is shares_hood, (name, other_name)

    assert agent_name_in_hood("visual.worker--plan", "visual.worker") is True
    assert index.ancestors_for(3) == (0,)
    # The member row joins the lane through the ``--`` descendant edge rather
    # than through hood membership.
    assert index.descendants_for(0) == (1, 3)
    assert index.neighbors_for(4) == ()
