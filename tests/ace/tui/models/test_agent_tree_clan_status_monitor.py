"""Lone monitor/running-member clan status tests.

Lone TESTING/TESTED/STARTING members, running precedence, and status
reprojection for the clan container.
"""

from __future__ import annotations

import pytest

from sase.ace.tui.models._agent_clan import ClanStatusCounts
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.agent.status_buckets import agent_status_bucket
from tests.ace.tui.models._agent_tree_clan_status_helpers import (
    assert_turn_presentation_cleared,
    format_member,
    make_clan_member,
    make_testing_member,
    style_at,
)

__all__ = [
    "test_clan_all_waiting_members_keep_existing_fallback",
    "test_clan_duplicate_member_identity_does_not_create_competing_member",
    "test_clan_honors_effective_bucket_override",
    "test_clan_lone_failed_label_stays_in_failed_count_and_bucket",
    "test_clan_mirrors_lone_failed_monitor_stop_label_and_counts",
    "test_clan_mirrors_lone_starting_member",
    "test_clan_mirrors_lone_testing_member_status_and_style",
    "test_clan_multiple_relevant_members_keep_canonical_aggregate",
    "test_clan_queued_and_waiting_companions_do_not_mask_lone_failed_label",
    "test_clan_status_preserves_precedence_over_lone_running_member",
    "test_clan_status_reprojection_clears_failed_source_after_second_member",
    "test_clan_status_reprojection_clears_stale_monitor_fields",
    "test_clan_status_reprojection_replaces_failed_label_with_later_running_member",
    "test_clan_stays_running_for_lone_plain_running_member",
    "test_clan_stays_running_when_two_members_are_running",
]


