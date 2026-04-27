"""GroupingMode: date / status bucketing and tree shape under non-STANDARD modes."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_groups import (
    GroupingMode,
    _date_bucket_for,
    _status_bucket_for,
    build_agent_tree,
    enumerate_group_keys,
)

from ._agent_groups_helpers import _NOW, _agent, _kinds

# --- GroupingMode: date bucketing ---


def test_date_bucket_today() -> None:
    a = _agent(start_time=datetime(2026, 4, 26, 9, 30, 0))
    assert _date_bucket_for(a, _NOW) == "Today"


def test_date_bucket_yesterday() -> None:
    a = _agent(start_time=datetime(2026, 4, 25, 15, 0, 0))
    assert _date_bucket_for(a, _NOW) == "Yesterday"


def test_date_bucket_yesterday_at_midnight_rollover() -> None:
    """An agent that ran at 23:59 the prior day still buckets as Yesterday."""
    a = _agent(start_time=datetime(2026, 4, 25, 23, 59, 59))
    just_after_midnight = datetime(2026, 4, 26, 0, 0, 1)
    assert _date_bucket_for(a, just_after_midnight) == "Yesterday"


def test_date_bucket_this_week_within_six_days() -> None:
    a = _agent(start_time=datetime(2026, 4, 22, 12, 0, 0))
    assert _date_bucket_for(a, _NOW) == "This Week"


def test_date_bucket_earlier_past_week() -> None:
    a = _agent(start_time=datetime(2026, 4, 18, 12, 0, 0))
    assert _date_bucket_for(a, _NOW) == "Earlier"


def test_date_bucket_missing_start_time_lands_in_earlier() -> None:
    a = _agent(start_time=None)
    assert _date_bucket_for(a, _NOW) == "Earlier"


def test_date_bucket_uses_local_calendar_date_not_24h_window() -> None:
    """A 23h-old start that crossed midnight is Yesterday, not Today."""
    a = _agent(start_time=datetime(2026, 4, 25, 13, 0, 0))
    now = datetime(2026, 4, 26, 12, 0, 0)
    assert _date_bucket_for(a, now) == "Yesterday"


# --- GroupingMode: status bucketing ---


def test_status_bucket_done() -> None:
    assert _status_bucket_for(_agent(status="DONE")) == "Done"


def test_status_bucket_running() -> None:
    assert _status_bucket_for(_agent(status="RUNNING")) == "Running"


def test_status_bucket_planning_is_needs_attention() -> None:
    """``PLANNING`` is an active drafting state where the user is on call."""
    assert _status_bucket_for(_agent(status="PLANNING")) == "Needs Attention"


def test_status_bucket_question_is_needs_attention() -> None:
    assert _status_bucket_for(_agent(status="QUESTION")) == "Needs Attention"


def test_status_bucket_plan_approved_is_running() -> None:
    """An approved plan is actively executing → Running."""
    assert _status_bucket_for(_agent(status="PLAN APPROVED")) == "Running"


def test_status_bucket_plan_done_is_done() -> None:
    """``PLAN DONE`` is a post-plan handoff state — planning work is finished."""
    assert _status_bucket_for(_agent(status="PLAN DONE")) == "Done"


def test_status_bucket_epic_created_is_done() -> None:
    """``EPIC CREATED`` is a post-plan handoff state — code work has been spun off."""
    assert _status_bucket_for(_agent(status="EPIC CREATED")) == "Done"


def test_status_bucket_waiting_without_wait_until_or_waiting_for_is_waiting() -> None:
    """All ``WAITING`` variants collapse into the ``Waiting`` bucket."""
    a = _agent(status="WAITING", wait_until=None)
    assert _status_bucket_for(a) == "Waiting"


def test_status_bucket_waiting_with_wait_until_is_waiting() -> None:
    """Timer-driven WAIT is blocked but progressing → Waiting, not Running."""
    a = _agent(status="WAITING", wait_until="2026-04-26T15:00:00")
    assert _status_bucket_for(a) == "Waiting"


def test_status_bucket_waiting_with_waiting_for_is_waiting() -> None:
    """Dependency-driven WAIT is blocked but not actionable → Waiting."""
    a = _agent(status="WAITING", wait_until=None, waiting_for=["other-agent"])
    assert _status_bucket_for(a) == "Waiting"


def test_status_bucket_failed_terminal_is_needs_attention() -> None:
    """A FAILED agent the user has not yet retried demands attention."""
    a = _agent(status="FAILED", retried_as_timestamp=None)
    assert _status_bucket_for(a) == "Needs Attention"


def test_status_bucket_failed_then_retried_is_failed() -> None:
    """FAILED with a forward retry pointer is handed-off, not actionable."""
    a = _agent(status="FAILED", retried_as_timestamp="ts-child")
    assert _status_bucket_for(a) == "Failed"


def test_status_bucket_failed_retried_status_string_is_failed() -> None:
    """``FAILED (RETRIED)`` is the display status of a handed-off failure."""
    a = _agent(status="FAILED (RETRIED)", retried_as_timestamp="ts-child")
    assert _status_bucket_for(a) == "Failed"


def test_status_bucket_unknown_status_falls_through_to_running() -> None:
    """Unrecognized states default to Running rather than disappearing."""
    a = _agent(status="WHATEVER")
    assert _status_bucket_for(a) == "Running"


def test_status_bucket_empty_status_is_running() -> None:
    a = _agent(status="")
    assert _status_bucket_for(a) == "Running"


# --- GroupingMode: tree shape ---


def test_build_agent_tree_default_mode_matches_standard() -> None:
    """Omitting the (Phase 2/3-bound) mode preserves existing behavior."""
    a = _agent(cl_name="demo", agent_name="coder.claude")
    b = _agent(cl_name="demo", agent_name="coder.codex")
    # Both produce the existing project / changespec / name-root tree.
    entries = build_agent_tree([a, b])
    assert _kinds(entries) == [
        ("group", 0),
        ("group", 1),
        ("group", 2),
        ("agent", 0),
        ("agent", 1),
    ]


def test_grouping_keys_for_agents_by_date_uses_bucket_at_l0() -> None:
    """Grouping keys under BY_DATE store the bucket as the L0 string."""
    from sase.ace.tui.models.agent_groups import _grouping_keys_for_agents

    today = _agent(start_time=datetime(2026, 4, 26, 9, 0, 0))
    earlier = _agent(start_time=datetime(2026, 4, 1, 9, 0, 0))
    keys = _grouping_keys_for_agents([today, earlier], GroupingMode.BY_DATE, _NOW)
    assert [k.project for k in keys] == ["Today", "Earlier"]
    # ChangeSpec is dropped in non-STANDARD modes.
    assert all(k.changespec == "" for k in keys)


def test_grouping_keys_for_agents_by_status_uses_bucket_at_l0() -> None:
    from sase.ace.tui.models.agent_groups import _grouping_keys_for_agents

    needs = _agent(status="QUESTION")
    running = _agent(status="RUNNING")
    keys = _grouping_keys_for_agents([needs, running], GroupingMode.BY_STATUS, _NOW)
    assert [k.project for k in keys] == ["Needs Attention", "Running"]
    assert all(k.changespec == "" for k in keys)


def test_panel_uses_changespec_level_skipped_in_non_standard_modes() -> None:
    """BY_DATE / BY_STATUS never use the ChangeSpec layer, even when present."""
    from sase.ace.tui.models.agent_groups import _panel_uses_changespec_level

    agents = [_agent(cl_name="demo")]
    assert _panel_uses_changespec_level(agents, GroupingMode.STANDARD) is True
    assert _panel_uses_changespec_level(agents, GroupingMode.BY_DATE) is False
    assert _panel_uses_changespec_level(agents, GroupingMode.BY_STATUS) is False


def test_panel_uses_changespec_level_ignores_project_scoped_agents() -> None:
    from sase.ace.tui.models.agent_groups import _panel_uses_changespec_level

    agents = [_agent(cl_name="sase", project_file="/r/sase/sase.gp")]
    assert _panel_uses_changespec_level(agents, GroupingMode.STANDARD) is False


def test_grouping_keys_for_agents_workflow_child_inherits_bucket() -> None:
    """Workflow children inherit their parent's bucket regardless of mode."""
    from sase.ace.tui.models.agent_groups import _grouping_keys_for_agents

    parent = _agent(
        cl_name="demo",
        agent_name="coder.claude",
        raw_suffix="ts1",
        status="DONE",
    )
    child = _agent(
        cl_name="step",
        agent_name="step.bash",
        parent_workflow="coder",
        parent_timestamp="ts1",
        status="RUNNING",
    )
    keys = _grouping_keys_for_agents([parent, child], GroupingMode.BY_STATUS, _NOW)
    # Both report the parent's bucket ("Done"), even though the child's
    # own status is "RUNNING".
    assert keys[0].project == "Done"
    assert keys[1].project == "Done"


