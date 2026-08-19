"""Monitor member row rendering tests."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from sase.ace.tui.models._agent_clan import (
    ClanStatusCounts as ParallelFamilyStatusCounts,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_family_members import (
    is_sequential_family_container,
    monitor_lane_counts,
)
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.ace.tui.widgets._agent_list_styling import (
    _MONITOR_COUNT_GLYPH_STYLE,
    _MONITOR_GLYPH_STYLE,
    _MONITOR_ROW_STYLE,
    _MONITOR_SETTLED_COUNT_GLYPH_STYLE,
    _MONITOR_SETTLED_GLYPH_STYLE,
)


def _monitor(
    *,
    status: str,
    monitor_state: str | None,
    exit_code: int | None = None,
    followup_error: str | None = None,
    followup_outcome: str | None = None,
) -> Agent:
    started = datetime(2026, 8, 12, 9, 0, 0)
    stop_time = (
        started + timedelta(minutes=3)
        if monitor_state in {"completed", "failed", "timeout", "stopped", "lost"}
        else None
    )
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-row",
        project_file="/tmp/monitor.sase",
        status=status,
        status_bucket=(
            "Running"
            if monitor_state == "running"
            else "Failed"
            if monitor_state in {"failed", "timeout", "lost"}
            else "Done"
        ),
        start_time=started,
        run_start_time=started,
        stop_time=stop_time,
        raw_suffix="20260812090000",
        parent_timestamp="20260812085900",
        agent_name="alpha--mon",
        agent_family="alpha",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m123",
        monitor_state=monitor_state,
        monitor_label="just check",
        monitor_command="just check-full",
        monitor_exit_code=exit_code,
        monitor_followup_error=followup_error,
        monitor_followup_outcome=followup_outcome,
    )


def _monitor_starter() -> Agent:
    started = datetime(2026, 8, 12, 9, 0, 0)
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="starter-row",
        project_file="/tmp/monitor.sase",
        status="DONE",
        status_bucket="Done",
        start_time=started,
        stop_time=started + timedelta(minutes=3),
        raw_suffix="20260812090000",
        agent_name="alpha--0",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
        monitor_id="m123",
        monitor_label="just check",
        monitor_command="just check-full",
    )


def test_monitor_row_uses_glyph_and_label_without_the_command() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORING", monitor_state="running"),
        0,
        is_selected=False,
    )

    assert "⚙" in left.plain
    assert "just check" in left.plain
    assert "just check-full" not in left.plain
    assert "MONITORING" in left.plain


def test_monitor_starter_row_uses_agent_rendering_not_monitor_rendering() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor_starter(),
        0,
        is_selected=False,
    )

    assert "⚙" not in left.plain
    assert "starter-row" in left.plain
    assert "just check" not in left.plain
    assert not any(str(span.style) == _MONITOR_ROW_STYLE for span in left.spans)


def test_failed_monitor_row_renders_exit_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORED", monitor_state="failed", exit_code=1),
        0,
        is_selected=False,
    )

    assert "✗ 1" in left.plain


def test_timeout_monitor_row_renders_timeout_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORED", monitor_state="timeout"),
        0,
        is_selected=False,
    )

    assert "⧖" in left.plain


def test_lost_monitor_row_renders_as_failed_without_exit_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORED", monitor_state="lost", exit_code=1),
        0,
        is_selected=False,
    )

    assert "MONITORED" in left.plain
    assert "✗ 1" not in left.plain


def test_dead_on_arrival_monitor_row_renders_stalled_badge() -> None:
    """A supervisor that died before reporting an exit code is not a plain FAILED row."""
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORED", monitor_state="failed", exit_code=None),
        0,
        is_selected=False,
    )

    assert "⚠" in left.plain
    assert "✗" not in left.plain


def test_lost_monitor_without_exit_code_renders_stalled_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORED", monitor_state="lost", exit_code=None),
        0,
        is_selected=False,
    )

    assert "⚠" in left.plain


def test_completed_monitor_row_has_no_stalled_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORED", monitor_state="completed", exit_code=0),
        0,
        is_selected=False,
    )

    assert "⚠" not in left.plain


def test_monitor_row_with_dropped_followup_renders_flag_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(
            status="MONITORED",
            monitor_state="completed",
            exit_code=0,
            followup_error="workspace #10 with pid 3333672 was not found",
        ),
        0,
        is_selected=False,
    )

    assert "⚑" in left.plain
    # A clean completion is not also flagged as dead-on-arrival.
    assert "⚠" not in left.plain


def test_monitor_row_with_degraded_followup_renders_flag_badge() -> None:
    """A degraded launch records no error, so the outcome alone must flag it."""
    left, _suffix, _option_id = format_agent_option(
        _monitor(
            status="MONITORED",
            monitor_state="completed",
            exit_code=0,
            followup_outcome="launched-degraded",
        ),
        0,
        is_selected=False,
    )

    assert "⚑" in left.plain


def test_monitor_row_with_a_clean_launched_followup_has_no_flag_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(
            status="MONITORED",
            monitor_state="completed",
            exit_code=0,
            followup_outcome="launched",
        ),
        0,
        is_selected=False,
    )

    assert "⚑" not in left.plain


def test_monitor_row_without_followup_error_has_no_flag_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORED", monitor_state="completed", exit_code=0),
        0,
        is_selected=False,
    )

    assert "⚑" not in left.plain


def _gear_style(text) -> str | None:
    return _style_at(text, text.plain.index("⚙"))


def test_running_monitor_row_renders_amber_gear() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORING", monitor_state="running"),
        0,
        is_selected=False,
    )

    assert _gear_style(left) == _MONITOR_GLYPH_STYLE


@pytest.mark.parametrize(
    "monitor_state",
    ("completed", "failed", "timeout", "stopped", "lost"),
)
def test_terminal_monitor_row_renders_grey_gear(monitor_state: str) -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORED", monitor_state=monitor_state),
        0,
        is_selected=False,
    )

    assert _gear_style(left) == _MONITOR_SETTLED_GLYPH_STYLE


def test_unreported_monitor_row_renders_amber_gear() -> None:
    left, _suffix, _option_id = format_agent_option(
        _monitor(status="MONITORING", monitor_state=None),
        0,
        is_selected=False,
    )

    assert _gear_style(left) == _MONITOR_GLYPH_STYLE


def test_running_monitor_row_with_stop_time_renders_grey_gear() -> None:
    monitor = _monitor(status="MONITORING", monitor_state="running")
    monitor.stop_time = datetime(2026, 8, 12, 9, 3, 0)

    left, _suffix, _option_id = format_agent_option(monitor, 0, is_selected=False)

    assert _gear_style(left) == _MONITOR_SETTLED_GLYPH_STYLE


def test_tree_child_settled_monitor_row_renders_grey_gear() -> None:
    container = _family_container("completed")
    monitor = container.followup_agents[0]

    left, _suffix, _option_id = format_agent_option(monitor, 0, is_selected=False)

    assert _gear_style(left) == _MONITOR_SETTLED_GLYPH_STYLE


def test_top_level_settled_monitor_row_renders_grey_gear() -> None:
    monitor = _monitor(status="MONITORED", monitor_state="completed")
    monitor.parent_timestamp = None

    left, _suffix, _option_id = format_agent_option(monitor, 0, is_selected=False)

    assert _gear_style(left) == _MONITOR_SETTLED_GLYPH_STYLE


def test_settled_row_gear_style_matches_container_settled_badge_style() -> None:
    container = _family_container("completed")
    monitor = container.followup_agents[0]

    row_left, _suffix, _option_id = format_agent_option(monitor, 0, is_selected=False)
    container_left, _c_suffix, _c_option_id = format_agent_option(
        container, 0, is_selected=False
    )

    assert _gear_style(row_left) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE
    assert _gear_style(container_left) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE


def _style_at(text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


def _family_container(*monitor_states: str) -> Agent:
    started = datetime(2026, 8, 12, 9, 0, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="alpha-root",
        project_file="/tmp/monitor.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="20260812090000",
        agent_name="alpha--0",
        agent_family="alpha",
        agent_family_role="root",
        role_suffix="--0",
    )
    monitors = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"alpha-mon-{index}",
            project_file="/tmp/monitor.sase",
            status="MONITORING" if monitor_state == "running" else "MONITORED",
            start_time=started,
            stop_time=None
            if monitor_state == "running"
            else started + timedelta(minutes=3),
            raw_suffix=f"2026081209000{index + 1}",
            parent_timestamp="20260812090000",
            agent_name=f"alpha--mon-{index}",
            agent_family="alpha",
            agent_family_role="monitor",
            role_suffix=f"--mon-{index}",
            monitor_id=f"m{index}",
            monitor_state=monitor_state,
            monitor_label="just check",
        )
        for index, monitor_state in enumerate(monitor_states)
    ]
    root.followup_agents = monitors
    return root


def test_family_container_with_running_monitor_renders_badge() -> None:
    left, _suffix, _option_id = format_agent_option(
        _family_container("running"),
        0,
        is_selected=False,
    )

    assert "⚙1" in left.plain


def test_family_container_with_only_settled_monitors_renders_grey_badge_only() -> None:
    left, _suffix, _option_id = format_agent_option(
        _family_container("completed"),
        0,
        is_selected=False,
    )

    assert "⚙1" in left.plain
    glyph_index = left.plain.index("⚙1")
    assert _style_at(left, glyph_index) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE


def test_family_container_with_running_and_settled_monitors_renders_both_badges() -> (
    None
):
    left, _suffix, _option_id = format_agent_option(
        _family_container("running", "completed", "stopped", "failed"),
        0,
        is_selected=False,
    )

    assert "⚙1 ⚙3" in left.plain
    running_index = left.plain.index("⚙1")
    settled_index = left.plain.index("⚙3")
    assert _style_at(left, running_index) == _MONITOR_COUNT_GLYPH_STYLE
    assert _style_at(left, settled_index) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE


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
        # check itself from ``monitor_lane_counts`` returning a nonzero lane.
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
    assert monitor_lane_counts(agent).running == 1

    left, _suffix, _option_id = format_agent_option(agent, 0, is_selected=False)

    assert "⚙" not in left.plain


def test_family_container_badge_does_not_alter_status_chip() -> None:
    counts = ParallelFamilyStatusCounts(running=2, awaiting=1)
    container = _family_container("running", "completed")
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
    assert monitor_lane_counts(starter).running == 1
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
    assert _style_at(left, glyph_index) == _MONITOR_SETTLED_COUNT_GLYPH_STYLE


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
        # check itself from ``monitor_lane_counts`` returning a nonzero lane.
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
    lanes = monitor_lane_counts(agent)
    assert lanes.running == 0
    assert lanes.settled == 1

    left, _suffix, _option_id = format_agent_option(agent, 0, is_selected=False)

    assert "⚙" not in left.plain
