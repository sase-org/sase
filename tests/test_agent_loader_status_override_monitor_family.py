"""Tests for family-root status mirroring of a nested-parent monitor member.

A monitor started by a mid-family continuation (for example an approved
coder) persists a direct ``parent_timestamp`` back to that continuation
rather than to the family root -- durable data monitor settlement relies on
to fork the starter safely. These tests reproduce that nested topology and
assert the Agents-tab family root still mirrors the monitor's lifecycle
instead of appearing terminal while the monitor runs.
"""

from datetime import datetime, timedelta

from sase.agent.status_buckets import agent_status_bucket
from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides

_STARTED = datetime(2026, 8, 10, 9, 0, 0)


def _plan_root(
    *,
    family: str = "fam",
    project_file: str = "/tmp/family.sase",
    raw_suffix: str = "20260810090000",
) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=family,
        project_file=project_file,
        status="DONE",
        start_time=_STARTED,
        raw_suffix=raw_suffix,
        role_suffix="--plan",
        workflow="ace-run",
        agent_name=family,
        agent_family=family,
        agent_family_role="root",
        plan_chain_root=True,
        plan_action="tale",
    )


def _completed_code_child(
    root: Agent,
    *,
    raw_suffix: str = "20260810091000",
    offset_minutes: int = 10,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{root.agent_family}-code",
        project_file=root.project_file,
        status="TALE DONE",
        start_time=_STARTED + timedelta(minutes=offset_minutes),
        stop_time=_STARTED + timedelta(minutes=offset_minutes + 3),
        raw_suffix=raw_suffix,
        parent_timestamp=root.raw_suffix,
        role_suffix="--code",
        agent_name=f"{root.agent_family}--code",
        agent_family=root.agent_family,
        agent_family_role="code",
    )


def _nested_monitor(
    code_child: Agent,
    root: Agent,
    *,
    raw_suffix: str = "20260810092000",
    offset_minutes: int = 20,
    status: str = "MONITORING",
    status_bucket: str = "Running",
    monitor_state: str = "running",
    stop_time: datetime | None = None,
) -> Agent:
    """A monitor whose durable starter link points at the coder, not the root."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{root.agent_family}-mon",
        project_file=root.project_file,
        status=status,
        status_bucket=status_bucket,
        start_time=_STARTED + timedelta(minutes=offset_minutes),
        run_start_time=_STARTED + timedelta(minutes=offset_minutes),
        stop_time=stop_time,
        raw_suffix=raw_suffix,
        parent_timestamp=code_child.raw_suffix,
        role_suffix="--mon",
        agent_name=f"{root.agent_family}--mon",
        agent_family=root.agent_family,
        agent_family_role="monitor",
        monitor_id="m123",
        monitor_state=monitor_state,
        monitor_label="just check",
        monitor_command="just check-full",
    )


def test_nested_monitor_keeps_starter_parent_for_display() -> None:
    """The monitor stays under the coder; the root still lists the coder."""
    root = _plan_root()
    coder = _completed_code_child(root)
    monitor = _nested_monitor(coder, root)

    _apply_status_overrides([root, coder, monitor])

    assert monitor.parent_timestamp == coder.raw_suffix
    assert monitor not in root.followup_agents
    assert coder in root.followup_agents


def test_nested_running_monitor_root_mirrors_monitoring_and_running_bucket() -> None:
    """The collapsed root shows MONITORING/Running, not TALE DONE."""
    root = _plan_root()
    coder = _completed_code_child(root)
    monitor = _nested_monitor(coder, root)

    _apply_status_overrides([root, coder, monitor])

    assert root.status == "MONITORING"
    assert root.status_bucket == "Running"
    assert agent_status_bucket(root) == "Running"


def test_nested_monitor_remains_in_visible_family_row_order() -> None:
    """The monitor is emitted immediately after the starter that owns it."""
    root = _plan_root()
    coder = _completed_code_child(root)
    monitor = _nested_monitor(coder, root)

    _apply_status_overrides([root, coder, monitor])
    ordered = sort_and_reorder([root, coder, monitor], [])

    assert [agent.raw_suffix for agent in ordered] == [
        root.raw_suffix,
        coder.raw_suffix,
        monitor.raw_suffix,
    ]
    assert monitor.parent_timestamp == coder.raw_suffix


def test_nested_terminal_successful_monitor_root_mirrors_stop_label() -> None:
    """A completed nested monitor still projects its configured stop label."""
    root = _plan_root()
    coder = _completed_code_child(root)
    monitor = _nested_monitor(
        coder,
        root,
        status="MONITORED",
        status_bucket="Done",
        monitor_state="completed",
        stop_time=_STARTED + timedelta(minutes=25),
    )

    _apply_status_overrides([root, coder, monitor])

    assert monitor.parent_timestamp == coder.raw_suffix
    assert root.status == "MONITORED"
    assert root.status_bucket == "Done"


def test_nested_terminal_failed_monitor_root_mirrors_failed_bucket() -> None:
    """A failed nested monitor does not get masked as a generic done root."""
    root = _plan_root()
    coder = _completed_code_child(root)
    monitor = _nested_monitor(
        coder,
        root,
        status="CHECKED",
        status_bucket="Failed",
        monitor_state="failed",
        stop_time=_STARTED + timedelta(minutes=25),
    )

    _apply_status_overrides([root, coder, monitor])

    assert root.status == "CHECKED"
    assert root.status_bucket == "Failed"


def test_root_advances_past_terminal_monitor_to_later_active_followup() -> None:
    """A later resumed agent outranks the settled monitor's terminal status."""
    root = _plan_root()
    coder = _completed_code_child(root)
    monitor = _nested_monitor(
        coder,
        root,
        status="MONITORED",
        status_bucket="Done",
        monitor_state="completed",
        stop_time=_STARTED + timedelta(minutes=25),
    )
    resumed = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{root.agent_family}-code2",
        project_file=root.project_file,
        status="RUNNING",
        start_time=_STARTED + timedelta(minutes=30),
        raw_suffix="20260810093000",
        parent_timestamp=root.raw_suffix,
        role_suffix="--code2",
        agent_name=f"{root.agent_family}--code2",
        agent_family=root.agent_family,
        agent_family_role="code",
    )

    _apply_status_overrides([root, coder, monitor, resumed])

    assert root.status == resumed.status
    assert root.status_bucket == resumed.status_bucket
    assert root.status not in {"MONITORED", "MONITORING"}
