"""Gate and queued-member clan status tests.

Lone gate presentation mirroring, queued admission-rank mirroring, and the
lone stopped-member label.
"""

from __future__ import annotations

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.agent.status_buckets import agent_status_bucket
from tests.ace.tui.models._agent_tree_clan_status_helpers import (
    format_member,
    make_base_agent,
    make_clan_member,
    style_at,
)

__all__ = [
    "test_clan_mirrors_lone_failed_gate_presentation",
    "test_clan_mirrors_lone_queued_agent_session_turn_rank",
    "test_clan_mirrors_lone_queued_member_admission_rank",
    "test_clan_mirrors_lone_running_member_gate_presentation",
    "test_clan_mirrors_lone_stopped_member_label",
    "test_clan_queued_rank_reprojection_clears_wait_display_source",
    "test_clan_two_queued_members_keep_generic_queued_without_rank",
    "test_clan_waiting_companions_do_not_block_lone_queued_rank",
]


def _queued_member(
    suffix: str,
    *,
    position: int | None = 3,
    queue_size: int | None = 4,
) -> Agent:
    row = make_clan_member(f"research.{suffix}", suffix, status="QUEUED")
    row.runner_slot_queue_position = position
    row.runner_slot_queue_size = queue_size
    return row


def test_clan_mirrors_lone_running_member_gate_presentation() -> None:
    members = [
        make_clan_member("research.done", "done", status="DONE"),
        make_clan_member(
            "research.gate",
            "gate",
            status="WORKING PLAN",
            status_bucket="Running",
            gate_start_status="WORKING PLAN",
            gate_stop_status="PLAN APPROVED",
            gate_state="settling",
            gate_accent="#FFAF5F",
        ),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "WORKING PLAN"
    assert agent_status_bucket(container) == "Running"
    assert container.gate_start_status == "WORKING PLAN"
    assert container.gate_stop_status == "PLAN APPROVED"
    assert container.gate_state == "settling"
    assert container.gate_accent == "#FFAF5F"


def test_clan_mirrors_lone_failed_gate_presentation() -> None:
    members = [
        make_clan_member("research.done", "done", status="DONE"),
        make_clan_member(
            "research.gate",
            "gate",
            status="PLAN REJECTED",
            status_bucket="Failed",
            gate_start_status="PLAN",
            gate_stop_status="PLAN REJECTED",
            gate_state="failed",
            gate_accent="#FFAF5F",
            gate_execution_active=True,
            gate_finalize_proc_id="proc-detach-1",
        ),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "PLAN REJECTED"
    assert agent_status_bucket(container) == "Failed"
    assert container.gate_start_status == "PLAN"
    assert container.gate_stop_status == "PLAN REJECTED"
    assert container.gate_state == "failed"
    assert container.gate_accent == "#FFAF5F"
    assert container.gate_execution_active is True
    assert container.gate_finalize_proc_id == "proc-detach-1"


def test_clan_mirrors_lone_queued_member_admission_rank() -> None:
    queued = _queued_member("land")
    members = [
        make_clan_member("research.one", "one", status="DONE"),
        make_clan_member("research.two", "two", status="DONE"),
        make_clan_member("research.three", "three", status="DONE"),
        queued,
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "QUEUED"
    assert container.wait_display_source is queued
    container_text = format_member(container)
    member_text = format_member(queued, 1)
    assert "(QUEUED #3/4)" in container_text.plain
    assert "[Q1 D3]" in container_text.plain
    assert style_at(container_text, container_text.plain.index("#3/4")) == (
        style_at(member_text, member_text.plain.index("#3/4"))
    )


def test_clan_two_queued_members_keep_generic_queued_without_rank() -> None:
    first = _queued_member("first", position=2)
    second = _queued_member("second", position=3)
    members = [first, second]

    container, *_ = project_clan_tree(members)

    assert container.status == "QUEUED"
    assert container.wait_display_source is None
    rendered = format_member(container).plain
    assert "(QUEUED)" in rendered
    assert "#" not in rendered
    assert "[Q2]" in rendered


def test_clan_waiting_companions_do_not_block_lone_queued_rank() -> None:
    queued = _queued_member("land")
    members = [
        queued,
        make_clan_member("research.waiting-a", "waiting-a", status="WAITING"),
        make_clan_member("research.waiting-b", "waiting-b", status="WAITING"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "QUEUED"
    assert container.wait_display_source is queued
    rendered = format_member(container).plain
    assert "(QUEUED #3/4)" in rendered
    assert "[Q1 W2]" in rendered


def test_clan_queued_rank_reprojection_clears_wait_display_source() -> None:
    queued = _queued_member("land")
    done_one = make_clan_member("research.one", "one", status="DONE")
    done_two = make_clan_member("research.two", "two", status="DONE")
    done_three = make_clan_member("research.three", "three", status="DONE")
    container, *members = project_clan_tree([done_one, done_two, done_three, queued])
    assert container.wait_display_source is queued

    queued.status = "DONE"
    queued.runner_slot_queue_position = None
    queued.runner_slot_queue_size = None
    reprojection, *_ = project_clan_tree([container, *members])

    assert reprojection.status == "DONE"
    assert reprojection.wait_display_source is None
    assert "#" not in format_member(reprojection).plain


def test_clan_mirrors_lone_queued_agent_session_turn_rank() -> None:
    agent_session_root = make_clan_member(
        "research.session", "session", status="QUEUED"
    )
    turn = make_base_agent(
        "research.session--code",
        "session-code",
        status="QUEUED",
        parent_timestamp=agent_session_root.raw_suffix,
        clan=None,
        generation=None,
    )
    turn.runner_slot_queue_position = 3
    turn.runner_slot_queue_size = 4
    agent_session_root.wait_display_source = turn
    members = [
        agent_session_root,
        turn,
        make_clan_member("research.one", "one", status="DONE"),
        make_clan_member("research.two", "two", status="DONE"),
        make_clan_member("research.three", "three", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "QUEUED"
    assert container.wait_display_source is turn
    container_text = format_member(container)
    turn_text = format_member(turn, 1)
    assert "(QUEUED #3/4)" in container_text.plain
    assert style_at(container_text, container_text.plain.index("#3/4")) == (
        style_at(turn_text, turn_text.plain.index("#3/4"))
    )


def test_clan_mirrors_lone_stopped_member_label() -> None:
    members = [
        make_clan_member("research.done", "done", status="DONE"),
        make_clan_member(
            "research.question",
            "question",
            status="WAITING INPUT",
            status_bucket="Stopped",
        ),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "WAITING INPUT"
    assert agent_status_bucket(container) == "Stopped"
