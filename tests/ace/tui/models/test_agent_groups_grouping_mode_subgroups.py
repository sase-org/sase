"""GroupingMode: BY_DATE L1 subgroup bucketing (1-hour / day / week)."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry
from sase.ace.tui.models.agent_groups import (
    NO_HOUR_LABEL,
    GroupingMode,
    build_agent_tree,
    date_subgroup_bucket_for,
    enumerate_group_keys,
)

from ._agent_groups_helpers import _NOW, _agent, _group_keys, _kinds


def test_date_subgroup_for_running_uses_start_time() -> None:
    a = _agent(status="RUNNING", start_time=datetime(2026, 4, 26, 9, 30, 0))
    assert date_subgroup_bucket_for(a, "Today") == "09:00"


def test_date_subgroup_for_terminal_uses_stop_time() -> None:
    a = _agent(
        status="DONE",
        start_time=datetime(2026, 4, 26, 7, 30, 0),
        stop_time=datetime(2026, 4, 26, 11, 45, 0),
    )
    assert date_subgroup_bucket_for(a, "Today") == "11:00"


def test_date_subgroup_for_terminal_no_stop_falls_back_to_start_time() -> None:
    a = _agent(
        status="DONE",
        start_time=datetime(2026, 4, 26, 7, 30, 0),
        stop_time=None,
    )
    assert date_subgroup_bucket_for(a, "Today") == "07:00"


def test_date_subgroup_for_no_anchor_returns_no_hour_label() -> None:
    a = _agent(start_time=None, stop_time=None)
    assert date_subgroup_bucket_for(a, "Earlier") == NO_HOUR_LABEL


def test_date_subgroup_this_week_uses_calendar_day() -> None:
    a = _agent(start_time=datetime(2026, 4, 24, 9, 0, 0))
    assert date_subgroup_bucket_for(a, "This Week") == "Fri Apr 24"


def test_date_subgroup_earlier_uses_monday_start_week() -> None:
    a = _agent(start_time=datetime(2026, 4, 23, 9, 0, 0))
    assert date_subgroup_bucket_for(a, "Earlier") == "Apr 20-26"


def test_build_agent_tree_today_uses_one_hour_subgroup() -> None:
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
    assert _group_keys(entries, 1) == [("Today", "09:00")]
    assert _group_keys(entries, 2) == []


def test_build_agent_tree_yesterday_uses_one_hour_subgroup() -> None:
    a = _agent(
        cl_name="x",
        agent_name="coder.aa",
        start_time=datetime(2026, 4, 25, 14, 15, 0),
    )
    b = _agent(
        cl_name="y",
        agent_name="coder.bb",
        start_time=datetime(2026, 4, 25, 14, 45, 0),
    )
    entries = build_agent_tree([a, b], mode=GroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 0) == [("Yesterday",)]
    assert _group_keys(entries, 1) == [("Yesterday", "14:00")]


def test_build_agent_tree_this_week_uses_calendar_day_subgroup() -> None:
    fri = _agent(
        cl_name="a",
        agent_name="x.a",
        start_time=datetime(2026, 4, 24, 9, 0, 0),
    )
    thu = _agent(
        cl_name="b",
        agent_name="y.b",
        start_time=datetime(2026, 4, 23, 9, 0, 0),
    )
    entries = build_agent_tree([fri, thu], mode=GroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 1) == [
        ("This Week", "Fri Apr 24"),
        ("This Week", "Thu Apr 23"),
    ]


def test_build_agent_tree_earlier_uses_monday_start_week_subgroup() -> None:
    a = _agent(
        cl_name="a",
        agent_name="x.a",
        start_time=datetime(2026, 4, 1, 9, 0, 0),
    )
    entries = build_agent_tree([a], mode=GroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 1) == [("Earlier", "Mar 30-Apr 5")]


def test_build_agent_tree_earlier_two_weeks_emits_two_l1_banners() -> None:
    """Earlier agents in distinct calendar weeks render as two L2 banners."""
    apr_15 = _agent(
        cl_name="a",
        agent_name="x.a",
        start_time=datetime(2026, 4, 15, 9, 0, 0),
    )
    apr_3 = _agent(
        cl_name="b",
        agent_name="y.b",
        start_time=datetime(2026, 4, 3, 9, 0, 0),
    )
    entries = build_agent_tree([apr_15, apr_3], mode=GroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 1) == [
        ("Earlier", "Apr 13-19"),
        ("Earlier", "Mar 30-Apr 5"),
    ]


def test_build_agent_tree_today_subgroups_newest_first() -> None:
    nine = _agent(
        cl_name="a", agent_name="x.a", start_time=datetime(2026, 4, 26, 9, 0, 0)
    )
    fourteen = _agent(
        cl_name="b", agent_name="y.b", start_time=datetime(2026, 4, 26, 14, 0, 0)
    )
    twenty = _agent(
        cl_name="c", agent_name="z.c", start_time=datetime(2026, 4, 26, 20, 0, 0)
    )
    entries = build_agent_tree(
        [nine, fourteen, twenty], mode=GroupingMode.BY_DATE, now=_NOW
    )
    assert _group_keys(entries, 1) == [
        ("Today", "20:00"),
        ("Today", "14:00"),
        ("Today", "09:00"),
    ]


def test_build_agent_tree_no_time_singleton_suppresses_banner() -> None:
    """Singleton ``(no time)`` keeps the existing suppression behavior."""
    no_time = _agent(cl_name="x", agent_name="solo", start_time=None)
    entries = build_agent_tree([no_time], mode=GroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 1) == []


def test_build_agent_tree_no_time_multi_agent_emits_banner() -> None:
    """Two ``(no time)`` agents in Earlier emit a synthetic banner."""
    a = _agent(cl_name="a", agent_name="x.a", start_time=None)
    b = _agent(cl_name="b", agent_name="y.b", start_time=None)
    entries = build_agent_tree([a, b], mode=GroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 1) == [("Earlier", NO_HOUR_LABEL)]


def test_build_agent_tree_today_singleton_real_subgroup_emits_banner() -> None:
    """Real subgroup labels always emit a banner, even for a singleton."""
    a = _agent(
        cl_name="x",
        agent_name="coder.aa",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    entries = build_agent_tree([a], mode=GroupingMode.BY_DATE, now=_NOW)
    assert _group_keys(entries, 1) == [("Today", "09:00")]
    assert _kinds(entries) == [("group", 0), ("group", 1), ("agent", 0)]


def test_build_agent_tree_no_time_sorts_last_within_earlier() -> None:
    has_time = _agent(
        cl_name="a", agent_name="x.a", start_time=datetime(2026, 4, 1, 8, 0, 0)
    )
    no_time = _agent(cl_name="b", agent_name="y.b", start_time=None)
    no_time2 = _agent(cl_name="c", agent_name="z.c", start_time=None)
    entries = build_agent_tree(
        [no_time, no_time2, has_time], mode=GroupingMode.BY_DATE, now=_NOW
    )
    assert _group_keys(entries, 1) == [
        ("Earlier", "Mar 30-Apr 5"),
        ("Earlier", NO_HOUR_LABEL),
    ]


def test_build_agent_tree_workflow_child_inherits_parent_subgroup() -> None:
    """Workflow children render under the parent's subgroup banner."""
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
    banner = next(
        e.group  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group"
        and e.group is not None
        and e.group.level == 1
        and e.group.group_key == ("Today", "09:00")
    )
    assert sorted(banner.agent_indices) == [0, 1, 2]


