"""Tests for nested-monitor family-root liveness without display rerooting.

A monitor started by a mid-family continuation persists a direct
``parent_timestamp`` back to that continuation (durable data monitor
settlement relies on to fork the starter safely), not to the family root.
The Agents tab now keeps that starter link and nests the monitor under the
starter; family-root liveness is preserved by status propagation.
"""

from datetime import datetime, timedelta

from sase.ace.tui.models._agent_clan import (
    sase_agent_status_counts,
    agent_summary_status_counts,
)
from sase.ace.tui.models._agent_loader_normalization import normalize_loaded_agents
from sase.ace.tui.models._agent_ordering import sort_and_reorder
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides

_STARTED = datetime(2026, 8, 10, 9, 0, 0)


def _root(
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
        agent_name=family,
        agent_family=family,
        agent_family_role="root",
        plan_chain_root=True,
    )


def _code_child(root: Agent, *, raw_suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{root.agent_family}-code",
        project_file=root.project_file,
        status="DONE",
        start_time=_STARTED + timedelta(minutes=10),
        raw_suffix=raw_suffix,
        parent_timestamp=root.raw_suffix,
        role_suffix="--code",
        agent_family=root.agent_family,
        agent_family_role="code",
    )


def _monitor(
    starter: Agent,
    root: Agent,
    *,
    raw_suffix: str,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{root.agent_family}-mon",
        project_file=root.project_file,
        status="MONITORING",
        status_bucket="Running",
        start_time=_STARTED + timedelta(minutes=20),
        raw_suffix=raw_suffix,
        parent_timestamp=starter.raw_suffix,
        role_suffix="--mon",
        agent_family=root.agent_family,
        agent_family_role="monitor",
        monitor_id="m123",
        monitor_state="running",
    )


def test_nested_monitor_keeps_starter_parent_link() -> None:
    """Display normalization no longer rewrites the durable starter link."""
    root = _root()
    coder = _code_child(root, raw_suffix="20260810091000")
    monitor = _monitor(coder, root, raw_suffix="20260810092000")

    _apply_status_overrides([root, coder, monitor])
    _apply_status_overrides([root, coder, monitor])

    assert monitor.parent_timestamp == coder.raw_suffix
    assert coder in root.followup_agents
    assert monitor not in root.followup_agents


def test_direct_root_monitor_is_left_unchanged() -> None:
    """A monitor already parented to the root keeps that link."""
    root = _root()
    monitor = _monitor(root, root, raw_suffix="20260810092000")

    _apply_status_overrides([root, monitor])

    assert monitor.parent_timestamp == root.raw_suffix
    assert monitor in root.followup_agents


def test_nested_monitor_renders_under_starter() -> None:
    root = _root()
    coder = _code_child(root, raw_suffix="20260810091000")
    monitor = _monitor(coder, root, raw_suffix="20260810092000")

    _apply_status_overrides([root, coder, monitor])
    ordered = sort_and_reorder([root, coder, monitor], [])

    assert [agent.raw_suffix for agent in ordered] == [
        root.raw_suffix,
        coder.raw_suffix,
        monitor.raw_suffix,
    ]
    assert monitor.tree_parent_key in {None, coder.raw_suffix}
    assert ordered.index(monitor) == ordered.index(coder) + 1


def test_nested_monitor_family_lane_counts_running_without_extra_agent() -> None:
    """A live nested monitor is one running lane, not an extra counted agent.

    Neither loaded LLM-driving row (root, coder) is itself an in-flight
    process once the coder has handed off -- only the plain OS-level monitor
    is -- so the concrete-agent summary settles both to Done with no running
    entry and, crucially, no third (phantom) entry for the monitor. The lane
    view is what mirrors the monitor's activity: the family is one lane and
    it reads Running.
    """
    root = _root()
    coder = _code_child(root, raw_suffix="20260810091000")
    coder.status = "TALE DONE"
    monitor = _monitor(coder, root, raw_suffix="20260810092000")

    _apply_status_overrides([root, coder, monitor])

    summary = agent_summary_status_counts((root,), ())
    lane = sase_agent_status_counts((root,), ())

    # root + coder only -- the monitor never counts as its own LLM agent.
    assert summary.total == 2
    assert summary.done == 2
    assert summary.running == 0

    assert lane.total == 1
    assert lane.running == 1
    assert monitor.parent_timestamp == coder.raw_suffix


