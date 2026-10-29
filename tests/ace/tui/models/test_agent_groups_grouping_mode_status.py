"""GroupingMode: status bucketing."""

from __future__ import annotations

from datetime import datetime, timedelta

from sase.ace.tui.models._agent_status_apply import apply_status_overrides
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import (
    MONITORING_STATUS_GROUP,
    GroupingMode,
    _status_bucket_for,
    build_agent_tree,
    machine_grouping_signature,
    row_displays_live_monitor,
    status_bucket_for,
    status_grouping_signature,
)
from sase.agent.status_buckets import agent_status_bucket

from ._agent_groups_helpers import _NOW, _agent
from ._agent_tree_clan_status_helpers import make_clan_member, make_testing_member


def test_status_bucket_done() -> None:
    assert _status_bucket_for(_agent(status="DONE")) == "Done"


def test_status_bucket_feedback_is_done() -> None:
    assert _status_bucket_for(_agent(status="FEEDBACK")) == "Done"


def test_status_bucket_running() -> None:
    assert _status_bucket_for(_agent(status="RUNNING")) == "Running"


def test_status_bucket_starting() -> None:
    assert _status_bucket_for(_agent(status="STARTING")) == "Starting"


def test_status_bucket_plan_is_stopped() -> None:
    """``PLAN`` is a submitted plan waiting on user review."""
    assert _status_bucket_for(_agent(status="PLAN")) == "Stopped"


def test_status_bucket_question_is_stopped() -> None:
    assert _status_bucket_for(_agent(status="QUESTION")) == "Stopped"


def test_status_bucket_plan_approved_is_running() -> None:
    """An approved plan is actively executing → Running."""
    assert _status_bucket_for(_agent(status="PLAN APPROVED")) == "Running"


def test_status_bucket_working_plan_statuses_are_running() -> None:
    """Coder handoff working states are actively executing → Running."""
    assert _status_bucket_for(_agent(status="WORKING PLAN")) == "Running"
    assert _status_bucket_for(_agent(status="WORKING TALE")) == "Running"


def test_status_bucket_answered_is_running() -> None:
    """ANSWERED is transient post-answer progress → Running, not Stopped."""
    assert _status_bucket_for(_agent(status="ANSWERED")) == "Running"


def test_status_bucket_plan_done_is_done() -> None:
    """``PLAN DONE`` is a post-plan handoff state — planning work is finished."""
    assert _status_bucket_for(_agent(status="PLAN DONE")) == "Done"


def test_status_bucket_tale_done_is_done() -> None:
    """``TALE DONE`` is a post-plan handoff state for tale-approved plans."""
    assert _status_bucket_for(_agent(status="TALE DONE")) == "Done"


def test_status_bucket_plan_rejected_is_done() -> None:
    """``PLAN REJECTED`` is a terminal plan decision, not active planning."""
    assert _status_bucket_for(_agent(status="PLAN REJECTED")) == "Done"


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


def test_status_bucket_failed_terminal_is_failed() -> None:
    """Every displayed ``FAILED`` status lands in the Failed bucket."""
    a = _agent(status="FAILED", retried_as_timestamp=None)
    assert _status_bucket_for(a) == "Failed"


def test_status_bucket_failed_then_retried_is_failed() -> None:
    """FAILED with a forward retry pointer is handed-off, not actionable."""
    a = _agent(status="FAILED", retried_as_timestamp="ts-child")
    assert _status_bucket_for(a) == "Failed"


def test_status_bucket_failed_retried_status_string_is_failed() -> None:
    """``FAILED (RETRIED)`` is the display status of a handed-off failure."""
    a = _agent(status="FAILED (RETRIED)", retried_as_timestamp=None)
    assert _status_bucket_for(a) == "Failed"


def test_status_bucket_unknown_status_falls_through_to_running() -> None:
    """Unrecognized states default to Running rather than disappearing."""
    a = _agent(status="WHATEVER")
    assert _status_bucket_for(a) == "Running"


def test_status_bucket_empty_status_is_running() -> None:
    a = _agent(status="")
    assert _status_bucket_for(a) == "Running"


def _monitoring_agent(
    *,
    status: str = "MONITORING",
    monitor_start_status: str | None = "MONITORING",
    monitor_stop_status: str | None = "MONITORED",
    monitor_state: str | None = "running",
    status_bucket: str | None = "Running",
) -> Agent:
    agent = _agent(status=status)
    agent.status_bucket = status_bucket
    agent.monitor_start_status = monitor_start_status
    agent.monitor_stop_status = monitor_stop_status
    agent.monitor_state = monitor_state
    return agent


