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


def test_build_agent_tree_by_status_keeps_standalone_lanes_above_subgroups() -> None:
    hh = _agent(
        cl_name="hh",
        agent_name="hh",
        start_time=datetime(2026, 4, 26, 12, 0, 0),
    )
    hi = _agent(
        cl_name="hi",
        agent_name="hi",
        start_time=datetime(2026, 4, 26, 8, 0, 0),
    )
    hk = _agent(
        cl_name="hk",
        agent_name="hk",
        start_time=datetime(2026, 4, 26, 11, 0, 0),
    )
    hk_followup = _agent(
        cl_name="hk-followup",
        agent_name="hk.f0",
        start_time=datetime(2026, 4, 26, 13, 0, 0),
    )
    agents = [hk_followup, hi, hk, hh]

    entries = build_agent_tree(agents, mode=GroupingMode.BY_STATUS, now=_NOW)

    assert _kinds(entries) == [
        ("group", 0),
        ("agent", 3),
        ("agent", 1),
        ("group", 1),
        ("agent", 0),
        ("agent", 2),
    ]
    assert _group_keys(entries, level=1) == [("Running", "hk")]


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

    # Standalone lanes remain above the visible family subgroup and stay
    # newest-first within that partition. The family's 09:00 root still anchors
    # the complete name group, and its established root/follow-up/child preorder
    # remains intact.
    assert [entry.agent_idx for entry in entries if entry.kind == "agent"] == [
        3,
        4,
        0,
        1,
        2,
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