def test_build_agent_tree_collapsed_subgroup_hides_only_its_agents() -> None:
    a = _agent(
        cl_name="x",
        agent_name="coder.aa",
        start_time=datetime(2026, 4, 26, 9, 15, 0),
    )
    b = _agent(
        cl_name="y",
        agent_name="coder.bb",
        start_time=datetime(2026, 4, 26, 14, 30, 0),
    )
    registry = AgentGroupFoldRegistry()
    registry.collapse(("Today", "14:00"))
    entries = build_agent_tree(
        [a, b], fold_registry=registry, mode=GroupingMode.BY_DATE, now=_NOW
    )
    # Today (L0) banner, two L1 subgroup banners, and only the 09:00 agent.
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 1),
        ("agent", 0),
    ]


def test_enumerate_group_keys_includes_subgroup_keys() -> None:
    a = _agent(
        cl_name="x",
        agent_name="coder.aa",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    b = _agent(
        cl_name="y",
        agent_name="coder.bb",
        start_time=datetime(2026, 4, 23, 14, 0, 0),
    )
    keys = enumerate_group_keys([a, b], mode=GroupingMode.BY_DATE, now=_NOW)
    assert ("Today",) in keys
    assert ("Today", "09:00") in keys
    assert ("This Week",) in keys
    assert ("This Week", "Thu Apr 23") in keys


def test_build_agent_tree_terminal_and_running_share_subgroup() -> None:
    """A DONE agent's stop_time and a RUNNING agent's start_time agree."""
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
    assert _group_keys(entries, 1) == [("Today", "09:00")]
