"""Tests for PID-based safety-net deduplication."""

import pytest

from sase.ace.agent_tribes import REVIEW_AGENT_TRIBE
from sase.ace.tui.models._dedup import dedup_by_pid
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import load_all_agents
from tests._agent_loader_helpers import _mock_agent_loader_sources
from tests._workspace_provider_helpers import patch_spy_metadata


@pytest.fixture(autouse=True)
def _register_spy_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_spy_metadata(monkeypatch)


def _pre_metadata_duplicate_pair() -> tuple[Agent, Agent]:
    child_ts = "20260829072911"
    generation = "20260829061525"
    stale = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="gh_sase-org__sase",
        project_file="/tmp/projects/sase/sase.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix=child_ts,
        pid=3473413,
        runner_is_live=True,
    )
    fresh = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="gh_sase-org__sase",
        project_file="/tmp/projects/sase/sase.sase",
        status="RUNNING",
        start_time=None,
        raw_suffix=child_ts,
        pid=3473413,
        runner_is_live=True,
        agent_name="toobig-4j.test_workflow_executor.0--1",
        parent_timestamp="20260829061545",
        agent_family="toobig-4j.test_workflow_executor.0",
        agent_family_role="root",
        role_suffix="--1",
        agent_clan="toobig-4j",
        agent_clan_generation=generation,
        clan_tribe="chop",
        tribe="chop",
    )
    return stale, fresh


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


@pytest.mark.parametrize("fresh_first", [False, True])
def test_pid_dedup_preserves_structural_placement_fields(
    fresh_first: bool,
) -> None:
    """PID collapse must not discard placement metadata from the removed row."""
    stale, fresh = _pre_metadata_duplicate_pair()
    agents = [fresh, stale] if fresh_first else [stale, fresh]

    result = dedup_by_pid(agents)

    assert len(result) == 1
    survivor = result[0]
    assert survivor.agent_clan == "toobig-4j"
    assert survivor.agent_clan_generation == "20260829061525"
    assert survivor.parent_timestamp == "20260829061545"
    assert survivor.agent_family == "toobig-4j.test_workflow_executor.0"
    assert survivor.role_suffix == "--1"
    assert survivor.tribe == "chop"
    assert survivor.is_child_row is True


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
