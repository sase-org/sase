"""Tests for distinguishing genuine PID duplicates from recycled PIDs."""

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from tests._agent_loader_helpers import _mock_agent_loader_sources
from tests._workspace_provider_helpers import patch_spy_metadata


@pytest.fixture(autouse=True)
def _register_spy_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_spy_metadata(monkeypatch)


def test_pid_reuse_keeps_both_running_agents_with_different_suffix() -> None:
    """A recycled PID does not merge agents with distinct artifact suffixes."""
    agent_a = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix="20260330120000",
        pid=55555,
    )
    agent_b = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="user-run",
        raw_suffix="20260330120500",
        pid=55555,
    )

    with _mock_agent_loader_sources(
        running_agents=[agent_a, agent_b],
        workflow_agents=[],
        process_is_running=True,
    ):
        result = load_all_agents()

    assert len(result) == 2
    suffixes = {agent.raw_suffix for agent in result}
    assert "20260330120000" in suffixes
    assert "20260330120500" in suffixes


def test_pid_reuse_merges_running_agents_with_same_suffix() -> None:
    """The same PID and artifact suffix identify a true duplicate."""
    agent_a = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix="20260330120000",
        pid=55555,
    )
    agent_b = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix="20260330120000",
        workspace_num=100,
        pid=55555,
    )

    with _mock_agent_loader_sources(
        running_agents=[agent_a, agent_b],
        workflow_agents=[],
        process_is_running=True,
    ):
        result = load_all_agents()

    assert len(result) == 1
    assert result[0].raw_suffix == "20260330120000"
    assert result[0].workspace_num == 100


def test_pid_reuse_merges_running_agents_with_missing_suffix() -> None:
    """A missing suffix retains the legacy merge fallback."""
    agent_a = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix="20260330120000",
        pid=55555,
    )
    agent_b = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_feature",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=None,
        workflow="fix_just",
        raw_suffix=None,
        workspace_num=100,
        pid=55555,
    )

    with _mock_agent_loader_sources(
        running_agents=[agent_a, agent_b],
        workflow_agents=[],
        process_is_running=True,
    ):
        result = load_all_agents()

    assert len(result) == 1
    assert result[0].workspace_num == 100