def test_monitoring_session_root_mirroring_running_monitor() -> None:
    agent = _monitoring_agent()
    assert row_displays_live_monitor(agent) is True
    assert status_bucket_for(agent) == MONITORING_STATUS_GROUP
    assert status_bucket_for(agent) == "Monitoring"
    assert agent_status_bucket(agent) == "Running"


def test_monitoring_custom_pair_matches_start_label() -> None:
    agent = _monitoring_agent(
        status="TESTING",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
    )
    assert status_bucket_for(agent) == "Monitoring"
    assert agent_status_bucket(agent) == "Running"


def test_monitoring_status_match_is_case_insensitive() -> None:
    agent = _monitoring_agent(
        status="Testing",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
    )
    assert status_bucket_for(agent) == "Monitoring"


def test_monitoring_missing_monitor_state_counts_as_live() -> None:
    agent = _monitoring_agent(monitor_state=None)
    assert row_displays_live_monitor(agent) is True
    assert status_bucket_for(agent) == "Monitoring"


def test_settled_monitor_does_not_use_monitoring_group() -> None:
    agent = _monitoring_agent(
        status="MONITORED",
        monitor_start_status="MONITORING",
        monitor_stop_status="MONITORED",
        monitor_state="completed",
        status_bucket=None,
    )
    assert row_displays_live_monitor(agent) is False
    assert status_bucket_for(agent) != "Monitoring"


def test_failed_monitor_stays_in_failed_group() -> None:
    agent = _monitoring_agent(
        status="TESTED",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state="failed",
        status_bucket="Failed",
    )
    assert status_bucket_for(agent) == "Failed"
    assert agent_status_bucket(agent) == "Failed"


def test_running_status_with_monitor_pair_stays_running() -> None:
    agent = _monitoring_agent(
        status="RUNNING",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state="running",
    )
    assert row_displays_live_monitor(agent) is False
    assert status_bucket_for(agent) == "Running"


def test_row_without_monitor_pair_keeps_bucket() -> None:
    agent = _agent(status="RUNNING")
    assert row_displays_live_monitor(agent) is False
    assert status_bucket_for(agent) == "Running"


def test_monitoring_shared_bucket_stays_running() -> None:
    for status in ("MONITORING", "TESTING", "Testing"):
        agent = _monitoring_agent(
            status=status,
            monitor_start_status=(
                "MONITORING" if status == "MONITORING" else "TESTING"
            ),
            monitor_stop_status=("MONITORED" if status == "MONITORING" else "TESTED"),
        )
        assert agent_status_bucket(agent) == "Running"
        assert status_bucket_for(agent) == "Monitoring"


_STARTED = datetime(2026, 8, 10, 9, 0, 0)


def _plan_root() -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sess",
        project_file="/tmp/agent_session.sase",
        status="DONE",
        start_time=_STARTED,
        raw_suffix="20260810090000",
        role_suffix="--plan",
        workflow="ace-run",
        agent_name="sess",
        agent_session="sess",
        agent_session_role="root",
        plan_chain_root=True,
        plan_action="tale",
    )


def _code_child(root: Agent) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{root.agent_session}-code",
        project_file=root.project_file,
        status="TALE DONE",
        start_time=_STARTED + timedelta(minutes=10),
        stop_time=_STARTED + timedelta(minutes=13),
        raw_suffix="20260810091000",
        parent_timestamp=root.raw_suffix,
        role_suffix="--code",
        agent_name=f"{root.agent_session}--code",
        agent_session=root.agent_session,
        agent_session_role="code",
    )


def _nested_monitor(
    code_child: Agent,
    root: Agent,
    *,
    status: str = "MONITORING",
    status_bucket: str | None = "Running",
    monitor_state: str | None = "running",
    monitor_start_status: str | None = "MONITORING",
    monitor_stop_status: str | None = "MONITORED",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{root.agent_session}-mon",
        project_file=root.project_file,
        status=status,
        status_bucket=status_bucket,
        start_time=_STARTED + timedelta(minutes=20),
        run_start_time=_STARTED + timedelta(minutes=20),
        stop_time=None,
        raw_suffix="20260810092000",
        parent_timestamp=code_child.raw_suffix,
        role_suffix="--mon",
        agent_name=f"{root.agent_session}--mon",
        agent_session=root.agent_session,
        agent_session_role="monitor",
        monitor_id="m123",
        monitor_state=monitor_state,
        monitor_start_status=monitor_start_status,
        monitor_stop_status=monitor_stop_status,
        monitor_label="just check",
        monitor_command="just check-full",
    )


