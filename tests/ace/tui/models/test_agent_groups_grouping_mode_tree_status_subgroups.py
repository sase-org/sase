"""GroupingMode: BY_STATUS ``build_agent_tree`` subgroup shape."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree

from ._agent_groups_helpers import _NOW, _agent, _group_keys, _kinds


def test_build_agent_tree_by_status_groups_by_name_root_within_bucket() -> None:
    """L1 banners still apply within a bucket when ≥2 agents share a name_root."""
    a = _agent(cl_name="x", agent_name="coder.claude", status="RUNNING")
    b = _agent(cl_name="y", agent_name="coder.codex", status="RUNNING")
    c = _agent(cl_name="z", agent_name="solo.gemini", status="RUNNING")
    entries = build_agent_tree([a, b, c], mode=GroupingMode.BY_STATUS, now=_NOW)
    # One bucket banner ("Running"), then the singleton bare agent,
    # then the "coder" name-root banner with its two members.
    assert _kinds(entries) == [
        ("group", 0),
        ("agent", 2),
        ("group", 1),
        ("agent", 0),
        ("agent", 1),
    ]


def test_build_agent_tree_by_status_groups_dotted_agent_family_under_root() -> None:
    root = _agent(
        cl_name="x",
        agent_name="a9f",
        raw_suffix="ts-root",
        status="RUNNING",
        role_suffix="-plan",
        agent_family="a9f",
        agent_family_role="root",
    )
    wait_parent = _agent(
        cl_name="x",
        agent_name="a9f.w1",
        raw_suffix="ts-w1",
        status="RUNNING",
        role_suffix="-plan",
        agent_family="a9f.w1",
        agent_family_role="root",
    )
    wait_plan = _agent(
        cl_name="x",
        agent_name="a9f.w1-plan",
        parent_workflow="a9f.w1",
        parent_timestamp="ts-w1",
        status="DONE",
        role_suffix="-plan",
    )

    entries = build_agent_tree(
        [root, wait_parent, wait_plan], mode=GroupingMode.BY_STATUS, now=_NOW
    )

    assert _group_keys(entries, level=1) == [("Running", "a9f")]
    assert _group_keys(entries, level=2) == [("Running", "a9f", "a9f.w1")]
    assert ("Running", "a9f.w1") not in _group_keys(entries, level=1)
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
        ("group", 2),
        ("agent", 1),
        ("agent", 2),
    ]


def test_build_agent_tree_by_status_groups_shared_second_period_prefixes() -> None:
    """Shared dotted prefixes form subgroups under the existing name-root."""
    direct = _agent(cl_name="x", agent_name="sase-42.2", status="DONE")
    p1a = _agent(cl_name="x", agent_name="sase-42.1.1", status="DONE")
    p1b = _agent(cl_name="x", agent_name="sase-42.1.2", status="DONE")
    p2a = _agent(cl_name="x", agent_name="sase-42.2.1", status="DONE")
    p2b = _agent(cl_name="x", agent_name="sase-42.2.2", status="DONE")
    entries = build_agent_tree(
        [p2b, direct, p1b, p2a, p1a], mode=GroupingMode.BY_STATUS, now=_NOW
    )
    groups = [
        (e.group.level, e.group.group_key)  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None
    ]
    assert groups == [
        (0, ("Done",)),
        (1, ("Done", "sase-42")),
        (2, ("Done", "sase-42", "sase-42.1")),
        (2, ("Done", "sase-42", "sase-42.2")),
    ]
    # The exact parent marker participates in its same-prefix subgroup
    # and sorts before dotted descendants there.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
        ("agent", 2),
        ("agent", 4),
        ("group", 2),
        ("agent", 1),
        ("agent", 0),
        ("agent", 3),
    ]


def test_build_agent_tree_by_status_partitions_direct_lanes_before_prefix_groups() -> (
    None
):
    root = _agent(
        cl_name="root",
        agent_name="hk",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    direct = _agent(
        cl_name="direct",
        agent_name="hk.f0",
        start_time=datetime(2026, 4, 26, 8, 0, 0),
    )
    g1_root = _agent(
        cl_name="g1-root",
        agent_name="hk.g1",
        start_time=datetime(2026, 4, 26, 11, 0, 0),
    )
    g1_child = _agent(
        cl_name="g1-child",
        agent_name="hk.g1.f0",
        start_time=datetime(2026, 4, 26, 13, 0, 0),
    )
    g2_a = _agent(
        cl_name="g2-a",
        agent_name="hk.g2.a",
        start_time=datetime(2026, 4, 26, 12, 0, 0),
    )
    g2_b = _agent(
        cl_name="g2-b",
        agent_name="hk.g2.b",
        start_time=datetime(2026, 4, 26, 7, 0, 0),
    )
    agents = [g1_child, direct, g2_b, root, g1_root, g2_a]

    entries = build_agent_tree(agents, mode=GroupingMode.BY_STATUS, now=_NOW)

    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 3),
        ("agent", 1),
        ("group", 2),
        ("agent", 2),
        ("agent", 5),
        ("group", 2),
        ("agent", 4),
        ("agent", 0),
    ]
    assert _group_keys(entries, level=2) == [
        ("Running", "hk", "hk.g2"),
        ("Running", "hk", "hk.g1"),
    ]


def test_build_agent_tree_by_status_sorts_name_subgroups_by_launch_recency() -> None:
    newer_root = _agent(
        cl_name="newer-root",
        agent_name="newer",
        start_time=datetime(2026, 4, 26, 11, 0, 0),
    )
    newer_child = _agent(
        cl_name="newer-child",
        agent_name="newer.f0",
        start_time=datetime(2026, 4, 26, 7, 0, 0),
    )
    older_root = _agent(
        cl_name="older-root",
        agent_name="older",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    older_child = _agent(
        cl_name="older-child",
        agent_name="older.f0",
        start_time=datetime(2026, 4, 26, 13, 0, 0),
    )
    missing_root = _agent(
        cl_name="missing-root",
        agent_name="missing",
        start_time=None,
    )
    missing_child = _agent(
        cl_name="missing-child",
        agent_name="missing.f0",
        start_time=datetime(2026, 4, 26, 12, 0, 0),
    )
    agents = [
        older_child,
        missing_child,
        newer_root,
        older_root,
        newer_child,
        missing_root,
    ]

    entries = build_agent_tree(agents, mode=GroupingMode.BY_STATUS, now=_NOW)

    assert _group_keys(entries, level=1) == [
        ("Running", "newer"),
        ("Running", "older"),
        ("Running", "missing"),
    ]
    assert [entry.agent_idx for entry in entries if entry.kind == "agent"] == [
        2,
        4,
        0,
        3,
        1,
        5,
    ]


def test_build_agent_tree_by_status_groups_parent_marker_with_children() -> None:
    direct = _agent(cl_name="x", agent_name="sase-42.3", status="DONE")
    child_a = _agent(cl_name="x", agent_name="sase-42.3.1", status="DONE")
    child_b = _agent(cl_name="x", agent_name="sase-42.3.2", status="DONE")
    entries = build_agent_tree(
        [child_a, direct, child_b], mode=GroupingMode.BY_STATUS, now=_NOW
    )
    groups = [
        (e.group.level, e.group.group_key)  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None
    ]
    assert groups == [
        (0, ("Done",)),
        (1, ("Done", "sase-42")),
        (2, ("Done", "sase-42", "sase-42.3")),
    ]
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
        ("agent", 1),
        ("agent", 0),
        ("agent", 2),
    ]


def test_build_agent_tree_by_status_direct_plus_one_child_emits_prefix_group() -> None:
    direct = _agent(cl_name="x", agent_name="foo.bar", status="DONE")
    child = _agent(cl_name="x", agent_name="foo.bar.1", status="DONE")
    entries = build_agent_tree([child, direct], mode=GroupingMode.BY_STATUS, now=_NOW)
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
        ("agent", 1),
        ("agent", 0),
    ]


def test_build_agent_tree_by_status_suppresses_singleton_prefix_groups() -> None:
    a = _agent(cl_name="x", agent_name="sase-42.1.1", status="DONE")
    b = _agent(cl_name="x", agent_name="sase-42.2.1", status="DONE")
    entries = build_agent_tree([a, b], mode=GroupingMode.BY_STATUS, now=_NOW)
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("agent", 0),
        ("agent", 1),
    ]


def test_build_agent_tree_by_status_workflow_child_inherits_parent_prefix() -> None:
    parent = _agent(
        cl_name="x",
        agent_name="sase-42.2.1",
        raw_suffix="ts-parent",
        status="DONE",
    )
    child = _agent(
        cl_name="x",
        agent_name="step.bash",
        parent_workflow="sase-42",
        parent_timestamp="ts-parent",
        status="RUNNING",
    )
    entries = build_agent_tree([parent, child], mode=GroupingMode.BY_STATUS, now=_NOW)
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
        ("agent", 0),
        ("agent", 1),
    ]
    groups = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None
    ]
    assert ("Done", "sase-42", "sase-42.2") in groups


def test_build_agent_tree_single_bucket_still_renders_banner() -> None:
    """A panel that lands every agent in one bucket still shows the banner."""
    a = _agent(cl_name="a", agent_name="x", status="DONE")
    b = _agent(cl_name="b", agent_name="y", status="DONE")
    entries = build_agent_tree([a, b], mode=GroupingMode.BY_STATUS, now=_NOW)
    l0_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 0
    ]
    assert l0_banners == [("Done",)]
