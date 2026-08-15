"""Tests for the monitor family-root display-parent normalization.

A monitor started by a mid-family continuation persists a direct
``parent_timestamp`` back to that continuation (durable data monitor
settlement relies on to fork the starter safely), not to the family root. The
Agents tab treats ``parent_timestamp`` as its display-containment link, so
:func:`normalize_monitor_family_display_parents` rewrites the in-memory link
only, and only when it can uniquely resolve the monitor's loaded family root.
"""

from datetime import datetime, timedelta

from sase.ace.tui.models._agent_clan import (
    sase_agent_status_counts,
    agent_summary_status_counts,
)
from sase.ace.tui.models._agent_status_family import (
    normalize_monitor_family_display_parents,
)
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


def test_direct_root_monitor_is_left_unchanged() -> None:
    """A monitor already parented to the root is a true no-op."""
    root = _root()
    monitor = _monitor(root, root, raw_suffix="20260810092000")

    normalize_monitor_family_display_parents([root, monitor])

    assert monitor.parent_timestamp == root.raw_suffix


def test_monitor_without_agent_family_is_left_unchanged() -> None:
    """A monitor with no family metadata cannot be safely rerooted."""
    root = _root()
    coder = _code_child(root, raw_suffix="20260810091000")
    monitor = _monitor(coder, root, raw_suffix="20260810092000")
    monitor.agent_family = None

    normalize_monitor_family_display_parents([root, coder, monitor])

    assert monitor.parent_timestamp == coder.raw_suffix


def test_monitor_outside_any_loaded_family_is_left_unchanged() -> None:
    """No loaded root for the family means the starter link is preserved."""
    coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="fam-code",
        project_file="/tmp/family.sase",
        status="DONE",
        start_time=_STARTED + timedelta(minutes=10),
        raw_suffix="20260810091000",
    )
    monitor = _monitor(coder, _root(), raw_suffix="20260810092000")

    normalize_monitor_family_display_parents([coder, monitor])

    assert monitor.parent_timestamp == coder.raw_suffix


def test_normalization_is_scoped_per_project() -> None:
    """Same-named families in different projects never cross-attach."""
    root_a = _root(project_file="/tmp/a.sase", raw_suffix="20260810090000")
    coder_a = _code_child(root_a, raw_suffix="20260810091000")
    monitor_a = _monitor(coder_a, root_a, raw_suffix="20260810092000")

    root_b = _root(project_file="/tmp/b.sase", raw_suffix="20260811090000")
    coder_b = _code_child(root_b, raw_suffix="20260811091000")
    monitor_b = _monitor(coder_b, root_b, raw_suffix="20260811092000")

    normalize_monitor_family_display_parents(
        [root_a, coder_a, monitor_a, root_b, coder_b, monitor_b]
    )

    assert monitor_a.parent_timestamp == root_a.raw_suffix
    assert monitor_b.parent_timestamp == root_b.raw_suffix


def test_normalization_fails_safe_on_ambiguous_family_root() -> None:
    """Two loaded roots sharing a project + family identity block rerooting."""
    root_1 = _root(raw_suffix="20260810090000")
    root_2 = _root(raw_suffix="20260810090500")
    coder = _code_child(root_1, raw_suffix="20260810091000")
    monitor = _monitor(coder, root_1, raw_suffix="20260810092000")

    normalize_monitor_family_display_parents([root_1, root_2, coder, monitor])

    assert monitor.parent_timestamp == coder.raw_suffix


def test_normalization_is_idempotent_across_repeated_passes() -> None:
    """Repeated normalization over the same cached objects is a fixed point."""
    root = _root()
    coder = _code_child(root, raw_suffix="20260810091000")
    monitor = _monitor(coder, root, raw_suffix="20260810092000")
    agents = [root, coder, monitor]

    normalize_monitor_family_display_parents(agents)
    first_pass = monitor.parent_timestamp
    normalize_monitor_family_display_parents(agents)
    normalize_monitor_family_display_parents(agents)

    assert monitor.parent_timestamp == first_pass == root.raw_suffix


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
