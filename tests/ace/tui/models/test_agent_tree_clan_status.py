"""Clan-container status mirrors a lone running member's refined label."""

from __future__ import annotations

from datetime import datetime

import pytest
from rich.text import Text

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


def test_clan_stays_running_when_two_members_are_running() -> None:
    members = [
        _testing_member(),
        _member("research.plain", "plain", status="RUNNING"),
        _member("research.done", "done", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "RUNNING"
    assert container.monitor_start_status is None
    assert container.monitor_stop_status is None
    assert container.monitor_state is None
    assert container.gate_start_status is None
    assert container.gate_stop_status is None
    assert container.gate_state is None
    assert container.gate_accent is None


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
    assert container.monitor_start_status is None
    assert container.monitor_stop_status is None
    assert container.monitor_state is None
    assert container.gate_start_status is None
    assert container.gate_stop_status is None
    assert container.gate_state is None
    assert container.gate_accent is None


def test_clan_stays_running_for_lone_starting_member() -> None:
    members = [
        _member("research.starting", "starting", status="STARTING"),
        _member("research.done", "done", status="DONE"),
    ]

    container, *_ = project_clan_tree(members)

    assert container.status == "RUNNING"


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
    assert reprojection.monitor_start_status is None
    assert reprojection.monitor_stop_status is None
    assert reprojection.monitor_state is None


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
