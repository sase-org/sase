"""Tests for loaded agent status override clearing."""

from datetime import datetime

import pytest

from sase.ace.tui.actions.agents._loading_helpers import (
    should_clear_loaded_agent_status_override,
)
from sase.ace.tui.models.agent import Agent, AgentType


def _agent(status: str, *, plan_action: str | None = None) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="agent",
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 6, 22, 9, 0, 0),
        raw_suffix="20260622090000",
        plan_action=plan_action,
    )


@pytest.mark.parametrize("override", ["PLAN APPROVED", "TALE APPROVED"])
@pytest.mark.parametrize("status", ["WORKING PLAN", "WORKING TALE"])
def test_approved_plan_override_clears_for_loaded_working_handoff_status(
    override: str,
    status: str,
) -> None:
    assert should_clear_loaded_agent_status_override(_agent(status), override) is True


@pytest.mark.parametrize("override", ["PLAN APPROVED", "TALE APPROVED"])
def test_approved_plan_override_stays_for_raw_running_status(override: str) -> None:
    assert (
        should_clear_loaded_agent_status_override(_agent("RUNNING"), override) is False
    )


@pytest.mark.parametrize("status", ["DONE", "PLAN DONE", "TALE DONE"])
def test_approved_plan_override_still_clears_for_terminal_statuses(status: str) -> None:
    assert (
        should_clear_loaded_agent_status_override(_agent(status), "TALE APPROVED")
        is True
    )


@pytest.mark.parametrize("override", ["PLAN", "TALE", "EPIC"])
@pytest.mark.parametrize(
    "status",
    [
        "PLAN APPROVED",
        "TALE APPROVED",
        "EPIC APPROVED",
        "PLAN COMMITTED",
        "WORKING PLAN",
        "WORKING TALE",
        "EPIC CREATED",
        "PLAN REJECTED",
        "FEEDBACK",
        "PLAN DONE",
        "TALE DONE",
        "DONE",
    ],
)
def test_pending_plan_override_clears_for_durable_post_review_status(
    override: str,
    status: str,
) -> None:
    assert should_clear_loaded_agent_status_override(_agent(status), override) is True


@pytest.mark.parametrize("override", ["PLAN", "TALE", "EPIC"])
@pytest.mark.parametrize("status", ["STARTING", "RUNNING", "WAITING"])
def test_pending_plan_override_stays_for_raw_pre_persistence_status(
    override: str,
    status: str,
) -> None:
    assert should_clear_loaded_agent_status_override(_agent(status), override) is False


@pytest.mark.parametrize("override", ["PLAN", "TALE", "EPIC"])
@pytest.mark.parametrize("status", ["PLAN", "TALE", "EPIC"])
def test_pending_plan_override_stays_for_loaded_pending_status(
    override: str,
    status: str,
) -> None:
    assert should_clear_loaded_agent_status_override(_agent(status), override) is False


@pytest.mark.parametrize("plan_action", ["approve", "tale", "epic", "commit"])
def test_pending_plan_override_clears_for_durable_plan_action(
    plan_action: str,
) -> None:
    assert (
        should_clear_loaded_agent_status_override(
            _agent("RUNNING", plan_action=plan_action),
            "TALE",
        )
        is True
    )
