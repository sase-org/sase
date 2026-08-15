"""Tests for the shared sase-agent neighbor projection."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_hoods import (
    AgentNeighborIndex,
    AgentNeighborRow,
    agent_owns_sase_agent,
)
from sase.ace.tui.models.sase_agent_neighbors import (
    build_sase_agent_neighbor_projection,
)


def _agent(
    name: str | None,
    *,
    suffix: str | None = None,
    **overrides: object,
) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name or "unnamed",
        "project_file": "/r/proj/proj.sase",
        "status": "RUNNING",
        "start_time": datetime(2026, 7, 25, 12, 0, 0),
        "raw_suffix": suffix if suffix is not None else name,
        "agent_name": name,
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


def _family_root(family: str, *, role: str = "plan") -> Agent:
    """Return a family root entry that renders under its bare family base."""
    root = _agent(f"{family}--{role}")
    root.agent_family = family
    root.agent_family_role = "root"
    root.plan_chain_root = True
    root.refresh_raw_presented_agent_name()
    return root


def _index(*agents: Agent) -> AgentNeighborIndex:
    return AgentNeighborIndex.from_visible_rows(
        [
            AgentNeighborRow(
                global_idx=idx,
                panel_idx=0,
                agent=agent,
                display_order=idx,
            )
            for idx, agent in enumerate(agents)
        ]
    )


def test_projection_orders_ancestors_descendants_and_hood_groups() -> None:
    ancestor = _agent("A")
    parent = _agent("A.B")
    source = _agent("A.B.C")
    descendant = _agent("A.B.C.child")
    same_hood = _agent("A.B.peer")
    outer_hood = _agent("A.other")
    index = _index(
        outer_hood,
        descendant,
        source,
        ancestor,
        same_hood,
        parent,
    )

    projection = build_sase_agent_neighbor_projection(
        lane_identity=source.identity,
        lane_name=source.presented_identity_name,
        index=index,
        hood_labels={"a": "A", "a.b": "A.B"},
    )

    assert [row.agent for row in projection.rows] == [
        parent,
        ancestor,
        descendant,
        same_hood,
        outer_hood,
    ]
    assert [row.relation for row in projection.rows] == [
        "ancestor",
        "ancestor",
        "descendant",
        "neighbor",
        "neighbor",
    ]
    assert [row.group_label for row in projection.rows] == [
        "ancestors",
        "ancestors",
        "descendants",
        "A.B hood",
        "A hood",
    ]
    assert [row.label_prefix for row in projection.rows] == [
        "",
        "",
        "A.B.C",
        "A.B",
        "A",
    ]
    assert [row.hood for row in projection.rows] == ["", "", "", "A.B", "A"]


def test_projection_interleaves_dismissed_descendants_by_name() -> None:
    source = _agent("foo")
    alpha = _agent("foo.alpha")
    charlie = _agent("foo.charlie")
    bravo = _agent("foo.bravo", suffix="dismissed-bravo")

    projection = build_sase_agent_neighbor_projection(
        lane_identity=source.identity,
        lane_name="foo",
        index=_index(charlie, source, alpha),
        dismissed_descendants=(bravo,),
    )

    assert [row.agent for row in projection.rows] == [alpha, bravo, charlie]
    assert [row.is_dismissed for row in projection.rows] == [
        False,
        True,
        False,
    ]
    assert projection.rows[1].index_row is None
    assert projection.rows[1].is_prospective is False


def test_projection_suppresses_family_members_and_counts_them() -> None:
    source = _agent("myclan.worker--plan")
    member = _agent("myclan.worker--impl")
    helper = _agent("myclan.worker--impl.helper")

    projection = build_sase_agent_neighbor_projection(
        lane_identity=source.identity,
        lane_name="myclan.worker",
        index=_index(source, member, helper),
        suppressed_identities={member.identity},
    )

    assert [row.agent for row in projection.rows] == [helper]
    assert projection.suppressed_lane_member_count == 1
    assert projection.is_empty is False


def test_projection_never_lists_the_lane_as_its_own_neighbor() -> None:
    source = _agent("myclan.worker--plan")
    # An expanded family renders its root member a second time under a
    # synthetic identity, so identity-only suppression would keep it.
    duplicate = _agent("myclan.worker--plan", raw_suffix=None)
    peer = _agent("myclan.helper")

    projection = build_sase_agent_neighbor_projection(
        lane_identity=source.identity,
        lane_name="myclan.worker--plan",
        index=_index(source, duplicate, peer),
        suppressed_identities={source.identity},
    )

    assert duplicate.identity != source.identity
    assert [row.agent for row in projection.rows] == [peer]
    assert projection.suppressed_lane_member_count == 0


def test_projection_drops_the_duplicate_root_member_row_of_a_family_lane() -> None:
    source = _family_root("myclan.worker")
    # Once the lane keys on the bare family base, the expanded family's second
    # root-member row is only reachable through ``lane_row_names``.
    duplicate = _agent("myclan.worker--plan", raw_suffix=None)
    peer = _agent("myclan.helper")

    projection = build_sase_agent_neighbor_projection(
        lane_identity=source.identity,
        lane_name="myclan.worker",
        lane_row_names=("myclan.worker--plan",),
        index=_index(source, duplicate, peer),
        suppressed_identities={source.identity},
    )

    assert duplicate.identity != source.identity
    assert [row.agent for row in projection.rows] == [peer]
    assert projection.suppressed_lane_member_count == 0


def test_projection_without_lane_row_names_leaks_the_duplicate_root_member() -> None:
    source = _family_root("myclan.worker")
    duplicate = _agent("myclan.worker--plan", raw_suffix=None)
    peer = _agent("myclan.helper")

    projection = build_sase_agent_neighbor_projection(
        lane_identity=source.identity,
        lane_name="myclan.worker",
        index=_index(source, duplicate, peer),
        suppressed_identities={source.identity},
    )

    assert [row.agent for row in projection.rows] == [duplicate, peer]


def test_top_level_family_lane_projects_its_dotted_hood_mates() -> None:
    root = _family_root("fam")
    helper = _agent("fam.helper")
    other = _agent("fam.other")

    projection = build_sase_agent_neighbor_projection(
        lane_identity=root.identity,
        lane_name="fam",
        lane_row_names=("fam--plan",),
        index=_index(root, helper, other),
        hood_labels={"fam": "fam"},
    )

    assert [row.agent for row in projection.rows] == [helper, other]
    assert [row.relation for row in projection.rows] == [
        "descendant",
        "descendant",
    ]
    assert [row.label_prefix for row in projection.rows] == ["fam", "fam"]


def test_projection_preserves_prospective_neighbor_flag() -> None:
    source = _agent("foo.plan")
    prospective = _agent("foo.code")
    index = AgentNeighborIndex.from_visible_rows(
        [
            AgentNeighborRow(0, 0, source, display_order=0),
            AgentNeighborRow(
                None,
                0,
                prospective,
                display_order=1,
                clan_fold_key="clan:workers",
            ),
        ]
    )

    projection = build_sase_agent_neighbor_projection(
        lane_identity=source.identity,
        lane_name="foo.plan",
        index=index,
    )

    assert [row.agent for row in projection.rows] == [prospective]
    assert projection.rows[0].is_prospective is True


def test_projection_is_empty_when_lane_has_no_relations() -> None:
    source = _agent("solo")

    projection = build_sase_agent_neighbor_projection(
        lane_identity=source.identity,
        lane_name="solo",
        index=_index(source),
    )

    assert projection.rows == ()
    assert projection.suppressed_lane_member_count == 0
    assert projection.is_empty is True


def test_agent_owns_sase_agent_truth_table() -> None:
    plain = _agent("plain")
    unnamed = _agent(None)
    clan = _agent("clan")
    clan.is_clan_container = True
    hidden = _agent("hidden", is_hidden_step=True)
    workflow_child = _agent("workflow.step", parent_workflow="workflow")
    family_member = _agent("family--code", parent_timestamp="family--plan")
    family = _agent("family--plan")
    family.agent_family = "family"
    family.agent_family_role = "root"
    family.followup_agents = [family_member]

    assert family.is_family_container_row is True
    assert agent_owns_sase_agent(family) is True
    assert agent_owns_sase_agent(plain) is True
    assert agent_owns_sase_agent(clan) is False
    assert agent_owns_sase_agent(family_member) is False
    assert agent_owns_sase_agent(workflow_child) is False
    assert agent_owns_sase_agent(hidden) is False
    assert agent_owns_sase_agent(unnamed) is False
