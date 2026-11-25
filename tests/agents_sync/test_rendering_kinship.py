from __future__ import annotations

import random

from sase.agents_sync.rendering_kinship import (
    NEIGHBOR_GROUP_LIMIT,
    _Node,
    _NodeKinshipGroup,
    _NodeKinshipProjection,
    _node_indexes,
    _node_projection,
    _node_sort_key,
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


def test_agent_session_is_one_lane_and_never_lists_its_members() -> None:
    root = _run("foo.crew--root")
    code = _run("foo.crew--code", state="failed")
    sibling = _run("foo.sibling")
    agent_session = V2ContainerRecord(
        "session",
        "alice.athena.foo.crew",
        (root.source_run_id, code.source_run_id),
    )

    kinship = build_hood_kinship(
        _snapshot(root, code, sibling, containers=(agent_session,))
    )

    assert kinship.lane_for_source(root.source_run_id) == "foo.crew"
    assert kinship.lane_for_source(code.source_run_id) == "foo.crew"
    projection = kinship.for_lane("foo.crew")
    assert [row.lane_name for row in projection.rows] == ["foo.sibling"]
    sibling_projection = kinship.for_lane("foo.sibling")
    session_row = sibling_projection.rows[0]
    assert session_row.lane_name == "foo.crew"
    assert session_row.is_session is True
    assert session_row.member_count == 2
    assert session_row.state == "completed 1, failed 1"


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


def test_indexed_projection_matches_reference_for_hand_built_and_random_chains() -> (
    None
):
    rng = random.Random(2601)
    nodes = [
        _synthetic_node(
            f"root.branch{index:02d}.leaf{index:02d}",
            ("root", f"root.branch{index % 4:02d}", f"root.branch{index % 4:02d}"),
            is_session=index % 9 == 0,
        )
        for index in range(75)
    ]
    nodes.extend(
        (
            _synthetic_node("root", ("root", "root", "root")),
            _synthetic_node("root.branch00", ("root", "root.branch00")),
            _synthetic_node(
                "root.branch00.overflow",
                ("root", "root.branch00", "root.branch00.overflow"),
            ),
        )
    )
    for index in range(60):
        branch = rng.randrange(5)
        leaf = rng.randrange(8)
        chain = ["root", f"root.branch{branch}"]
        if rng.random() < 0.5:
            chain.append(chain[-1])
        if rng.random() < 0.65:
            chain.append(f"{chain[-1]}.leaf{leaf}")
        name = f"agent{index:03d}"
        nodes.append(_synthetic_node(name, tuple(chain), is_session=index % 7 == 0))

    ordered = tuple(sorted(nodes, key=_node_sort_key))
    by_name = {node.name: node for node in ordered}
    member_indexes = _node_indexes(ordered, include_self=True)
    descendant_indexes = _node_indexes(ordered, include_self=False)
    for node in ordered:
        actual = _node_projection(node, by_name, member_indexes, descendant_indexes)
        expected = _reference_projection(node, ordered, by_name)
        assert actual == expected


def test_large_hood_kinship_sort_key_calls_grow_near_linearly(
    monkeypatch,
) -> None:  # type: ignore[no-untyped-def]
    import sase.agents_sync.rendering_kinship as rendering_kinship

    snapshot = _snapshot(*(_run(f"foo.node{index:04d}") for index in range(3000)))
    real_sort_key = rendering_kinship._node_sort_key
    calls = 0

    def counting_sort_key(node: _Node) -> tuple[str, str]:
        nonlocal calls
        calls += 1
        return real_sort_key(node)

    monkeypatch.setattr(rendering_kinship, "_node_sort_key", counting_sort_key)
    kinship = build_hood_kinship(snapshot)

    assert len(kinship.lanes) == 3000
    assert calls < 100_000


def _synthetic_node(
    name: str,
    chain: tuple[str, ...],
    *,
    is_session: bool = False,
) -> _Node:
    runs = (_run(name), _run(f"{name}.member")) if is_session else (_run(name),)
    return _Node(name, f"agents/{name}/README.md", runs, is_session, chain)


def _reference_projection(
    node: _Node,
    nodes: tuple[_Node, ...],
    by_name: dict[str, _Node],
) -> _NodeKinshipProjection:
    """The pre-index projection algorithm, retained only as a test oracle."""

    assigned = {node.name}
    groups: list[_NodeKinshipGroup] = []
    ancestors = [
        by_name[name]
        for name in reversed(node.chain[:-1])
        if name in by_name and name not in assigned
    ]
    if ancestors:
        groups.append(_reference_group("ancestor", ancestors))
        assigned.update(item.name for item in ancestors)

    descendants = sorted(
        (
            candidate
            for candidate in nodes
            if node.name in candidate.chain[:-1] and candidate.name not in assigned
        ),
        key=_node_sort_key,
    )
    if descendants:
        groups.append(_reference_group("descendant", descendants))
        assigned.update(item.name for item in descendants)

    for hood in reversed(node.chain):
        neighbors = sorted(
            (
                candidate
                for candidate in nodes
                if hood in candidate.chain and candidate.name not in assigned
            ),
            key=_node_sort_key,
        )
        if neighbors:
            relation = f"{hood} hood"
            groups.append(_reference_group(relation, neighbors))
            assigned.update(item.name for item in neighbors)
    return _NodeKinshipProjection(node.name, tuple(groups))


def _reference_group(
    relation: str,
    nodes: list[_Node],
) -> _NodeKinshipGroup:
    visible = nodes[:NEIGHBOR_GROUP_LIMIT]
    return _NodeKinshipGroup(
        relation,
        tuple(node.row(relation) for node in visible),
        len(nodes) - len(visible),
    )
