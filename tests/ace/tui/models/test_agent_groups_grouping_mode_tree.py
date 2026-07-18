"""GroupingMode: ``build_agent_tree`` shape under non-STANDARD modes."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent_groups import (
    GroupingMode,
    build_agent_tree,
    enumerate_group_keys,
)

from ._agent_groups_helpers import _NOW, _agent, _group_keys, _kinds


def test_build_agent_tree_by_date_buckets_at_l0() -> None:
    """BY_DATE replaces project banners with date-bucket banners."""
    today = _agent(
        cl_name="a",
        agent_name="coder.claude",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    yesterday = _agent(
        cl_name="b",
        agent_name="coder.codex",
        start_time=datetime(2026, 4, 25, 9, 0, 0),
    )
    earlier = _agent(
        cl_name="c",
        agent_name="solo",
        start_time=datetime(2026, 4, 1, 9, 0, 0),
    )
    entries = build_agent_tree(
        [today, yesterday, earlier], mode=GroupingMode.BY_DATE, now=_NOW
    )
    l0_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 0
    ]
    # Three distinct date buckets, each rendered exactly once, in fixed
    # newest-first order. "This Week" is absent — no agent fell into it.
    assert l0_banners == [("Today",), ("Yesterday",), ("Earlier",)]


def test_build_agent_tree_by_date_orders_buckets_newest_first_regardless_of_input() -> (
    None
):
    earlier = _agent(
        cl_name="c", agent_name="x", start_time=datetime(2026, 4, 1, 9, 0, 0)
    )
    today = _agent(
        cl_name="a", agent_name="y", start_time=datetime(2026, 4, 26, 9, 0, 0)
    )
    entries = build_agent_tree([earlier, today], mode=GroupingMode.BY_DATE, now=_NOW)
    l0_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 0
    ]
    assert l0_banners == [("Today",), ("Earlier",)]


def test_build_agent_tree_by_status_orders_buckets_priority_first() -> None:
    """BY_STATUS bucket order is fixed at
    Running → Done → Waiting → Stopped → Failed → Starting.
    """
    needs = _agent(cl_name="a", agent_name="x.a", status="QUESTION")
    running = _agent(cl_name="b", agent_name="y.a", status="RUNNING")
    waiting = _agent(
        cl_name="e",
        agent_name="v.a",
        status="WAITING",
        wait_until="2026-04-26T15:00:00",
    )
    failed = _agent(cl_name="c", agent_name="z.a", status="FAILED")
    done = _agent(cl_name="d", agent_name="w.a", status="DONE")
    starting = _agent(cl_name="f", agent_name="u.a", status="STARTING")
    # Feed them in scrambled order to verify the sort is intrinsic.
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
        ("Running",),
        ("Done",),
        ("Waiting",),
        ("Stopped",),
        ("Failed",),
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


def test_build_agent_tree_by_date_drops_changespec_and_project_levels() -> None:
    """Two agents in the same date bucket from different projects share an L0."""
    a = _agent(
        cl_name="cl-a",
        project_file="/r/projA/proj.sase",
        agent_name="solo",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    b = _agent(
        cl_name="cl-b",
        project_file="/r/projB/proj.sase",
        agent_name="solo",
        start_time=datetime(2026, 4, 26, 13, 0, 0),
    )
    entries = build_agent_tree([a, b], mode=GroupingMode.BY_DATE, now=_NOW)
    l0_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 0
    ]
    # Single "Today" banner — project / changespec are no longer in the
    # hierarchy, so two different projects collapse into one L0 group.
    assert l0_banners == [("Today",)]
    # L1 is the date-aware subgroup layer under BY_DATE; no project or
    # ChangeSpec identity is retained in those keys.
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == [("Today", "13:00"), ("Today", "09:00")]
    assert all("cl-" not in key for banner in l1_banners for key in banner)
    assert all("proj" not in key for banner in l1_banners for key in banner)


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


def test_build_agent_tree_by_date_emits_no_name_root_banner() -> None:
    """Under BY_DATE the name-root banner is suppressed entirely.

    Within a date bucket, same-base-name agents are not a meaningful unit
    — the bucket renders with subgroup banners sorted by ``start_time``.
    """
    a = _agent(
        cl_name="x",
        agent_name="coder.claude",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    b = _agent(
        cl_name="y",
        agent_name="coder.codex",
        start_time=datetime(2026, 4, 26, 13, 0, 0),
    )
    entries = build_agent_tree([a, b], mode=GroupingMode.BY_DATE, now=_NOW)
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == [("Today", "13:00"), ("Today", "09:00")]
    assert ("Today", "coder") not in l1_banners


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


def test_enumerate_group_keys_respects_grouping_mode() -> None:
    """Enumerating keys under BY_DATE returns date-bucket L0 keys, not project keys."""
    a = _agent(
        cl_name="a",
        agent_name="coder.claude",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    b = _agent(
        cl_name="b",
        agent_name="coder.codex",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    keys = enumerate_group_keys([a, b], mode=GroupingMode.BY_DATE, now=_NOW)
    assert ("Today",) in keys
    # No name-root sub-banner under BY_DATE.
    assert ("Today", "coder") not in keys
    # The STANDARD-mode (project,) key shape is absent under BY_DATE.
    assert ("repo",) not in keys


def test_build_agent_tree_by_date_sorts_agents_newest_first_within_bucket() -> None:
    """Within a date bucket, agents render newest-first by ``start_time``."""
    foo = _agent(
        cl_name="x",
        agent_name="coder.foo",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    bar = _agent(
        cl_name="y",
        agent_name="coder.bar",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    solo = _agent(
        cl_name="z",
        agent_name="solo",
        start_time=datetime(2026, 4, 26, 8, 0, 0),
    )
    entries = build_agent_tree([foo, bar, solo], mode=GroupingMode.BY_DATE, now=_NOW)
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    # Newest first: bar (10:00) → foo (09:00) → solo (08:00).
    assert agent_order == [1, 0, 2]


def test_build_agent_tree_by_date_workflow_child_stays_adjacent_to_parent() -> None:
    """A workflow child renders immediately after its parent regardless of own start."""
    parent = _agent(
        cl_name="x",
        agent_name="coder.foo",
        raw_suffix="ts-parent",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    child = _agent(
        cl_name="x",
        agent_name="step.bash",
        parent_workflow="coder",
        parent_timestamp="ts-parent",
        start_time=datetime(2026, 4, 26, 12, 0, 0),
    )
    other = _agent(
        cl_name="y",
        agent_name="coder.bar",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    entries = build_agent_tree(
        [parent, child, other], mode=GroupingMode.BY_DATE, now=_NOW
    )
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    # The child's own 12:00 start would put it ahead of everyone, but it
    # inherits the parent's 09:00 anchor and the child-after-parent flag,
    # so the order is: other (10:00) → parent (09:00) → child.
    assert agent_order == [2, 0, 1]


def test_build_agent_tree_by_date_no_name_root_banner_across_buckets() -> None:
    """Same base name appearing in two buckets emits no name-root banner anywhere."""
    today_a = _agent(
        cl_name="x",
        agent_name="coder.foo",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    today_b = _agent(
        cl_name="y",
        agent_name="coder.bar",
        start_time=datetime(2026, 4, 26, 13, 0, 0),
    )
    earlier_a = _agent(
        cl_name="z",
        agent_name="coder.qux",
        start_time=datetime(2026, 4, 1, 9, 0, 0),
    )
    entries = build_agent_tree(
        [today_a, today_b, earlier_a], mode=GroupingMode.BY_DATE, now=_NOW
    )
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == [
        ("Today", "13:00"),
        ("Today", "09:00"),
        ("Earlier", "Mar 30-Apr 5"),
    ]
    assert all(banner[-1] != "coder" for banner in l1_banners)


def test_build_agent_tree_by_date_done_agents_sort_by_stop_time() -> None:
    """Within a bucket, terminal agents sort by ``stop_time``, newest-first.

    A starts earlier but stops later; B starts later but stops earlier.
    The Done segment should order A → B (newest completion first), even
    though by ``start_time`` it would be B → A.
    """
    a = _agent(
        cl_name="x",
        agent_name="coder.bb",
        status="DONE",
        start_time=datetime(2026, 4, 26, 8, 0, 0),
        stop_time=datetime(2026, 4, 26, 11, 0, 0),
    )
    b = _agent(
        cl_name="y",
        agent_name="coder.bc",
        status="DONE",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
        stop_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    entries = build_agent_tree([a, b], mode=GroupingMode.BY_DATE, now=_NOW)
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    assert agent_order == [0, 1]


def test_build_agent_tree_by_date_mixed_running_and_done_uses_each_anchor() -> None:
    """Running agents anchor on ``start_time``; done agents anchor on ``stop_time``.

    Running's start_time is 09:00; Done's stop_time is 11:00, so Done sorts
    first (newest by its own anchor) even though its start_time (07:00) is
    older than the running agent's start.
    """
    running = _agent(
        cl_name="x",
        agent_name="coder.run",
        status="RUNNING",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    done = _agent(
        cl_name="y",
        agent_name="coder.done",
        status="DONE",
        start_time=datetime(2026, 4, 26, 7, 0, 0),
        stop_time=datetime(2026, 4, 26, 11, 0, 0),
    )
    entries = build_agent_tree([running, done], mode=GroupingMode.BY_DATE, now=_NOW)
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    # done.stop_time (11:00) is newer than running.start_time (09:00),
    # so done sorts first.
    assert agent_order == [1, 0]


def test_build_agent_tree_by_date_done_without_stop_time_falls_back_to_start_time() -> (
    None
):
    """A DONE agent missing ``stop_time`` still sorts (by ``start_time``)."""
    no_stop = _agent(
        cl_name="x",
        agent_name="coder.foo",
        status="DONE",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
        stop_time=None,
    )
    has_stop = _agent(
        cl_name="y",
        agent_name="coder.bar",
        status="DONE",
        start_time=datetime(2026, 4, 26, 8, 0, 0),
        stop_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    entries = build_agent_tree([no_stop, has_stop], mode=GroupingMode.BY_DATE, now=_NOW)
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    # has_stop's stop_time (10:00) > no_stop's start_time fallback (09:00).
    assert agent_order == [1, 0]


def test_build_agent_tree_by_date_workflow_child_inherits_parents_stop_time() -> None:
    """A workflow child of a DONE parent anchors on the parent's ``stop_time``.

    The child still renders immediately after its parent (the
    ``is_child`` invariant), and the parent/child cluster sorts by
    ``stop_time`` against other agents in the bucket.
    """
    parent = _agent(
        cl_name="x",
        agent_name="coder.parent",
        raw_suffix="ts-parent",
        status="DONE",
        start_time=datetime(2026, 4, 26, 7, 0, 0),
        stop_time=datetime(2026, 4, 26, 11, 0, 0),
    )
    child = _agent(
        cl_name="x",
        agent_name="step.bash",
        parent_workflow="coder",
        parent_timestamp="ts-parent",
        status="RUNNING",
        start_time=datetime(2026, 4, 26, 8, 0, 0),
    )
    other = _agent(
        cl_name="y",
        agent_name="coder.other",
        status="RUNNING",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    entries = build_agent_tree(
        [parent, child, other], mode=GroupingMode.BY_DATE, now=_NOW
    )
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    # Parent's stop_time (11:00) outranks other's start_time (10:00),
    # and child stays glued to the parent.
    assert agent_order == [0, 1, 2]


def test_build_agent_tree_by_date_none_start_time_sorts_last_within_bucket() -> None:
    """Agents with no ``start_time`` sort after start-time-bearing peers."""
    has_start = _agent(
        cl_name="x",
        agent_name="solo",
        start_time=datetime(2026, 4, 1, 9, 0, 0),
    )
    no_start = _agent(cl_name="y", agent_name="solo2", start_time=None)
    entries = build_agent_tree(
        [no_start, has_start], mode=GroupingMode.BY_DATE, now=_NOW
    )
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    # Both bucket as "Earlier"; the dated agent comes first.
    assert agent_order == [1, 0]
