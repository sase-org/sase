"""Clan-container status mirrors a lone running member's refined label."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.text import Text

from sase.ace.tui.models._agent_clan import ClanStatusCounts
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.agent.status_buckets import agent_status_bucket

from ._agent_tree_helpers import _agent

_NOW = datetime(2026, 7, 17, 10, 5, 0)


def _style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


def _member(
    name: str,
    suffix: str,
    *,
    status: str,
    status_bucket: str | None = None,
    monitor_start_status: str | None = None,
    monitor_stop_status: str | None = None,
    monitor_state: str | None = None,
    gate_start_status: str | None = None,
    gate_stop_status: str | None = None,
    gate_state: str | None = None,
    gate_accent: str | None = None,
    gate_execution_active: bool = False,
    gate_finalize_proc_id: str | None = None,
) -> Agent:
    row = _agent(name, suffix, status=status)
    row.status_bucket = status_bucket
    row.monitor_start_status = monitor_start_status
    row.monitor_stop_status = monitor_stop_status
    row.monitor_state = monitor_state
    row.gate_start_status = gate_start_status
    row.gate_stop_status = gate_stop_status
    row.gate_state = gate_state
    row.gate_accent = gate_accent
    row.gate_execution_active = gate_execution_active
    row.gate_finalize_proc_id = gate_finalize_proc_id
    return row


def _testing_member(suffix: str = "testing") -> Agent:
    return _member(
        f"research.{suffix}",
        suffix,
        status="TESTING",
        status_bucket="Running",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
        monitor_state="running",
    )


def _format(agent: Agent, index: int = 0) -> Text:
    text, _, _ = format_agent_option(agent, index, is_selected=False, now=_NOW)
    return text


def _assert_shell_presentation_cleared(agent: Agent) -> None:
    assert agent.monitor_start_status is None
    assert agent.monitor_stop_status is None
    assert agent.monitor_state is None
    assert agent.gate_start_status is None
    assert agent.gate_stop_status is None
    assert agent.gate_state is None
    assert agent.gate_accent is None
    assert agent.gate_execution_active is False
    assert agent.gate_finalize_proc_id is None


def test_clan_mirrors_lone_testing_member_status_and_style() -> None:
    testing = _testing_member()
    members = [
        _member("research.one", "one", status="DONE"),
        _member("research.two", "two", status="DONE"),
        _member("research.waiting", "waiting", status="WAITING"),
        testing,
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "TESTING"
    assert agent_status_bucket(container) == "Running"
    assert container.monitor_start_status == "TESTING"
    assert container.monitor_stop_status == "TESTED"
    assert container.monitor_state == "running"
    container_text = _format(container)
    member_text = _format(testing, 1)
    assert container_text.plain.startswith("(TESTING")
    assert _style_at(container_text, container_text.plain.index("TESTING")) == (
        _style_at(member_text, member_text.plain.index("TESTING"))
    )


@pytest.mark.parametrize("monitor_state", ["failed", "timeout", "lost"])
def test_clan_mirrors_lone_failed_monitor_stop_label_and_counts(
    monitor_state: str,
) -> None:
    tested = _member(
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
        _member("research.waiting", "waiting", status="WAITING"),
        *(
            _member(f"research.done-{index}", f"done-{index}", status="DONE")
            for index in range(9)
        ),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "TESTED"
    assert agent_status_bucket(container) == "Failed"
    assert container.monitor_start_status == "TESTING"
    assert container.monitor_stop_status == "TESTED"
    assert container.monitor_state == monitor_state
    container_text = _format(container)
    member_text = _format(tested, 1)
    assert container_text.plain.startswith("(TESTED")
    assert "[W1 F1 D9]" in container_text.plain
    assert _style_at(container_text, container_text.plain.index("TESTED")) == (
        _style_at(member_text, member_text.plain.index("TESTED"))
    )


def test_clan_lone_failed_label_stays_in_failed_count_and_bucket() -> None:
    tested = _member(
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
            _member("research.waiting", "waiting", status="WAITING"),
            tested,
            _member("research.done", "done", status="DONE"),
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
        _testing_member(),
        _member("research.plain", "plain", status="RUNNING"),
        _member("research.done", "done", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "RUNNING"
    _assert_shell_presentation_cleared(container)


def test_clan_stays_running_for_lone_plain_running_member() -> None:
    members = [
        _member("research.plain", "plain", status="RUNNING"),
        _member("research.done", "done", status="DONE"),
        _member("research.waiting", "waiting", status="WAITING"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "RUNNING"


@pytest.mark.parametrize("higher", ["FAILED", "QUESTION", "PLAN"])
def test_clan_status_preserves_precedence_over_lone_running_member(
    higher: str,
) -> None:
    members = [
        _testing_member(),
        _member("research.higher", "higher", status=higher),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == higher
    _assert_shell_presentation_cleared(container)


def test_clan_stays_running_for_lone_starting_member() -> None:
    members = [
        _member("research.starting", "starting", status="STARTING"),
        _member("research.done", "done", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "RUNNING"


def test_clan_queued_and_waiting_companions_do_not_mask_lone_failed_label() -> None:
    members = [
        _member(
            "research.tested",
            "tested",
            status="TESTED",
            status_bucket="Failed",
            monitor_start_status="TESTING",
            monitor_stop_status="TESTED",
            monitor_state="failed",
        ),
        _member("research.queued", "queued", status="QUEUED"),
        _member("research.waiting", "waiting", status="WAITING"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "TESTED"
    assert agent_status_bucket(container) == "Failed"
    assert container.monitor_state == "failed"


def test_clan_duplicate_member_identity_does_not_create_competing_member() -> None:
    tested = _member(
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
                _member("research.failed-1", "failed-1", status="FAILED"),
                _member("research.failed-2", "failed-2", status="FAILED"),
            ],
            "FAILED",
        ),
        (
            [
                _member(
                    "research.tested",
                    "tested",
                    status="TESTED",
                    status_bucket="Failed",
                    monitor_start_status="TESTING",
                    monitor_stop_status="TESTED",
                    monitor_state="failed",
                ),
                _member("research.running", "running", status="RUNNING"),
            ],
            "FAILED",
        ),
        (
            [
                _member("research.question", "question", status="QUESTION"),
                _member("research.testing", "testing", status="TESTING"),
            ],
            "QUESTION",
        ),
        (
            [
                _member("research.plan", "plan", status="PLAN"),
                _member("research.testing", "testing", status="TESTING"),
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
    _assert_shell_presentation_cleared(container)


def test_clan_honors_effective_bucket_override() -> None:
    members = [
        _member(
            "research.tested",
            "tested",
            status="TESTED",
            status_bucket="Done",
        ),
        _member("research.done", "done", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "DONE"


def test_clan_all_waiting_members_keep_existing_fallback() -> None:
    waiting, *_ = project_clan_tree(
        [
            _member("research.waiting", "waiting", status="WAITING"),
            _member("research.queued", "queued", status="QUEUED"),
        ]
    )
    assert waiting.status == "QUEUED"
    _assert_shell_presentation_cleared(waiting)


def test_clan_status_reprojection_clears_stale_monitor_fields() -> None:
    testing = _testing_member()
    done_one = _member("research.one", "one", status="DONE")
    done_two = _member("research.two", "two", status="DONE")
    container, *members = project_clan_tree([done_one, done_two, testing])
    assert container.status == "TESTING"

    testing.status = "DONE"
    testing.status_bucket = None
    testing.monitor_state = "completed"
    reprojection, *_ = project_clan_tree([container, *members])

    assert reprojection.status == "DONE"
    _assert_shell_presentation_cleared(reprojection)


def test_clan_status_reprojection_clears_failed_source_after_second_member() -> None:
    tested = _member(
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

    second = _member("research.failed", "failed", status="FAILED")
    reprojection, *_ = project_clan_tree([container, *members, second])

    assert reprojection.status == "FAILED"
    assert agent_status_bucket(reprojection) == "Failed"
    _assert_shell_presentation_cleared(reprojection)


def test_clan_status_reprojection_replaces_failed_label_with_later_running_member() -> (
    None
):
    tested = _member(
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
    running = _testing_member("later")
    reprojection, *_ = project_clan_tree([container, *members, running])

    assert reprojection.status == "TESTING"
    assert agent_status_bucket(reprojection) == "Running"
    assert reprojection.monitor_state == "running"


def test_clan_mirrors_lone_running_member_gate_presentation() -> None:
    members = [
        _member("research.done", "done", status="DONE"),
        _member(
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
        _member("research.done", "done", status="DONE"),
        _member(
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


def test_clan_mirrors_lone_stopped_member_label() -> None:
    members = [
        _member("research.done", "done", status="DONE"),
        _member(
            "research.question",
            "question",
            status="WAITING INPUT",
            status_bucket="Stopped",
        ),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "WAITING INPUT"
    assert agent_status_bucket(container) == "Stopped"
