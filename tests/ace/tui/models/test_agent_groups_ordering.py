"""Dedupe + deterministic group ordering for the agent tree."""

from __future__ import annotations

from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import TreeEntry, build_agent_tree

from ._agent_groups_helpers import _agent, _group_keys, _kinds


def test_full_tree_does_not_split_same_project_group() -> None:
    """Members of the same project interleaved with another project render once each."""
    a = _agent(cl_name="cl-a", project_file="/r/projA/proj.gp")
    b = _agent(cl_name="cl-b", project_file="/r/projB/proj.gp")
    c = _agent(cl_name="cl-a", project_file="/r/projA/proj.gp")
    entries = build_agent_tree([a, b, c])
    proj_keys = _group_keys(entries, level=0)
    assert len(proj_keys) == 2


def test_full_tree_sort_is_deterministic() -> None:
    """Same agents in different orders produce identical tree shapes."""
    a = _agent(cl_name="a", project_file="/r/projA/proj.gp")
    b = _agent(cl_name="b", project_file="/r/projB/proj.gp")
    c = _agent(cl_name="c", project_file="")

    order1 = build_agent_tree([a, b, c])
    order2 = build_agent_tree([c, b, a])
    order3 = build_agent_tree([b, c, a])

    def reduce_keys(entries: list[TreeEntry]) -> list[tuple[str, ...] | None]:
        out: list[tuple[str, ...] | None] = []
        for e in entries:
            if e.kind == "group":
                assert e.group is not None
                out.append(e.group.group_key)
            else:
                out.append(None)
        return out

    assert reduce_keys(order1) == reduce_keys(order2) == reduce_keys(order3)


def test_full_tree_named_projects_sort_before_unprojected() -> None:
    entries = build_agent_tree(
        [
            _agent(cl_name="a", project_file="/r/beta/proj.gp"),
            _agent(cl_name="b", project_file=""),
            _agent(cl_name="c", project_file="/r/alpha/proj.gp"),
        ]
    )
    proj_keys = _group_keys(entries, level=0)
    assert [k[0] for k in proj_keys] == ["alpha", "beta", ""]


def test_full_tree_workflow_children_stay_with_parent_after_sort() -> None:
    """Workflow children keep parent-adjacent ordering even with an interloper."""
    parent = _agent(cl_name="demo", agent_name="solo", raw_suffix="ts1")
    child1 = _agent(
        cl_name="step1",
        agent_name="step1",
        parent_workflow="solo",
        parent_timestamp="ts1",
    )
    other = _agent(cl_name="other", agent_name="other")
    child2 = _agent(
        cl_name="step2",
        agent_name="step2",
        parent_workflow="solo",
        parent_timestamp="ts1",
    )
    entries = build_agent_tree([parent, child1, other, child2])

    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    # demo (cl_name=demo) sorts before "other" within the same project.
    assert agent_order == [0, 1, 3, 2]


def test_full_tree_singleton_name_root_still_suppressed_after_sort() -> None:
    """Sort-driven walk doesn't regress the singleton name-root suppression."""
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="solo.gemini"),
            _agent(cl_name="demo", agent_name="coder.claude"),
            _agent(cl_name="demo", agent_name="coder.codex"),
        ]
    )
    deep_banners = [
        e
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 2
    ]
    assert len(deep_banners) == 1
    assert deep_banners[0].group.group_key[-1] == "coder"  # type: ignore[union-attr]
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    assert agent_order == [0, 1, 2]


def test_singleton_dotted_agent_sorts_above_grouped_name_root() -> None:
    """A singleton dotted agent renders above the deeper group banner."""
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="solo.gemini"),
            _agent(cl_name="demo", agent_name="coder.claude"),
            _agent(cl_name="demo", agent_name="coder.codex"),
        ]
    )
    # Project + ChangeSpec banners, the singleton, then the coder group.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
        ("group", 2),
        ("agent", 1),
        ("agent", 2),
    ]


def test_dotless_and_singleton_agents_both_precede_grouped_name_root() -> None:
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="bare"),
            _agent(cl_name="demo", agent_name="lone.x"),
            _agent(cl_name="demo", agent_name="grp.a"),
            _agent(cl_name="demo", agent_name="grp.b"),
        ]
    )
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
        ("agent", 1),
        ("group", 2),
        ("agent", 2),
        ("agent", 3),
    ]


def test_dotless_parent_and_resume_child_sort_inside_name_root_group() -> None:
    entries = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="foo"),
            _agent(cl_name="demo", agent_name="bar"),
            _agent(cl_name="demo", agent_name="foo.r1"),
        ]
    )
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 1),
        ("group", 2),
        ("agent", 0),
        ("agent", 2),
    ]


def test_ungrouped_bucket_preserves_input_order() -> None:
    perm_a = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="bare"),
            _agent(cl_name="demo", agent_name="lone.x"),
            _agent(cl_name="demo", agent_name="grp.a"),
            _agent(cl_name="demo", agent_name="grp.b"),
        ]
    )
    perm_b = build_agent_tree(
        [
            _agent(cl_name="demo", agent_name="lone.x"),
            _agent(cl_name="demo", agent_name="bare"),
            _agent(cl_name="demo", agent_name="grp.a"),
            _agent(cl_name="demo", agent_name="grp.b"),
        ]
    )
    order_a = [e.agent_idx for e in perm_a if e.kind == "agent"]
    order_b = [e.agent_idx for e in perm_b if e.kind == "agent"]
    assert order_a == [0, 1, 2, 3]
    assert order_b == [0, 1, 2, 3]


def test_collapsed_tree_order_is_deterministic() -> None:
    a = _agent(cl_name="a", project_file="/r/projA/proj.gp")
    b = _agent(cl_name="b", project_file="/r/projB/proj.gp")
    c = _agent(cl_name="c", project_file="")
    registry = AgentGroupFoldRegistry()
    registry.collapse_keys([("projA",), ("projB",), ("",)])

    order1 = build_agent_tree([a, b, c], fold_registry=registry)
    order2 = build_agent_tree([c, a, b], fold_registry=registry)
    order3 = build_agent_tree([b, c, a], fold_registry=registry)

    def banner_keys(entries: list[TreeEntry]) -> list[tuple[int, tuple[str, ...]]]:
        return [
            (e.group.level, e.group.group_key)  # type: ignore[union-attr]
            for e in entries
            if e.kind == "group" and e.group is not None
        ]

    assert banner_keys(order1) == banner_keys(order2) == banner_keys(order3)
