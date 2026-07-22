"""Tests for PID-based safety-net deduplication."""

import pytest

from sase.ace.agent_tribes import REVIEW_AGENT_TRIBE
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from tests._agent_loader_helpers import _mock_agent_loader_sources
from tests._workspace_provider_helpers import patch_spy_metadata


@pytest.fixture(autouse=True)
def _register_spy_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_spy_metadata(monkeypatch)


def test_pid_dedup_safety_net() -> None:
    """The final PID pass removes a less-specific duplicate agent."""
    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="some-workflow",
        raw_suffix="20260310173745",
        pid=12345,
    )
    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="some-other-workflow",
        raw_suffix=None,
        workspace_num=100,
        pid=12345,
    )

    with _mock_agent_loader_sources(
        running_agents=[running_agent],
        workflow_agents=[workflow_agent],
        process_is_running=True,
    ):
        result = load_all_agents()

    assert len(result) == 1
    assert result[0].agent_type == AgentType.WORKFLOW
    assert result[0].workspace_num == 100


def test_pid_dedup_merges_running_workflow_rows_for_same_artifact() -> None:
    """Same-suffix RUNNING and WORKFLOW projections remain one artifact row."""
    root_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="root",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="root-workflow",
        raw_suffix="20260310170000",
        pid=12345,
    )
    workflow_agent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="some-workflow",
        raw_suffix="20260310173745",
        pid=12345,
    )
    running_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="some-other-workflow",
        raw_suffix="20260310173745",
        workspace_num=100,
        pid=12345,
    )

    with _mock_agent_loader_sources(
        running_agents=[root_agent, running_agent],
        workflow_agents=[workflow_agent],
        process_is_running=True,
    ):
        result = load_all_agents()

    assert result == [root_agent, workflow_agent]
    assert workflow_agent.workspace_num == 100


def test_pid_dedup_safety_net_works_on_review_agents() -> None:
    """Review agents still deduplicate against a VCS row with the same PID."""
    fix_hook_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix-hook",
        raw_suffix="fix_hook-99999-260310_175213",
        pid=99999,
        tribe=REVIEW_AGENT_TRIBE,
    )
    vcs_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="spy-my_feature",
        raw_suffix=None,
        workspace_num=100,
        pid=99999,
    )

    with _mock_agent_loader_sources(
        running_agents=[fix_hook_agent, vcs_agent],
        workflow_agents=[],
        process_is_running=True,
    ):
        result = load_all_agents()

    pid_agents = [agent for agent in result if agent.pid == 99999]
    assert len(pid_agents) == 1
    assert pid_agents[0].workflow == "fix-hook"
    assert pid_agents[0].tribe == REVIEW_AGENT_TRIBE
