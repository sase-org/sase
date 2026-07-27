from __future__ import annotations

from sase.agents_sync.rendering_kinship import (
    NEIGHBOR_GROUP_LIMIT,
    build_hood_kinship,
    render_neighbors_section,
)
from sase.agents_sync.v2_models import (
    RunState,
    V2ContainerRecord,
    V2HoodSnapshot,
    V2ProjectIdentity,
    V2RunRecord,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity


def _run(name: str, *, state: RunState = "completed") -> V2RunRecord:
    suffix = name.replace(".", "-").replace("--", "-")
    return V2RunRecord(
        f"run-{suffix}",
        name,
        f"alice.athena.{name}",
        state,
    )


def _snapshot(
    *runs: V2RunRecord,
    containers: tuple[V2ContainerRecord, ...] = (),
) -> V2HoodSnapshot:
    return V2HoodSnapshot(
        AgentOwnerIdentity("alice", "athena"),
        V2ProjectIdentity("proj", "Project"),
        "foo",
        "alice.athena.foo",
        runs=runs,
        containers=containers,
    )


def test_projection_orders_ancestors_descendants_and_hood_groups() -> None:
    snapshot = _snapshot(
        _run("foo"),
        _run("foo.bar"),
        _run("foo.bar.zed"),
        _run("foo.bar.alpha"),
        _run("foo.baz"),
    )

    kinship = build_hood_kinship(snapshot)
    leaf = kinship.for_lane("foo.bar.zed")
    assert [(row.lane_name, row.relation) for row in leaf.rows] == [
        ("foo.bar", "ancestor"),
        ("foo", "ancestor"),
        ("foo.bar.alpha", "foo.bar hood"),
        ("foo.baz", "foo hood"),
    ]

    parent = kinship.for_lane("foo.bar")
    assert [(row.lane_name, row.relation) for row in parent.rows] == [
        ("foo", "ancestor"),
        ("foo.bar.alpha", "descendant"),
        ("foo.bar.zed", "descendant"),
        ("foo.baz", "foo hood"),
    ]
    assert len({row.lane_name for row in parent.rows}) == len(parent.rows)


def test_family_is_one_lane_and_never_lists_its_members() -> None:
    root = _run("foo.family--root")
    code = _run("foo.family--code", state="failed")
    sibling = _run("foo.sibling")
    family = V2ContainerRecord(
        "family",
        "alice.athena.foo.family",
        (root.source_run_id, code.source_run_id),
    )

    kinship = build_hood_kinship(_snapshot(root, code, sibling, containers=(family,)))

    assert kinship.lane_for_source(root.source_run_id) == "foo.family"
    assert kinship.lane_for_source(code.source_run_id) == "foo.family"
    projection = kinship.for_lane("foo.family")
    assert [row.lane_name for row in projection.rows] == ["foo.sibling"]
    sibling_projection = kinship.for_lane("foo.sibling")
    family_row = sibling_projection.rows[0]
    assert family_row.lane_name == "foo.family"
    assert family_row.is_family is True
    assert family_row.member_count == 2
    assert family_row.state == "completed 1, failed 1"


def test_lone_lane_has_no_neighbor_groups() -> None:
    kinship = build_hood_kinship(_snapshot(_run("foo")))

    assert kinship.for_lane("foo").groups == ()


def test_historical_double_dash_name_uses_facade_ancestor_chain() -> None:
    kinship = build_hood_kinship(_snapshot(_run("fi"), _run("fi--code.f0")))

    assert [
        (row.lane_name, row.relation) for row in kinship.for_lane("fi--code.f0").rows
    ] == [("fi", "ancestor")]


def test_each_relation_group_is_capped_with_a_roster_tail() -> None:
    target = _run("foo.target")
    siblings = tuple(
        _run(f"foo.sibling{index:02d}") for index in range(NEIGHBOR_GROUP_LIMIT + 1)
    )
    kinship = build_hood_kinship(_snapshot(target, *siblings))

    group = kinship.for_lane("foo.target").groups[0]
    assert len(group.rows) == NEIGHBOR_GROUP_LIMIT
    assert group.overflow_count == 1

    rendered = "\n".join(
        render_neighbors_section(
            kinship,
            lane_name="foo.target",
            source_path="agents/alice.athena.foo.target/README.md",
        )
    )
    assert (
        "… and 1 more in the "
        "[hood roster](../../users/alice/machines/athena/hoods/foo/README.md)"
        in rendered
    )
