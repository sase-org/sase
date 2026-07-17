"""Tests for parallel-family root status aggregation."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from sase.ace.tui.models._agent_parallel_family import (
    aggregate_parallel_family_status,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        (["WAITING", "FAILED", "QUESTION"], "QUESTION"),
        (["RUNNING", "FAILED", "PLAN"], "PLAN"),
        (["WAITING", "RUNNING", "FAILED"], "FAILED"),
        (["WAITING", "DONE", "RUNNING"], "RUNNING"),
        (["DONE", "WAITING"], "WAITING"),
        (["DONE", "STOPPED", "PLAN REJECTED"], "DONE"),
    ],
)
def test_aggregate_parallel_family_status_priority(
    statuses: list[str], expected: str
) -> None:
    assert aggregate_parallel_family_status(statuses) == expected


def _parallel_family() -> tuple[Agent, list[Agent]]:
    started = datetime(2026, 7, 16, 10, 0, 0)
    root = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="parallel-root",
        project_file="/tmp/test.sase",
        status="WAITING",
        start_time=started,
        raw_suffix="20260716100000",
        agent_name="parallel-root",
        agent_family="parallel-root",
        agent_family_role="root",
        agent_family_parallel=True,
    )
    members = [
        Agent(
            agent_type=AgentType.RUNNING,
            cl_name=f"parallel-member-{index}",
            project_file="/tmp/test.sase",
            status=status,
            start_time=started + timedelta(minutes=index),
            raw_suffix=f"20260716100{index}00",
            parent_timestamp=root.raw_suffix,
            agent_name=f"parallel-member-{index}",
            agent_family="parallel-root",
            agent_family_role="phase",
            agent_family_parallel=True,
        )
        for index, status in enumerate(("RUNNING", "DONE"), start=1)
    ]
    return root, members


def test_parallel_family_running_member_overrides_waiting_root() -> None:
    root, members = _parallel_family()

    _apply_status_overrides([root, *members])

    assert root.status == "RUNNING"
    assert root.agent_name == "parallel-root"


def test_parallel_family_wait_uses_member_wait_metadata() -> None:
    root, members = _parallel_family()
    root.status = "DONE"
    members[0].status = "WAITING"

    _apply_status_overrides([root, *members])

    assert root.status == "WAITING"
    assert root.wait_display_source is members[0]


def test_parallel_family_roles_do_not_trigger_serial_handoff_statuses() -> None:
    root, members = _parallel_family()
    root.status = "DONE"
    members[0].status = "DONE"
    members[0].agent_family_role = "code"

    _apply_status_overrides([root, *members])

    assert members[0].status == "DONE"
    assert root.status == "DONE"
