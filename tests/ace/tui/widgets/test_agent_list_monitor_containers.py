"""Family and clan container monitor-badge tests."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models._agent_clan import (
    ClanStatusCounts as ParallelFamilyStatusCounts,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_family_members import (
    is_sequential_family_container,
    shell_lane_counts,
)
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.ace.tui.widgets._agent_list_styling import (
    _GATE_COUNT_GLYPH_STYLE,
    _GATE_FAILED_COUNT_GLYPH_STYLE,
    _GATE_SETTLED_COUNT_GLYPH_STYLE,
    _MONITOR_COUNT_GLYPH_STYLE,
    _MONITOR_SETTLED_COUNT_GLYPH_STYLE,
)

from ._agent_list_monitor_rows_helpers import make_family_container, style_at


def _monitor_lane_counts(agent: Agent):
    return shell_lane_counts(agent).monitor


def _gate_lane_counts(agent: Agent):
    return shell_lane_counts(agent).gate


def test_family_container_with_running_monitor_renders_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_family_container("running"),
        0,
        is_selected=False,
    )

    assert "⚙1" in left.plain


def test_family_container_with_only_settled_monitors_renders_grey_badge_only() -> None:
    left, _suffix, _option_id = format_agent_option(
        make_family_container("completed"),
        0,
        is_selected=False,
    )

    assert "⚙1" in left.plain
    glyph_index = left.plain.index("⚙1")
    assert style_at(left, glyph_index) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE


def test_family_container_with_running_and_settled_monitors_renders_both_badges() -> (
    None
):
    left, _suffix, _option_id = format_agent_option(
        make_family_container("running", "completed", "stopped", "failed"),
        0,
        is_selected=False,
    )

    assert "⚙1 ⚙3" in left.plain
    running_index = left.plain.index("⚙1")
    settled_index = left.plain.index("⚙3")
    assert style_at(left, running_index) == _MONITOR_COUNT_GLYPH_STYLE
    assert style_at(left, settled_index) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE


def test_non_container_row_never_renders_monitor_badge() -> None:
    started = datetime(2026, 8, 12, 9, 0, 0)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha--0",
        project_file="/tmp/monitor.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="20260812090000",
        agent_name="alpha--0",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
        # A parallel-family root is never a sequential-family container, even
        # with running-monitor children, so this isolates the container
        # check itself from ``_monitor_lane_counts`` returning a nonzero lane.
        agent_family_parallel=True,
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-mon",
        project_file="/tmp/monitor.sase",
        status="MONITORING",
        start_time=started,
        raw_suffix="20260812090001",
        parent_timestamp="20260812090000",
        agent_name="alpha--mon",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m1",
        monitor_state="running",
        monitor_label="just check",
    )
    agent.followup_agents = [monitor]
    assert _monitor_lane_counts(agent).running == 1

    left, _suffix, _option_id = format_agent_option(agent, 0, is_selected=False)

    assert "⚙" not in left.plain


def test_family_container_badge_does_not_alter_status_chip() -> None:
    counts = ParallelFamilyStatusCounts(running=2, awaiting=1)
    container = make_family_container("running", "completed")
    container.is_clan_container = True
    container.agent_clan = "alpha"
    container.agent_clan_generation = "gen"

    left, _suffix, _option_id = format_agent_option(
        container,
        0,
        is_selected=False,
        clan_counts=counts,
    )

    assert "[S1 R2]" in left.plain
    assert "⚙1 ⚙1" in left.plain


def test_starter_with_only_monitor_child_renders_no_count_badge() -> None:
    started = datetime(2026, 8, 12, 9, 0, 0)
    starter = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha--2",
        project_file="/tmp/monitor.sase",
        status="TALE DONE",
        start_time=started,
        stop_time=started,
        raw_suffix="20260812090000",
        parent_timestamp="20260812085900",
        agent_name="alpha--2",
        agent_family="alpha",
        agent_family_role="code",
        role_suffix="--2",
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha--mon-1",
        project_file="/tmp/monitor.sase",
        status="MONITORING",
        start_time=started,
        raw_suffix="20260812090001",
        parent_timestamp=starter.raw_suffix,
        agent_name="alpha--mon-1",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon-1",
        monitor_id="m1",
        monitor_state="running",
        monitor_label="just check",
    )
    starter.runtime_children = [monitor]
    starter.followup_agents = [monitor]
    assert _monitor_lane_counts(starter).running == 1
    assert is_sequential_family_container(starter) is False

    left, _suffix, _option_id = format_agent_option(starter, 0, is_selected=False)

    assert "⚙1" not in left.plain
    assert "⚙" not in left.plain


def test_clan_container_with_nested_running_monitor_renders_badge() -> None:
    started = datetime(2026, 8, 12, 9, 0, 0)
    clan = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="workers",
        project_file="/tmp/monitor.sase",
        status="RUNNING",
        start_time=started,
        is_clan_container=True,
        agent_clan="workers",
        agent_clan_generation="gen",
    )
    family = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha",
        project_file="/tmp/monitor.sase",
        status="TALE DONE",
        start_time=started,
        raw_suffix="20260812085900",
        agent_name="alpha",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
    )
    starter = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha--2",
        project_file="/tmp/monitor.sase",
        status="TALE DONE",
        start_time=started,
        raw_suffix="20260812090000",
        parent_timestamp=family.raw_suffix,
        agent_name="alpha--2",
        agent_family="alpha",
        agent_family_role="code",
        role_suffix="--2",
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha--mon-1",
        project_file="/tmp/monitor.sase",
        status="MONITORING",
        start_time=started,
        raw_suffix="20260812090001",
        parent_timestamp=starter.raw_suffix,
        agent_name="alpha--mon-1",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon-1",
        monitor_id="m1",
        monitor_state="running",
        monitor_label="just check",
    )
    starter.runtime_children = [monitor]
    family.runtime_children = [starter]
    family.followup_agents = [starter]
    clan.runtime_children = [family]

    left, _suffix, _option_id = format_agent_option(clan, 0, is_selected=False)

    assert "⚙1" in left.plain


def test_clan_container_aggregates_settled_lane_across_member_families() -> None:
    started = datetime(2026, 8, 12, 9, 0, 0)
    clan = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="workers",
        project_file="/tmp/monitor.sase",
        status="RUNNING",
        start_time=started,
        is_clan_container=True,
        agent_clan="workers",
        agent_clan_generation="gen",
    )

    def _settled_family(name: str) -> Agent:
        family = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=name,
            project_file="/tmp/monitor.sase",
            status="TALE DONE",
            start_time=started,
            raw_suffix=f"{name}-root",
            agent_name=name,
            agent_family=name,
            agent_family_role="root",
            role_suffix="--0",
        )
        monitor = Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"{name}--mon",
            project_file="/tmp/monitor.sase",
            status="MONITORED",
            start_time=started,
            stop_time=started + timedelta(minutes=3),
            raw_suffix=f"{name}-mon",
            parent_timestamp=family.raw_suffix,
            agent_name=f"{name}--mon",
            agent_family=name,
            agent_family_role="monitor",
            role_suffix="--mon",
            monitor_id=f"{name}-m1",
            monitor_state="completed",
            monitor_label="just check",
        )
        family.followup_agents = [monitor]
        return family

    clan.runtime_children = [_settled_family("alpha"), _settled_family("beta")]

    left, _suffix, _option_id = format_agent_option(clan, 0, is_selected=False)

    assert "⚙2" in left.plain
    glyph_index = left.plain.index("⚙2")
    assert style_at(left, glyph_index) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE


def test_non_container_row_with_settled_monitors_renders_no_badge() -> None:
    started = datetime(2026, 8, 12, 9, 0, 0)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha--0",
        project_file="/tmp/monitor.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="20260812090000",
        agent_name="alpha--0",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
        # A parallel-family root is never a sequential-family container, even
        # with settled-monitor children, so this isolates the container
        # check itself from ``_monitor_lane_counts`` returning a nonzero lane.
        agent_family_parallel=True,
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-mon",
        project_file="/tmp/monitor.sase",
        status="MONITORED",
        start_time=started,
        stop_time=started + timedelta(minutes=3),
        raw_suffix="20260812090001",
        parent_timestamp="20260812090000",
        agent_name="alpha--mon",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m1",
        monitor_state="completed",
        monitor_label="just check",
    )
    agent.followup_agents = [monitor]
    lanes = _monitor_lane_counts(agent)
    assert lanes.running == 0
    assert lanes.settled == 1

    left, _suffix, _option_id = format_agent_option(agent, 0, is_selected=False)

    assert "⚙" not in left.plain


def test_family_container_with_gate_lanes_renders_state_badges() -> None:
    started = datetime(2026, 8, 12, 9, 0, 0)
    family = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha",
        project_file="/tmp/gate.sase",
        status="TALE DONE",
        start_time=started,
        raw_suffix="20260812085900",
        agent_name="alpha",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
    )

    def _gate(name: str, state: str) -> Agent:
        return Agent(
            agent_type=AgentType.RUNNING,
            cl_name=name,
            project_file="/tmp/gate.sase",
            status="GATED" if state != "pending" else "GATE",
            start_time=started,
            stop_time=started + timedelta(minutes=3) if state != "pending" else None,
            raw_suffix=f"2026081209{name}",
            parent_timestamp=family.raw_suffix,
            agent_name=name,
            agent_family="alpha",
            agent_family_role="gate",
            role_suffix="--gate",
            gate_id=f"{name}-gate",
            gate_kind="test",
            gate_state=state,
        )

    pending = _gate("alpha--gate-pending", "pending")
    settled = _gate("alpha--gate-done", "answered")
    failed = _gate("alpha--gate-failed", "failed")
    family.followup_agents = [pending, settled, failed]
    assert _gate_lane_counts(family).running == 1
    assert _gate_lane_counts(family).settled == 1
    assert _gate_lane_counts(family).failed == 1

    left, _suffix, _option_id = format_agent_option(family, 0, is_selected=False)

    assert "⋔1 ⋔1 ⋔1" in left.plain
    first = left.plain.index("⋔1")
    second = left.plain.index("⋔1", first + 1)
    third = left.plain.index("⋔1", second + 1)
    assert style_at(left, first) == _GATE_COUNT_GLYPH_STYLE
    assert style_at(left, second) == _GATE_SETTLED_COUNT_GLYPH_STYLE
    assert style_at(left, third) == _GATE_FAILED_COUNT_GLYPH_STYLE
