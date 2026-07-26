"""Tests for the Agents-tab neighbor index model (dotted-name hoods)."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups._keys import status_grouping_signature
from sase.ace.tui.models.agent_groups import build_agent_tree
from sase.ace.tui.models.agent_hoods import (
    AgentNeighborIndex,
    AgentNeighborRow,
    agent_hood,
    agent_lane_name,
    agent_name_key,
    agent_owns_lane,
    is_agent_descendant,
)
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    AgentOwnerIdentity,
    agent_name_in_hood,
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


def _family_root(family: str, *, role: str = "plan") -> Agent:
    """Return a family root entry that renders under its bare family base."""
    root = _agent(f"{family}--{role}")
    root.agent_family = family
    root.agent_family_role = "root"
    root.plan_chain_root = True
    root.refresh_raw_presented_agent_name()
    return root


def _family_member(family: str, *, role: str, parent: Agent) -> Agent:
    """Return a concrete family-member child row of ``parent``."""
    member = _agent(f"{family}--{role}")
    member.agent_family = family
    member.agent_family_role = role
    member.parent_timestamp = parent.raw_suffix
    parent.followup_agents = [*parent.followup_agents, member]
    return member


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


def test_machine_hood_is_removed_before_local_kinship_indexing() -> None:
    identity = AgentIdentitySnapshot(
        AgentOwnerIdentity("alice", "athena"),
        ("athena", "zeus"),
    )
    local = _agent("athena.foo.plan")
    legacy = _agent("foo.code")
    foreign = _agent("zeus.foo.plan")
    for agent in (local, legacy, foreign):
        agent.refresh_presented_agent_name(identity)

    assert local.agent_name == "athena.foo.plan"
    assert local.presented_agent_name == "foo.plan"
    assert local.presented_identity_name == "foo.plan"
    assert agent_hood(local) == "foo"
    assert agent_hood(legacy) == "foo"
    assert foreign.presented_agent_name == "zeus.foo.plan"
    assert agent_hood(foreign) == "zeus.foo"

    index = AgentNeighborIndex.from_visible_rows(
        [
            AgentNeighborRow(0, 0, local),
            AgentNeighborRow(1, 0, legacy),
            AgentNeighborRow(2, 0, foreign),
        ]
    )
    assert index.neighbors_for(0) == (1,)
    assert index.neighbors_for(1) == (0,)
    assert index.neighbors_for(2) == ()
    assert status_grouping_signature(local)[1:3] == ("foo", "foo.plan")


def test_agent_row_construction_does_not_read_machine_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_current(_cls: type[AgentIdentitySnapshot]) -> AgentIdentitySnapshot:
        raise AssertionError("row construction must not resolve machine config")

    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(fail_current),
    )

    agent = _agent("athena.foo")

    assert agent.presented_agent_name == "athena.foo"
    assert agent.presented_identity_name == "athena.foo"


def test_family_display_and_kinship_identity_are_normalized_independently() -> None:
    family = _agent("athena.foo--plan")
    family.agent_family = "athena.foo"
    family.agent_family_role = "root"
    family.plan_chain_root = True
    family.refresh_presented_agent_name(
        AgentIdentitySnapshot(
            AgentOwnerIdentity("alice", "athena"),
            ("athena", "zeus"),
        )
    )

    assert family.presented_agent_name == "foo"
    assert family.presented_identity_name == "foo--plan"


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


def test_index_suppresses_family_root_member_duplicate_from_descendants() -> None:
    root = _family_root("fam", role="0")
    root.cl_name = "family-root"
    root.raw_suffix = "root"
    main = _family_member("fam", role="0", parent=root)
    main.cl_name = "main"
    main.raw_suffix = "main"
    coder = _family_member("fam", role="code", parent=root)
    coder.cl_name = "coder"
    coder.raw_suffix = "coder"

    rows = [
        AgentNeighborRow(0, 0, root),
        AgentNeighborRow(1, 0, main),
        AgentNeighborRow(2, 0, coder),
    ]

    index = AgentNeighborIndex.from_visible_rows(rows)

    assert index.descendants_for(0) == (2,)
    assert index.descendant_count(0) == 1


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


def test_lane_name_is_the_family_base_for_a_family_root_entry() -> None:
    root = _family_root("fam")
    member = _family_member("fam", role="code", parent=root)
    single = _agent("fam.helper")
    clan = _agent("workers")
    clan.is_clan_container = True

    assert root.presented_identity_name == "fam--plan"
    assert agent_lane_name(root) == "fam"
    assert agent_name_key(root) == "fam"
    # Members are not lanes; they keep their raw ``--`` key.
    assert agent_lane_name(member) == "fam--code"
    assert agent_name_key(member) == "fam--code"
    assert agent_lane_name(single) == "fam.helper"
    assert agent_name_key(single) == "fam.helper"
    assert agent_lane_name(clan) is None
    assert agent_name_key(clan) is None


def test_lane_name_key_still_rejects_malformed_and_empty_names() -> None:
    assert agent_lane_name(_agent(None)) is None
    assert agent_name_key(_agent(None)) is None
    assert agent_name_key(_agent("")) is None
    assert agent_name_key(_agent(".bar")) is None
    assert agent_name_key(_agent("foo..bar")) is None
    assert agent_name_key(_agent("Foo.Bar")) == "foo.bar"

    empty_family = _family_root("fam")
    empty_family.agent_family = None
    empty_family.agent_name = None
    empty_family.refresh_raw_presented_agent_name()
    assert agent_lane_name(empty_family) is None


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
    # The family lane and its hood-mate now meet in ``a.b``, not only in ``a``.
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
        idx for idx, agent in enumerate(rows_by_agent) if agent_owns_lane(agent)
    ]
    assert lane_indices == [0, 2, 3, 4]

    hoods = {
        ".".join(name.split(".")[:depth])
        for idx in lane_indices
        if (name := agent_name_key(rows_by_agent[idx])) is not None
        for depth in range(1, len(name.split(".")) + 1)
    }

    for idx in lane_indices:
        name = agent_lane_name(rows_by_agent[idx]) or ""
        related = {
            *index.ancestors_for(idx),
            *index.descendants_for(idx),
            *index.neighbors_for(idx),
        } & set(lane_indices)
        for other in lane_indices:
            if other == idx:
                continue
            other_name = agent_lane_name(rows_by_agent[other]) or ""
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