def test_normalize_loaded_agents_nests_screenshot_monitor_at_depth_three() -> None:
    """Clan -> family root -> ``--2`` -> disk-shaped monitor at depth 3."""
    family = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase-ns.6.6.6.1",
        project_file="/tmp/sase.sase",
        status="TALE DONE",
        start_time=datetime(2026, 8, 17, 5, 55, 18),
        raw_suffix="20260817055518",
        role_suffix="--plan",
        workflow="ace-run",
        agent_name="sase-ns.6.6.6.1",
        agent_family="sase-ns.6.6.6.1",
        agent_family_role="root",
        plan_chain_root=True,
        agent_clan="sase-ns.6.6.6",
        agent_clan_generation="20260817055518",
        plan_action="tale",
    )
    plan = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file=family.project_file,
        status="TALE APPROVED",
        start_time=family.start_time,
        raw_suffix=family.raw_suffix,
        parent_timestamp=family.raw_suffix,
        parent_workflow="ace-run",
        step_type="agent",
        step_index=0,
        total_steps=1,
        role_suffix="--plan",
        agent_name="sase-ns.6.6.6.1--plan",
        agent_family=family.agent_family,
    )
    code = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase-ns.6.6.6.1--code",
        project_file=family.project_file,
        status="TALE DONE",
        start_time=datetime(2026, 8, 17, 6, 10, 0),
        stop_time=datetime(2026, 8, 17, 6, 40, 0),
        raw_suffix="20260817061000",
        parent_timestamp=family.raw_suffix,
        role_suffix="--code",
        agent_name="sase-ns.6.6.6.1--code",
        agent_family=family.agent_family,
        agent_family_role="code",
    )
    one = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase-ns.6.6.6.1--1",
        project_file=family.project_file,
        status="TALE DONE",
        start_time=datetime(2026, 8, 17, 6, 50, 0),
        stop_time=datetime(2026, 8, 17, 7, 0, 0),
        raw_suffix="20260817065000",
        parent_timestamp=family.raw_suffix,
        role_suffix="--1",
        agent_name="sase-ns.6.6.6.1--1",
        agent_family=family.agent_family,
        agent_family_role="code",
    )
    two = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase-ns.6.6.6.1--2",
        project_file=family.project_file,
        status="TALE DONE",
        start_time=datetime(2026, 8, 17, 7, 8, 11),
        stop_time=datetime(2026, 8, 17, 7, 14, 0),
        raw_suffix="20260817070811",
        parent_timestamp=family.raw_suffix,
        role_suffix="--2",
        agent_name="sase-ns.6.6.6.1--2",
        agent_family=family.agent_family,
        agent_family_role="code",
    )
    monitor = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sase-ns.6.6.6.1--mon-1",
        project_file=family.project_file,
        status="MONITORING",
        status_bucket="Running",
        start_time=datetime(2026, 8, 17, 7, 15, 11),
        raw_suffix="20260817071511",
        parent_timestamp=two.raw_suffix,
        role_suffix="--mon-1",
        agent_name="sase-ns.6.6.6.1--mon-1",
        agent_family=family.agent_family,
        agent_family_role="monitor",
        monitor_id="m1",
        monitor_state="running",
    )

    ordered = normalize_loaded_agents(
        [family, code, one, two, monitor],
        [plan],
        is_process_running=lambda _pid: False,
    )

    monitors = [row for row in ordered if row.is_monitor]
    assert len(monitors) == 1
    nested = monitors[0]
    starter = next(row for row in ordered if row.raw_suffix == two.raw_suffix)
    assert nested.agent_clan is None
    assert nested.agent_clan_generation is None
    assert nested.parent_timestamp == starter.raw_suffix
    assert nested.tree_parent_key == starter.raw_suffix
    assert nested.tree_depth == starter.tree_depth + 1 == 3
    assert ordered[ordered.index(starter) + 1] is nested
    assert ordered[0].is_clan_container is True
