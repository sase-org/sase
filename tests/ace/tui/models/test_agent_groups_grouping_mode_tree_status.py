"""GroupingMode: BY_STATUS ``build_agent_tree`` shape and ordering."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent_groups import (
    GroupingMode,
    build_agent_tree,
    enumerate_group_keys,
)

from ._agent_groups_helpers import _NOW, _agent, _group_keys, _kinds


def test_build_agent_tree_by_status_orders_buckets_priority_first() -> None:
    """BY_STATUS bucket order is fixed at
    Stopped → Failed → Running → Waiting → Done → Starting.
    """
    needs = _agent(
        cl_name="a",
        agent_name="x.a",
        status="QUESTION",
        start_time=None,
    )
    running = _agent(
        cl_name="b",
        agent_name="y.a",
        status="RUNNING",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    waiting = _agent(
        cl_name="e",
        agent_name="v.a",
        status="WAITING",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
        wait_until="2026-04-26T15:00:00",
    )
    failed = _agent(
        cl_name="c",
        agent_name="z.a",
        status="FAILED",
        start_time=datetime(2026, 4, 26, 8, 0, 0),
    )
    done = _agent(
        cl_name="d",
        agent_name="w.a",
        status="DONE",
        start_time=datetime(2026, 4, 26, 11, 0, 0),
    )
    starting = _agent(
        cl_name="f",
        agent_name="u.a",
        status="STARTING",
        start_time=datetime(2026, 4, 26, 12, 0, 0),
    )
    # Feed them in scrambled order with timestamps increasingly opposed to
    # priority, proving neither input order nor launch recency moves a bucket.
    entries = build_agent_tree(
        [starting, done, failed, needs, waiting, running],
        mode=GroupingMode.BY_STATUS,
        now=_NOW,
    )
    l0_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 0
    ]
    assert l0_banners == [
        ("Stopped",),
        ("Failed",),
        ("Running",),
        ("Waiting",),
        ("Done",),
        ("Starting",),
    ]


def test_build_agent_tree_by_status_sorts_running_units_by_launch_recency() -> None:
    newest = _agent(
        cl_name="newest",
        agent_name="newest",
        start_time=datetime(2026, 4, 26, 11, 0, 0),
    )
    equal_first = _agent(
        cl_name="equal-first",
        agent_name="equal-first",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    equal_second = _agent(
        cl_name="equal-second",
        agent_name="equal-second",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    older = _agent(
        cl_name="older",
        agent_name="older",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    missing = _agent(cl_name="missing", agent_name="missing", start_time=None)

    agents = [missing, equal_first, older, newest, equal_second]
    entries = build_agent_tree(agents, mode=GroupingMode.BY_STATUS, now=_NOW)

    assert [entry.agent_idx for entry in entries if entry.kind == "agent"] == [
        3,
        1,
        4,
        2,
        0,
    ]


@pytest.mark.parametrize("status", ["DONE", "WAITING"])
def test_build_agent_tree_by_status_sorts_terminal_and_waiting_by_launch_recency(
    status: str,
) -> None:
    newer = _agent(
        cl_name="newer",
        agent_name="newer",
        status=status,
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    older = _agent(
        cl_name="older",
        agent_name="older",
        status=status,
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    missing = _agent(
        cl_name="missing",
        agent_name="missing",
        status=status,
        start_time=None,
    )

    entries = build_agent_tree(
        [missing, older, newer], mode=GroupingMode.BY_STATUS, now=_NOW
    )

    assert [entry.agent_idx for entry in entries if entry.kind == "agent"] == [
        2,
        1,
        0,
    ]


def test_build_agent_tree_by_status_keeps_root_anchored_family_contiguous() -> None:
    family_root = _agent(
        cl_name="family-root",
        agent_name="a9f",
        raw_suffix="ts-root",
        role_suffix="-plan",
        agent_family="a9f",
        agent_family_role="root",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    newer_followup = _agent(
        cl_name="family-followup",
        agent_name="a9f.w1",
        raw_suffix="ts-followup",
        role_suffix="-plan",
        agent_family="a9f.w1",
        agent_family_role="root",
        start_time=datetime(2026, 4, 26, 12, 0, 0),
    )
    workflow_child = _agent(
        cl_name="family-step",
        agent_name="step.bash",
        parent_workflow="a9f.w1",
        parent_timestamp="ts-followup",
        status="DONE",
        start_time=datetime(2026, 4, 26, 13, 0, 0),
    )
    newer_singleton = _agent(
        cl_name="newer-singleton",
        agent_name="newer-singleton",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    older_singleton = _agent(
        cl_name="older-singleton",
        agent_name="older-singleton",
        start_time=datetime(2026, 4, 26, 8, 0, 0),
    )
    agents = [
        family_root,
        newer_followup,
        workflow_child,
        newer_singleton,
        older_singleton,
    ]

    entries = build_agent_tree(agents, mode=GroupingMode.BY_STATUS, now=_NOW)

    # The family's 09:00 root anchors the complete name group. Its newer
    # follow-up and workflow child neither split it nor move it above the 10:00
    # singleton, and its established root/follow-up/child preorder is retained.
    assert [entry.agent_idx for entry in entries if entry.kind == "agent"] == [
        3,
        0,
        1,
        2,
        4,
    ]
    rendered_banner_keys = [
        entry.group.group_key
        for entry in entries
        if entry.kind == "group" and entry.group is not None
    ]
    assert rendered_banner_keys == [
        ("Running",),
        ("Running", "a9f"),
        ("Running", "a9f", "a9f.w1"),
    ]
    assert (
        enumerate_group_keys(agents, mode=GroupingMode.BY_STATUS, now=_NOW)
        == rendered_banner_keys
    )


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