def _l0_banners(entries: list) -> list[tuple[str, ...]]:
    return [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 0
    ]


def test_monitoring_session_subtree_groups_under_monitoring() -> None:
    root = _plan_root()
    coder = _code_child(root)
    monitor = _nested_monitor(
        coder,
        root,
        monitor_start_status="MONITORING",
        monitor_stop_status="MONITORED",
    )
    apply_status_overrides([root, coder, monitor])
    assert root.status == "MONITORING"
    assert status_bucket_for(root) == "Monitoring"

    running = _agent(
        cl_name="plain-running",
        agent_name="plain",
        status="RUNNING",
        start_time=datetime(2026, 8, 10, 8, 0, 0),
    )
    done = _agent(
        cl_name="plain-done",
        agent_name="finished",
        status="DONE",
        start_time=datetime(2026, 8, 10, 11, 0, 0),
    )
    agents = [root, coder, monitor, running, done]
    entries = build_agent_tree(agents, mode=GroupingMode.BY_STATUS, now=_NOW)

    assert _l0_banners(entries) == [("Running",), ("Monitoring",), ("Done",)]
    agent_order = [e.agent_idx for e in entries if e.kind == "agent"]
    session_indices = [agents.index(root), agents.index(coder), agents.index(monitor)]
    positions = [agent_order.index(idx) for idx in session_indices]
    assert positions == sorted(positions)
    assert max(positions) - min(positions) == 2


def test_monitoring_session_leaves_after_monitor_settles() -> None:
    root = _plan_root()
    coder = _code_child(root)
    monitor = _nested_monitor(
        coder,
        root,
        monitor_start_status="MONITORING",
        monitor_stop_status="MONITORED",
    )
    apply_status_overrides([root, coder, monitor])
    assert status_bucket_for(root) == "Monitoring"

    monitor.status = "MONITORED"
    monitor.status_bucket = "Done"
    monitor.monitor_state = "completed"
    monitor.stop_time = _STARTED + timedelta(minutes=25)
    apply_status_overrides([root, coder, monitor])

    assert status_bucket_for(root) != "Monitoring"
    running = _agent(cl_name="plain-running", agent_name="plain", status="RUNNING")
    done = _agent(cl_name="plain-done", agent_name="finished", status="DONE")
    entries = build_agent_tree(
        [root, coder, monitor, running, done],
        mode=GroupingMode.BY_STATUS,
        now=_NOW,
    )
    assert ("Monitoring",) not in _l0_banners(entries)


def test_lone_monitoring_clan_groups_under_monitoring() -> None:
    testing = make_testing_member()
    members = [
        make_clan_member("research.done", "done", status="DONE"),
        testing,
    ]
    container, *_ = project_clan_tree(members)
    assert container.status == "TESTING"
    assert status_bucket_for(container) == "Monitoring"

    entries = build_agent_tree(
        [container, *members], mode=GroupingMode.BY_STATUS, now=_NOW
    )
    assert ("Monitoring",) in _l0_banners(entries)


def test_two_running_members_keep_clan_under_running() -> None:
    members = [
        make_testing_member(),
        make_clan_member("research.plain", "plain", status="RUNNING"),
        make_clan_member("research.done", "done", status="DONE"),
    ]
    container, *_ = project_clan_tree(members)
    assert container.status == "RUNNING"
    assert status_bucket_for(container) == "Running"


def test_by_machine_monitoring_session_forms_monitoring_subgroup() -> None:
    agent = _monitoring_agent()
    agent.fleet_origin_alias = "apollo"
    other = _agent(status="RUNNING")
    other.fleet_origin_alias = "apollo"
    entries = build_agent_tree([agent, other], mode=GroupingMode.BY_MACHINE, now=_NOW)
    l1_keys = [
        e.group.group_key  # type: ignore[union-attr]
        for e in entries
        if e.kind == "group" and e.group is not None and e.group.level == 1
    ]
    assert ("apollo", "Running") in l1_keys
    assert ("apollo", "Monitoring") in l1_keys
    assert l1_keys.index(("apollo", "Running")) < l1_keys.index(
        ("apollo", "Monitoring")
    )


def test_running_to_monitoring_flip_changes_grouping_signature() -> None:
    old = _agent(status="RUNNING", agent_name="alpha")
    new = _monitoring_agent(status="TESTING")
    new.agent_name = "alpha"
    assert status_grouping_signature(old) != status_grouping_signature(new)
    old.fleet_origin_alias = "apollo"
    new.fleet_origin_alias = "apollo"
    assert machine_grouping_signature(old) != machine_grouping_signature(new)