# --- GroupingMode: build_agent_tree shape ---


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
    Needs Attention → Running → Waiting → Failed → Done.
    """
    needs = _agent(cl_name="a", agent_name="x.a", status="QUESTION")
    running = _agent(cl_name="b", agent_name="y.a", status="RUNNING")
    waiting = _agent(
        cl_name="e",
        agent_name="v.a",
        status="WAITING",
        wait_until="2026-04-26T15:00:00",
    )
    failed = _agent(
        cl_name="c", agent_name="z.a", status="FAILED", retried_as_timestamp="ts"
    )
    done = _agent(cl_name="d", agent_name="w.a", status="DONE")
    # Feed them in scrambled order to verify the sort is intrinsic.
    entries = build_agent_tree(
        [done, failed, needs, waiting, running],
        mode=GroupingMode.BY_STATUS,
        now=_NOW,
    )
    l0_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 0
    ]
    assert l0_banners == [
        ("Needs Attention",),
        ("Running",),
        ("Waiting",),
        ("Failed",),
        ("Done",),
    ]


def test_build_agent_tree_by_date_drops_changespec_and_project_levels() -> None:
    """Two agents in the same date bucket from different projects share an L0."""
    a = _agent(
        cl_name="cl-a",
        project_file="/r/projA/proj.gp",
        agent_name="solo",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    b = _agent(
        cl_name="cl-b",
        project_file="/r/projB/proj.gp",
        agent_name="solo",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
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
    # No L1 ChangeSpec banner is emitted.
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == []


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


def test_build_agent_tree_by_date_emits_no_name_root_banner() -> None:
    """Under BY_DATE the L1 name-root banner is suppressed entirely.

    Within a date bucket, same-base-name agents are not a meaningful unit
    — the bucket renders as a flat list sorted by ``start_time``.
    """
    a = _agent(
        cl_name="x",
        agent_name="coder.claude",
        start_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    b = _agent(
        cl_name="y",
        agent_name="coder.codex",
        start_time=datetime(2026, 4, 26, 10, 0, 0),
    )
    entries = build_agent_tree([a, b], mode=GroupingMode.BY_DATE, now=_NOW)
    l1_banners = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert l1_banners == []


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
    # No name-root sub-banner under BY_DATE — the bucket renders flat.
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
        start_time=datetime(2026, 4, 26, 10, 0, 0),
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
    assert l1_banners == []


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
