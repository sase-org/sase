"""Tests for _apply_status_overrides timestamp propagation."""

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


def test_apply_status_overrides_propagates_code_time_from_coder_child() -> None:
    """_apply_status_overrides sets parent.code_time from .code child."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        raw_suffix="20250615100000",
        role_suffix=".plan",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 10, 0),
        run_start_time=datetime(2025, 6, 15, 10, 10, 5),
        parent_timestamp="20250615100000",
        role_suffix=".code",
    )
    agents = [parent, child]
    _apply_status_overrides(agents)

    assert parent.code_time == datetime(2025, 6, 15, 10, 10, 5)


def test_apply_status_overrides_code_time_falls_back_to_start_time() -> None:
    """code_time uses start_time when run_start_time is None."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        raw_suffix="20250615100000",
        role_suffix=".plan",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 10, 0),
        parent_timestamp="20250615100000",
        role_suffix=".code",
    )
    agents = [parent, child]
    _apply_status_overrides(agents)

    assert parent.code_time == datetime(2025, 6, 15, 10, 10, 0)


def test_apply_status_overrides_propagates_epic_time() -> None:
    """_apply_status_overrides sets parent.epic_time from .epic child metadata."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        raw_suffix="20250615100000",
        role_suffix=".plan",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2025, 6, 15, 10, 10, 0),
        run_start_time=datetime(2025, 6, 15, 10, 10, 5),
        epic_time=datetime(2025, 6, 15, 10, 10, 7),
        parent_timestamp="20250615100000",
        role_suffix=".epic",
    )
    agents = [parent, child]
    _apply_status_overrides(agents)

    assert parent.epic_time == datetime(2025, 6, 15, 10, 10, 7)


def test_apply_status_overrides_epic_time_falls_back_to_run_start_time() -> None:
    """epic_time uses run_start_time when .epic child metadata is absent."""
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="DONE",
        start_time=datetime(2025, 6, 15, 10, 0, 0),
        raw_suffix="20250615100000",
        role_suffix=".plan",
    )
    child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2025, 6, 15, 10, 10, 0),
        run_start_time=datetime(2025, 6, 15, 10, 10, 5),
        parent_timestamp="20250615100000",
        role_suffix=".epic",
    )
    agents = [parent, child]
    _apply_status_overrides(agents)

    assert parent.epic_time == datetime(2025, 6, 15, 10, 10, 5)
