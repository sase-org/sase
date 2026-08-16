"""Agents-tab agent-node taxonomy tests."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_nodes import is_agents_tab_agent_node

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
