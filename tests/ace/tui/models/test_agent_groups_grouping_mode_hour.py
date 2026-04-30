"""GroupingMode: hour bucketing under BY_DATE."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_groups import (
    NO_HOUR_LABEL,
    GroupingMode,
    build_agent_tree,
    enumerate_group_keys,
    hour_bucket_for,
)

from ._agent_groups_helpers import _NOW, _agent


def test_hour_bucket_for_running_uses_start_time() -> None:
    a = _agent(status="RUNNING", start_time=datetime(2026, 4, 26, 9, 30, 0))
    assert hour_bucket_for(a) == "09:00"


def test_hour_bucket_for_terminal_uses_stop_time() -> None:
    a = _agent(
        status="DONE",
        start_time=datetime(2026, 4, 26, 7, 30, 0),
        stop_time=datetime(2026, 4, 26, 11, 45, 0),
    )
    assert hour_bucket_for(a) == "11:00"


def test_hour_bucket_for_terminal_no_stop_falls_back_to_start_time() -> None:
    a = _agent(
        status="DONE",
        start_time=datetime(2026, 4, 26, 7, 30, 0),
        stop_time=None,
    )
    assert hour_bucket_for(a) == "07:00"


def test_hour_bucket_for_no_anchor_returns_no_time_label() -> None:
    a = _agent(start_time=None, stop_time=None)
    assert hour_bucket_for(a) == NO_HOUR_LABEL


def test_build_agent_tree_by_date_emits_hour_banner_under_date_bucket() -> None:
    """Two same-hour agents in Today get a ("Today", "09:00") L1 banner."""
    a = _agent(
        cl_name="x",
        agent_name="coder.aa",
        start_time=datetime(2026, 4, 26, 9, 15, 0),
    )
    b = _agent(
        cl_name="y",
        agent_name="coder.bb",
        start_time=datetime(2026, 4, 26, 9, 45, 0),
    )
    entries = build_agent_tree([a, b], mode=GroupingMode.BY_DATE, now=_NOW)
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == [("Today", "09:00")]


def test_build_agent_tree_by_date_singleton_real_hours_emit_banners() -> None:
    """Agents at distinct real hours each get an L1 hour banner."""
    a = _agent(
        cl_name="x",
        agent_name="coder.aa",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    b = _agent(
        cl_name="y",
        agent_name="coder.bb",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    entries = build_agent_tree([a, b], mode=GroupingMode.BY_DATE, now=_NOW)
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == [("Today", "10:00"), ("Today", "09:00")]


def test_build_agent_tree_by_date_hour_buckets_newest_first() -> None:
    """Hour banners within a date bucket sort newest hour first."""
    eight_a = _agent(
        cl_name="a", agent_name="x.a", start_time=datetime(2026, 4, 26, 8, 0, 0)
    )
    eight_b = _agent(
        cl_name="b", agent_name="x.b", start_time=datetime(2026, 4, 26, 8, 30, 0)
    )
    fourteen_a = _agent(
        cl_name="c", agent_name="y.a", start_time=datetime(2026, 4, 26, 14, 0, 0)
    )
    fourteen_b = _agent(
        cl_name="d", agent_name="y.b", start_time=datetime(2026, 4, 26, 14, 30, 0)
    )
    nine_a = _agent(
        cl_name="e", agent_name="z.a", start_time=datetime(2026, 4, 26, 9, 0, 0)
    )
    nine_b = _agent(
        cl_name="f", agent_name="z.b", start_time=datetime(2026, 4, 26, 9, 30, 0)
    )
    entries = build_agent_tree(
        [eight_a, eight_b, fourteen_a, fourteen_b, nine_a, nine_b],
        mode=GroupingMode.BY_DATE,
        now=_NOW,
    )
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == [
        ("Today", "14:00"),
        ("Today", "09:00"),
        ("Today", "08:00"),
    ]


def test_build_agent_tree_by_date_no_time_hour_sorts_last() -> None:
    """``(no time)`` hour bucket sorts after all numeric hour buckets."""
    eight_a = _agent(
        cl_name="a",
        agent_name="x.a",
        start_time=datetime(2026, 4, 1, 8, 0, 0),
    )
    eight_b = _agent(
        cl_name="b",
        agent_name="x.b",
        start_time=datetime(2026, 4, 1, 8, 30, 0),
    )
    no_time_a = _agent(cl_name="c", agent_name="y.a", start_time=None)
    no_time_b = _agent(cl_name="d", agent_name="y.b", start_time=None)
    entries = build_agent_tree(
        [no_time_a, no_time_b, eight_a, eight_b],
        mode=GroupingMode.BY_DATE,
        now=_NOW,
    )
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == [
        ("Earlier", "08:00"),
        ("Earlier", NO_HOUR_LABEL),
    ]


def test_build_agent_tree_by_date_singleton_no_time_has_no_hour_banner() -> None:
    """A singleton ``(no time)`` bucket keeps the old suppression behavior."""
    no_time = _agent(cl_name="x", agent_name="solo", start_time=None)
    entries = build_agent_tree([no_time], mode=GroupingMode.BY_DATE, now=_NOW)
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == []


def test_build_agent_tree_by_date_workflow_child_inherits_parents_hour() -> None:
    """A workflow child renders under its parent's hour banner.

    The child's own ``start_time`` is in a different hour, but it
    inherits the parent's hour for grouping just like every other level.
    """
    parent_a = _agent(
        cl_name="x",
        agent_name="coder.parent",
        raw_suffix="ts-parent",
        start_time=datetime(2026, 4, 26, 9, 15, 0),
    )
    child = _agent(
        cl_name="x",
        agent_name="step.bash",
        parent_workflow="coder",
        parent_timestamp="ts-parent",
        start_time=datetime(2026, 4, 26, 14, 0, 0),
    )
    sibling = _agent(
        cl_name="y",
        agent_name="coder.sib",
        start_time=datetime(2026, 4, 26, 9, 45, 0),
    )
    entries = build_agent_tree(
        [parent_a, child, sibling], mode=GroupingMode.BY_DATE, now=_NOW
    )
    # Find the 09:00 banner; it must reference all three agent indices
    # (parent, child, sibling) — child does not become its own bucket.
    hour_banner = next(
        e.group  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group"
        and e.group is not None
        and e.group.level == 1
        and e.group.group_key == ("Today", "09:00")
    )
    assert sorted(hour_banner.agent_indices) == [0, 1, 2]


def test_build_agent_tree_by_date_terminal_and_running_share_hour() -> None:
    """A DONE agent's stop_time and a RUNNING agent's start_time agree.

    DONE with stop_time=09:30 and RUNNING with start_time=09:15 cluster
    under a single ``09:00`` banner — the hour-anchor rule mirrors the
    sort rule.
    """
    done = _agent(
        cl_name="x",
        agent_name="coder.done",
        status="DONE",
        start_time=datetime(2026, 4, 26, 7, 0, 0),
        stop_time=datetime(2026, 4, 26, 9, 30, 0),
    )
    running = _agent(
        cl_name="y",
        agent_name="coder.run",
        status="RUNNING",
        start_time=datetime(2026, 4, 26, 9, 15, 0),
    )
    entries = build_agent_tree([done, running], mode=GroupingMode.BY_DATE, now=_NOW)
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == [("Today", "09:00")]


def test_enumerate_group_keys_by_date_includes_hour_keys() -> None:
    """``enumerate_group_keys`` lists visible hour groups under BY_DATE."""
    a = _agent(
        cl_name="x",
        agent_name="coder.aa",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    b = _agent(
        cl_name="y",
        agent_name="coder.bb",
        start_time=datetime(2026, 4, 26, 9, 30, 0),
    )
    solo = _agent(
        cl_name="z",
        agent_name="solo",
        start_time=datetime(2026, 4, 26, 14, 0, 0),
    )
    keys = enumerate_group_keys([a, b, solo], mode=GroupingMode.BY_DATE, now=_NOW)
    assert ("Today", "09:00") in keys
    assert ("Today", "14:00") in keys
