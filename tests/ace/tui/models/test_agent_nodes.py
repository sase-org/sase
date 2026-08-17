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
            "family container",
            _agent(
                "build--plan",
                agent_family="build",
                agent_family_role="root",
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
            "family member shell",
            _agent(
                "build--code",
                parent_timestamp="suffix-build--plan",
                agent_family="build",
                agent_family_role="code",
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
                agent_family="build",
                agent_family_role="monitor",
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


def test_family_container_detection_counts_as_agent_node_after_member_load() -> None:
    root = _agent("build", agent_family="build", agent_family_role="root")
    child = _agent(
        "build--code",
        parent_timestamp=root.raw_suffix,
        agent_family="build",
        agent_family_role="code",
    )
    root.followup_agents = [child]

    assert root.is_family_container_row
    assert is_agents_tab_agent_node(root)
    assert not is_agents_tab_agent_node(child)


def _plan_family_root_with_main_step_and_continuation() -> tuple[Agent, Agent, Agent]:
    """Build the shape from the regression: a plan root whose ``main`` workflow
    step shares the root's own ``raw_suffix``, plus a real continuation member.
    """
    root = _agent(
        "gh_sase-org__sase",
        agent_family="gh_sase-org__sase",
        agent_family_role="root",
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
        agent_family="gh_sase-org__sase",
        agent_family_role="code",
    )
    root.runtime_children = [main_step, continuation]
    root.followup_agents = [main_step, continuation]
    return root, main_step, continuation


def test_plan_family_root_owns_its_key_not_its_main_step_key() -> None:
    root, _, continuation = _plan_family_root_with_main_step_and_continuation()

    keys = agent_node_completion_keys(root)

    assert (root.cl_name, root.raw_suffix) in keys
    assert (continuation.cl_name, continuation.raw_suffix) in keys
    assert ("main", root.raw_suffix) not in keys


def test_plan_family_root_projection_index_matches_its_own_key() -> None:
    root, main_step, continuation = _plan_family_root_with_main_step_and_continuation()
    index = agent_node_projection_index([root, main_step, continuation])
    projection = index.by_node_identity[root.identity]
    root_key = (root.cl_name, root.raw_suffix)

    assert root_key in projection.completion_keys
    assert projection_has_active_completion(projection, {root_key})


def test_standalone_node_yields_exactly_one_completion_key() -> None:
    solo = _agent("solo")

    keys = agent_node_completion_keys(solo)

    assert keys == ((solo.cl_name, solo.raw_suffix),)


def test_sequential_family_container_owns_member_keys_and_its_own_key() -> None:
    root = _agent(
        "alpha--0",
        agent_family="alpha",
        agent_family_role="root",
    )
    coder = _agent(
        "alpha--code",
        parent_timestamp=root.raw_suffix,
        agent_family="alpha",
        agent_family_role="code",
    )
    root.runtime_children = [coder]
    root.followup_agents = [coder]

    keys = agent_node_completion_keys(root)

    assert (root.cl_name, root.raw_suffix) in keys
    assert (coder.cl_name, coder.raw_suffix) in keys