def test_clan_mirrors_lone_testing_member_status_and_style() -> None:
    testing = make_testing_member()
    members = [
        make_clan_member("research.one", "one", status="DONE"),
        make_clan_member("research.two", "two", status="DONE"),
        make_clan_member("research.waiting", "waiting", status="WAITING"),
        testing,
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "TESTING"
    assert agent_status_bucket(container) == "Running"
    assert container.monitor_start_status == "TESTING"
    assert container.monitor_stop_status == "TESTED"
    assert container.monitor_state == "running"
    container_text = format_member(container)
    member_text = format_member(testing, 1)
    assert container_text.plain.startswith("(TESTING")
    assert style_at(container_text, container_text.plain.index("TESTING")) == (
        style_at(member_text, member_text.plain.index("TESTING"))
    )


@pytest.mark.parametrize("monitor_state", ["failed", "timeout", "lost"])
def test_clan_mirrors_lone_failed_monitor_stop_label_and_counts(
    monitor_state: str,
) -> None:
    tested = make_clan_member(
        "research.tested",
        "tested",
        status="TESTED",
        status_bucket="Failed",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state=monitor_state,
    )
    members = [
        tested,
        make_clan_member("research.waiting", "waiting", status="WAITING"),
        *(
            make_clan_member(f"research.done-{index}", f"done-{index}", status="DONE")
            for index in range(9)
        ),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "TESTED"
    assert agent_status_bucket(container) == "Failed"
    assert container.monitor_start_status == "TESTING"
    assert container.monitor_stop_status == "TESTED"
    assert container.monitor_state == monitor_state
    container_text = format_member(container)
    member_text = format_member(tested, 1)
    assert container_text.plain.startswith("(TESTED")
    assert "[W1 F1 D9]" in container_text.plain
    assert style_at(container_text, container_text.plain.index("TESTED")) == (
        style_at(member_text, member_text.plain.index("TESTED"))
    )


def test_clan_lone_failed_label_stays_in_failed_count_and_bucket() -> None:
    tested = make_clan_member(
        "research.tested",
        "tested",
        status="TESTED",
        status_bucket="Failed",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state="failed",
    )
    container, *_ = project_clan_tree(
        [
            make_clan_member("research.waiting", "waiting", status="WAITING"),
            tested,
            make_clan_member("research.done", "done", status="DONE"),
        ]
    )

    assert container.status == "TESTED"
    assert agent_status_bucket(container) == "Failed"
    rendered = format_agent_option(
        container,
        0,
        is_selected=False,
        clan_counts=ClanStatusCounts(failed=1, waiting=1, done=1),
    )[0].plain
    assert rendered.startswith("(TESTED) [W1 F1 D1]")


def test_clan_stays_running_when_two_members_are_running() -> None:
    members = [
        make_testing_member(),
        make_clan_member("research.plain", "plain", status="RUNNING"),
        make_clan_member("research.done", "done", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "RUNNING"
    assert_turn_presentation_cleared(container)


def test_clan_stays_running_for_lone_plain_running_member() -> None:
    members = [
        make_clan_member("research.plain", "plain", status="RUNNING"),
        make_clan_member("research.done", "done", status="DONE"),
        make_clan_member("research.waiting", "waiting", status="WAITING"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "RUNNING"


@pytest.mark.parametrize("higher", ["FAILED", "QUESTION", "PLAN"])
def test_clan_status_preserves_precedence_over_lone_running_member(
    higher: str,
) -> None:
    members = [
        make_testing_member(),
        make_clan_member("research.higher", "higher", status=higher),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == higher
    assert container.status_display_source is None
    assert_turn_presentation_cleared(container)


def test_clan_mirrors_lone_starting_member() -> None:
    starting = make_clan_member("research.starting", "starting", status="STARTING")
    members = [
        starting,
        make_clan_member("research.done", "done", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "STARTING"
    assert agent_status_bucket(container) == "Starting"
    assert container.status_display_source is starting
    container_text = format_member(container)
    member_text = format_member(starting, 1)
    assert container_text.plain.startswith("(STARTING")
    assert style_at(container_text, container_text.plain.index("STARTING")) == (
        style_at(member_text, member_text.plain.index("STARTING"))
    )


def test_clan_queued_and_waiting_companions_do_not_mask_lone_failed_label() -> None:
    members = [
        make_clan_member(
            "research.tested",
            "tested",
            status="TESTED",
            status_bucket="Failed",
            monitor_start_status="TESTING",
            monitor_stop_status="TESTED",
            monitor_state="failed",
        ),
        make_clan_member("research.queued", "queued", status="QUEUED"),
        make_clan_member("research.waiting", "waiting", status="WAITING"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "TESTED"
    assert agent_status_bucket(container) == "Failed"
    assert container.monitor_state == "failed"
    assert container.wait_display_source is None


def test_clan_duplicate_member_identity_does_not_create_competing_member() -> None:
    tested = make_clan_member(
        "research.tested",
        "tested",
        status="TESTED",
        status_bucket="Failed",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state="failed",
    )

    container, *_ = project_clan_tree([tested, tested])

    assert container.status == "TESTED"
    assert agent_status_bucket(container) == "Failed"
    assert container.monitor_state == "failed"


@pytest.mark.parametrize(
    ("members", "expected_status"),
    [
        (
            [
                make_clan_member("research.failed-1", "failed-1", status="FAILED"),
                make_clan_member("research.failed-2", "failed-2", status="FAILED"),
            ],
            "FAILED",
        ),
        (
            [
                make_clan_member(
                    "research.tested",
                    "tested",
                    status="TESTED",
                    status_bucket="Failed",
                    monitor_start_status="TESTING",
                    monitor_stop_status="TESTED",
                    monitor_state="failed",
                ),
                make_clan_member("research.running", "running", status="RUNNING"),
            ],
            "FAILED",
        ),
        (
            [
                make_clan_member("research.question", "question", status="QUESTION"),
                make_clan_member("research.testing", "testing", status="TESTING"),
            ],
            "QUESTION",
        ),
        (
            [
                make_clan_member("research.plan", "plan", status="PLAN"),
                make_clan_member("research.testing", "testing", status="TESTING"),
            ],
            "PLAN",
        ),
    ],
)
def test_clan_multiple_relevant_members_keep_canonical_aggregate(
    members: list[Agent],
    expected_status: str,
) -> None:
    container, *_ = project_clan_tree(members)

    assert container.status == expected_status
    assert_turn_presentation_cleared(container)


def test_clan_honors_effective_bucket_override() -> None:
    members = [
        make_clan_member(
            "research.tested",
            "tested",
            status="TESTED",
            status_bucket="Done",
        ),
        make_clan_member("research.done", "done", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "DONE"


def test_clan_all_waiting_members_keep_existing_fallback() -> None:
    waiting, *_ = project_clan_tree(
        [
            make_clan_member("research.waiting", "waiting", status="WAITING"),
            make_clan_member("research.queued", "queued", status="QUEUED"),
        ]
    )
    assert waiting.status == "QUEUED"
    assert_turn_presentation_cleared(waiting)


def test_clan_status_reprojection_clears_stale_monitor_fields() -> None:
    testing = make_testing_member()
    done_one = make_clan_member("research.one", "one", status="DONE")
    done_two = make_clan_member("research.two", "two", status="DONE")
    container, *members = project_clan_tree([done_one, done_two, testing])
    assert container.status == "TESTING"

    testing.status = "DONE"
    testing.status_bucket = None
    testing.monitor_state = "completed"
    reprojection, *_ = project_clan_tree([container, *members])

    assert reprojection.status == "DONE"
    assert_turn_presentation_cleared(reprojection)


def test_clan_status_reprojection_clears_failed_source_after_second_member() -> None:
    tested = make_clan_member(
        "research.tested",
        "tested",
        status="TESTED",
        status_bucket="Failed",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state="failed",
    )
    container, *members = project_clan_tree([tested])
    assert container.status == "TESTED"
    assert container.monitor_state == "failed"

    second = make_clan_member("research.failed", "failed", status="FAILED")
    reprojection, *_ = project_clan_tree([container, *members, second])

    assert reprojection.status == "FAILED"
    assert agent_status_bucket(reprojection) == "Failed"
    assert_turn_presentation_cleared(reprojection)


def test_clan_status_reprojection_replaces_failed_label_with_later_running_member() -> (
    None
):
    tested = make_clan_member(
        "research.tested",
        "tested",
        status="TESTED",
        status_bucket="Failed",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state="failed",
    )
    container, *members = project_clan_tree([tested])
    assert container.status == "TESTED"

    tested.status = "DONE"
    tested.status_bucket = None
    tested.monitor_state = "completed"
    running = make_testing_member("later")
    reprojection, *_ = project_clan_tree([container, *members, running])

    assert reprojection.status == "TESTING"
    assert agent_status_bucket(reprojection) == "Running"
    assert reprojection.monitor_state == "running"
