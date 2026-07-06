"""Tests for custom-role display labels over semantic statuses."""

from datetime import datetime

from sase.agent.status_buckets import status_bucket_for_values
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import _apply_status_overrides
from sase.ace.tui.models.agent_status import is_unread_completed_status
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option


def _root() -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="family",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 7, 6, 9, 0, 0),
        raw_suffix="20260706090000",
        role_suffix="--plan",
        agent_name="family",
        agent_family="family",
        agent_family_role="root",
        plan_chain_root=True,
    )


def _custom_child(
    *,
    status: str,
    start_time: datetime,
    label: str = "TESTING",
    done_label: str = "TESTED",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="family--tester",
        project_file="/tmp/test.sase",
        status=status,
        start_time=start_time,
        raw_suffix=start_time.strftime("%Y%m%d%H%M%S"),
        parent_timestamp="20260706090000",
        role_suffix="--tester",
        agent_name="family--tester",
        agent_family="family",
        agent_family_role="tester",
        custom_role_label=label,
        custom_role_done_label=done_label,
    )


def test_running_custom_role_label_keeps_running_bucket_and_mirrors_root() -> None:
    parent = _root()
    child = _custom_child(
        status="RUNNING",
        start_time=datetime(2026, 7, 6, 9, 10, 0),
        label="TESTING",
    )

    _apply_status_overrides([parent, child])

    assert child.status == "RUNNING"
    assert child.display_status == "TESTING"
    assert status_bucket_for_values(child.status) == "Running"
    assert parent.status == "RUNNING"
    assert parent.display_status == "TESTING"


def test_done_custom_role_label_keeps_done_bucket_and_dismissibility() -> None:
    parent = _root()
    child = _custom_child(
        status="DONE",
        start_time=datetime(2026, 7, 6, 9, 10, 0),
        done_label="TESTED",
    )

    _apply_status_overrides([parent, child])

    assert child.status == "DONE"
    assert child.display_status == "TESTED"
    assert status_bucket_for_values(child.status) == "Done"
    assert is_unread_completed_status(child.status)
    assert parent.status == "DONE"
    assert parent.display_status == "TESTED"


def test_custom_role_label_does_not_override_blocked_semantics() -> None:
    parent = _root()
    child = _custom_child(
        status="DONE",
        start_time=datetime(2026, 7, 6, 9, 10, 0),
        label="TESTING",
        done_label="TESTED",
    )
    child.questions_times = [datetime(2026, 7, 6, 9, 12, 0)]

    _apply_status_overrides([parent, child])

    assert child.status == "QUESTION"
    assert child.display_status == "QUESTION"
    assert status_bucket_for_values(child.status) == "Stopped"
    assert parent.status == "QUESTION"
    assert parent.display_status == "QUESTION"


def test_agent_row_renders_custom_role_label_not_semantic_status() -> None:
    agent = _custom_child(
        status="DONE",
        start_time=datetime(2026, 7, 6, 9, 10, 0),
        done_label="TESTED",
    )

    left, _suffix, _option_id = format_agent_option(
        agent,
        0,
        is_selected=False,
    )

    assert "TESTED" in left.plain
    assert "(DONE)" not in left.plain
