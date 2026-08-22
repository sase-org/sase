"""Sequential family-member status projection tests."""

from __future__ import annotations

from sase.ace.tui.models.agent_family_members import (
    concrete_agent_statuses,
    family_member_status_buckets,
)

from ._agent_family_members_helpers import _agent


def test_approved_non_final_family_member_projects_done() -> None:
    planner = _agent(
        "alpha--plan",
        role="plan",
        status="TALE APPROVED",
    )
    coder = _agent(
        "alpha--code",
        role="code",
        status="WORKING TALE",
    )

    assert family_member_status_buckets((planner, coder)) == ("Done", "Running")


def test_approved_final_family_member_keeps_global_running_bucket() -> None:
    planner = _agent(
        "alpha--plan",
        role="plan",
        status="PLAN APPROVED",
    )

    assert family_member_status_buckets((planner,)) == ("Running",)


def test_custom_final_family_member_bucket_override_wins() -> None:
    monitor = _agent(
        "alpha--mon",
        role="monitor",
        status="MONITORED",
        status_bucket="Done",
    )

    assert family_member_status_buckets((monitor,)) == ("Done",)
    assert concrete_agent_statuses(monitor) == ()


def test_stopped_non_final_family_member_projects_done() -> None:
    planner = _agent(
        "alpha--plan",
        role="plan",
        status="ANSWERED",
        stop_offset=1,
    )
    coder = _agent(
        "alpha--1",
        role="code",
        status="DONE",
    )

    assert family_member_status_buckets((planner, coder)) == ("Done", "Done")


def test_unknown_status_on_stopped_non_final_member_projects_done() -> None:
    predecessor = _agent(
        "alpha--0",
        role="root",
        status="SOME NEW STATUS",
        stop_offset=1,
    )
    successor = _agent(
        "alpha--1",
        role="code",
        status="DONE",
    )

    assert family_member_status_buckets((predecessor, successor)) == (
        "Done",
        "Done",
    )


def test_running_non_final_family_member_keeps_running_bucket() -> None:
    predecessor = _agent(
        "alpha--0",
        role="root",
        status="RUNNING",
    )
    successor = _agent(
        "alpha--reviewer",
        role="review",
        status="WAITING",
    )

    assert family_member_status_buckets((predecessor, successor)) == (
        "Running",
        "Waiting",
    )


def test_failed_and_question_non_final_members_keep_their_buckets() -> None:
    successor = _agent(
        "alpha--1",
        role="code",
        status="DONE",
    )
    failed = _agent(
        "alpha--failed",
        role="root",
        status="FAILED",
        stop_offset=1,
    )
    question = _agent(
        "alpha--question",
        role="root",
        status="QUESTION",
    )

    assert family_member_status_buckets((failed, successor)) == (
        "Failed",
        "Done",
    )
    assert family_member_status_buckets((question, successor)) == (
        "Stopped",
        "Done",
    )
