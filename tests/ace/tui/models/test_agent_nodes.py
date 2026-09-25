"""Agents-tab agent-node taxonomy tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_nodes import (
    agent_node_completion_keys,
    agent_node_projection_index,
    is_agents_tab_agent_node,
    projection_has_active_completion,
)

_START = datetime(2026, 8, 16, 12, 0, 0)


def _agent(name: str, **overrides: object) -> Agent:
    values: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": name,
        "project_file": "/tmp/demo.sase",
        "status": "RUNNING",
        "start_time": _START,
        "raw_suffix": f"suffix-{name}",
        "agent_name": name,
    }
    values.update(overrides)
    return Agent(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("label", "row", "expected"),
    [
        ("standalone root", _agent("solo"), True),
        (
            "standalone under clan",
            _agent(
                "research.solo",
                agent_clan="research",
                agent_clan_generation="gen",
                tree_parent_key="clan:research:gen",
                tree_depth=1,
            ),
            True,
        ),
        (
            "session container",
            _agent(
                "build--plan",
                agent_session="build",
                agent_session_role="root",
                plan_chain_root=True,
            ),
            True,
        ),
        (
            "clan container",
            _agent(
                "research",
                raw_suffix=None,
                agent_clan="research",
                is_clan_container=True,
            ),
            False,
        ),
        (
            "session member shell",
            _agent(
                "build--code",
                parent_timestamp="suffix-build--plan",
                agent_session="build",
                agent_session_role="code",
            ),
            False,
        ),
        (
            "workflow step child",
            _agent(
                "workflow-step",
                parent_timestamp="suffix-workflow",
                parent_workflow="workflow",
                step_type="agent",
            ),
            False,
        ),
        (
            "monitor proc shell",
            _agent(
                "build--monitor",
                parent_timestamp="suffix-build--plan",
                agent_session="build",
                agent_session_role="monitor",
                monitor_id="monitor-1",
            ),
            False,
        ),
    ],
)
def test_agents_tab_agent_node_truth_table(
    label: str,
    row: Agent,
    expected: bool,
) -> None:
    assert is_agents_tab_agent_node(row) is expected, label


def test_agent_session_container_detection_counts_as_agent_node_after_member_load() -> (
    None
):
    root = _agent("build", agent_session="build", agent_session_role="root")
    child = _agent(
        "build--code",
        parent_timestamp=root.raw_suffix,
        agent_session="build",
        agent_session_role="code",
    )
    root.followup_agents = [child]

    assert root.is_agent_session_container_row
    assert is_agents_tab_agent_node(root)
    assert not is_agents_tab_agent_node(child)


def _plan_agent_session_root_with_main_step_and_continuation() -> tuple[
    Agent, Agent, Agent
]:
    """Build the shape from the regression: a plan root whose ``main`` workflow
    step shares the root's own ``raw_suffix``, plus a real continuation member.
    """
    root = _agent(
        "gh_sase-org__sase",
        agent_session="gh_sase-org__sase",
        agent_session_role="root",
        plan_chain_root=True,
        role_suffix="--plan",
    )
    main_step = _agent(
        "main",
        raw_suffix=root.raw_suffix,
        parent_timestamp=root.raw_suffix,
        parent_workflow="ace-run",
        step_type="agent",
    )
    continuation = _agent(
        "gh_sase-org__sase--code",
        parent_timestamp=root.raw_suffix,
        agent_session="gh_sase-org__sase",
        agent_session_role="code",
    )
    root.runtime_children = [main_step, continuation]
    root.followup_agents = [main_step, continuation]
    return root, main_step, continuation


def test_plan_agent_session_root_owns_its_key_not_its_main_step_key() -> None:
    root, _, continuation = _plan_agent_session_root_with_main_step_and_continuation()

    keys = agent_node_completion_keys(root)

    assert (root.cl_name, root.raw_suffix) in keys
    assert (continuation.cl_name, continuation.raw_suffix) in keys
    assert ("main", root.raw_suffix) not in keys


def test_plan_agent_session_root_projection_index_matches_its_own_key() -> None:
    root, main_step, continuation = (
        _plan_agent_session_root_with_main_step_and_continuation()
    )
    index = agent_node_projection_index([root, main_step, continuation])
    projection = index.by_node_identity[root.identity]
    root_key = (root.cl_name, root.raw_suffix)

    assert root_key in projection.completion_keys
    assert projection_has_active_completion(projection, {root_key})


def test_standalone_node_yields_exactly_one_completion_key() -> None:
    solo = _agent("solo")

    keys = agent_node_completion_keys(solo)

    assert keys == ((solo.cl_name, solo.raw_suffix),)


def test_sequential_agent_session_container_owns_member_keys_and_its_own_key() -> None:
    root = _agent(
        "alpha--0",
        agent_session="alpha",
        agent_session_role="root",
    )
    coder = _agent(
        "alpha--code",
        parent_timestamp=root.raw_suffix,
        agent_session="alpha",
        agent_session_role="code",
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]

    keys = agent_node_completion_keys(root)

    assert (root.cl_name, root.raw_suffix) in keys
    assert (coder.cl_name, coder.raw_suffix) in keys


def _gate_launch_agent_session() -> tuple[Agent, Agent, Agent]:
    """Build the production epic-launch shape: node → gate → monitor."""
    node = _agent(
        "build--plan",
        raw_suffix="node-suffix",
        agent_session="build",
        agent_session_role="root",
        plan_chain_root=True,
    )
    gate = _agent(
        "build--gate",
        raw_suffix="gate-suffix",
        parent_timestamp=node.raw_suffix,
        agent_session="build",
        agent_session_role="gate",
        gate_id="gate-1",
    )
    monitor = _agent(
        "build--mon",
        raw_suffix="mon-suffix",
        parent_timestamp=gate.raw_suffix,
        agent_session="build",
        agent_session_role="monitor",
        role_suffix="--mon",
        monitor_id="mon-1",
    )
    return node, gate, monitor


def test_gate_launch_monitor_is_owned_by_agent_session_node() -> None:
    node, gate, monitor = _gate_launch_agent_session()

    index = agent_node_projection_index([node, gate, monitor])
    projection = index.by_node_identity[node.identity]
    monitor_key = (monitor.cl_name, monitor.raw_suffix)

    assert index.owner_for_identity(monitor.identity) is projection
    assert monitor_key in projection.completion_keys
    assert projection_has_active_completion(projection, {monitor_key})


def test_agent_session_member_monitor_is_owned_by_agent_session_node() -> None:
    node = _agent(
        "build--plan",
        raw_suffix="node-suffix",
        agent_session="build",
        agent_session_role="root",
        plan_chain_root=True,
    )
    coder = _agent(
        "build--code",
        raw_suffix="code-suffix",
        parent_timestamp=node.raw_suffix,
        agent_session="build",
        agent_session_role="code",
    )
    monitor = _agent(
        "build--mon",
        raw_suffix="mon-suffix",
        parent_timestamp=coder.raw_suffix,
        agent_session="build",
        agent_session_role="monitor",
        role_suffix="--mon",
        monitor_id="mon-1",
    )

    index = agent_node_projection_index([node, coder, monitor])
    projection = index.by_node_identity[node.identity]

    assert index.owner_for_identity(monitor.identity) is projection
    assert (monitor.cl_name, monitor.raw_suffix) in projection.completion_keys


def test_ownership_chain_cycle_guard_stays_unowned() -> None:
    node = _agent(
        "build--plan",
        raw_suffix="node-suffix",
        agent_session="build",
        agent_session_role="root",
        plan_chain_root=True,
    )
    first = _agent(
        "build--a",
        raw_suffix="cycle-a",
        parent_timestamp="cycle-b",
        agent_session="build",
        agent_session_role="code",
    )
    second = _agent(
        "build--b",
        raw_suffix="cycle-b",
        parent_timestamp="cycle-a",
        agent_session="build",
        agent_session_role="code",
    )
    loop = _agent(
        "build--loop",
        raw_suffix="loop-suffix",
        parent_timestamp="loop-suffix",
        agent_session="build",
        agent_session_role="code",
    )

    index = agent_node_projection_index([node, first, second, loop])

    assert index.owner_for_identity(first.identity) is None
    assert index.owner_for_identity(second.identity) is None
    assert index.owner_for_identity(loop.identity) is None


def test_ownership_dangling_chain_stays_unowned() -> None:
    node = _agent(
        "build--plan",
        raw_suffix="node-suffix",
        agent_session="build",
        agent_session_role="root",
        plan_chain_root=True,
    )
    gate = _agent(
        "build--gate",
        raw_suffix="gate-suffix",
        parent_timestamp="missing-suffix",
        agent_session="build",
        agent_session_role="gate",
        gate_id="gate-1",
    )
    monitor = _agent(
        "build--mon",
        raw_suffix="mon-suffix",
        parent_timestamp=gate.raw_suffix,
        agent_session="build",
        agent_session_role="monitor",
        role_suffix="--mon",
        monitor_id="mon-1",
    )

    index = agent_node_projection_index([node, gate, monitor])

    assert index.owner_for_identity(gate.identity) is None
    assert index.owner_for_identity(monitor.identity) is None


def test_projection_index_keeps_workflow_step_child_out_of_keys() -> None:
    roster = _plan_agent_session_root_with_main_step_and_continuation()
    index = agent_node_projection_index(list(roster))
    node = roster[0]
    projection = index.by_node_identity[node.identity]

    assert (node.cl_name, node.raw_suffix) in projection.completion_keys
    assert ("main", node.raw_suffix) not in projection.completion_keys


def test_nested_monitors_do_not_cross_agent_sessions() -> None:
    first_node, first_gate, first_monitor = _gate_launch_agent_session()
    second_node = _agent(
        "other--plan",
        raw_suffix="other-node-suffix",
        agent_session="other",
        agent_session_role="root",
        plan_chain_root=True,
    )
    second_gate = _agent(
        "other--gate",
        raw_suffix="other-gate-suffix",
        parent_timestamp=second_node.raw_suffix,
        agent_session="other",
        agent_session_role="gate",
        gate_id="gate-2",
    )
    second_monitor = _agent(
        first_monitor.cl_name,
        raw_suffix="other-mon-suffix",
        parent_timestamp=second_gate.raw_suffix,
        agent_session="other",
        agent_session_role="monitor",
        role_suffix="--mon",
        monitor_id="mon-2",
    )

    index = agent_node_projection_index(
        [
            first_node,
            first_gate,
            first_monitor,
            second_node,
            second_gate,
            second_monitor,
        ]
    )

    assert (
        index.owner_for_identity(first_monitor.identity)
        is index.by_node_identity[first_node.identity]
    )
    assert (
        index.owner_for_identity(second_monitor.identity)
        is index.by_node_identity[second_node.identity]
    )
