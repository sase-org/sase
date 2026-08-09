"""GroupingMode: BY_DATE ``build_agent_tree`` shape and ordering."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_groups import (
    GroupingMode,
    build_agent_tree,
    enumerate_group_keys,
)

from ._agent_groups_helpers import _NOW, _agent, _group_keys


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


def test_build_agent_tree_by_date_overnight_done_agent_buckets_with_its_subgroup() -> (
    None
):
    overnight = _agent(
        cl_name="x",
        agent_name="coder.overnight",
        status="DONE",
        start_time=datetime(2026, 4, 24, 18, 9, 0),
        stop_time=datetime(2026, 4, 25, 10, 56, 0),
    )
    same_day = _agent(
        cl_name="y",
        agent_name="coder.same-day",
        status="DONE",
        start_time=datetime(2026, 4, 25, 20, 0, 0),
        stop_time=datetime(2026, 4, 25, 21, 35, 0),
    )
    entries = build_agent_tree(
        [overnight, same_day], mode=GroupingMode.BY_DATE, now=_NOW
    )

    assert _group_keys(entries, level=0) == [("Yesterday",)]
    assert _group_keys(entries, level=1) == [
        ("Yesterday", "21:00"),
        ("Yesterday", "10:00"),
    ]
    assert ("This Week", "Sat Apr 25") not in _group_keys(entries, level=1)


def test_build_agent_tree_by_date_drops_patch_and_project_levels() -> None:
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
    # Single "Today" banner — project / patch are no longer in the
    # hierarchy, so two different projects collapse into one L0 group.
    assert l0_banners == [("Today",)]
    # L1 is the date-aware subgroup layer under BY_DATE; no project or
    # Patch identity is retained in those keys.
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == [("Today", "13:00"), ("Today", "09:00")]
    assert all("cl-" not in key for banner in l1_banners for key in banner)
    assert all("proj" not in key for banner in l1_banners for key in banner)


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
