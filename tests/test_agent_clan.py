"""Rootless clan model and cleanup helpers."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._clan_cleanup import clan_members_for_container
from sase.ace.tui.models._agent_clan import (
    ClanStatusCounts,
    aggregate_clan_status,
    clan_member_counts,
    clan_members,
)
from sase.ace.tui.models.agent import Agent, AgentType


def _agent(name: str, status: str, *, suffix: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 7, 17, 10, 0, 0),
        raw_suffix=suffix,
        agent_name=name,
        agent_clan="research",
        agent_clan_generation="20260717100000",
    )


def test_clan_aggregation_keys_members_on_agent_clan() -> None:
    container = _agent("research", "RUNNING", suffix=None)
    running = _agent("research.one", "RUNNING", suffix="one")
    done = _agent("research.two", "DONE", suffix="two")
    outsider = _agent("other.one", "FAILED", suffix="other")
    outsider.agent_clan = "other"
    container.runtime_children = [running, done, outsider]

    assert clan_members(container) == (running, done)
    assert clan_member_counts(container) == ClanStatusCounts(running=1, done=1)
    assert aggregate_clan_status(
        member.status for member in clan_members(container)
    ) == ("RUNNING")


def test_clan_pending_plan_status_uses_review_priority() -> None:
    assert aggregate_clan_status(["PLAN", "TALE"]) == "TALE"
    assert aggregate_clan_status(["TALE", "EPIC"]) == "EPIC"
    assert aggregate_clan_status(["EPIC", "QUESTION"]) == "QUESTION"


def test_clan_queued_outranks_waiting() -> None:
    assert aggregate_clan_status(["QUEUED", "DONE"]) == "QUEUED"
    assert aggregate_clan_status(["QUEUED", "WAITING"]) == "QUEUED"


def test_clan_unread_counts_deduplicate_and_replace_successful_done() -> None:
    container = _agent("research", "FAILED", suffix=None)
    container.is_clan_container = True
    read_done = _agent("research.read", "DONE", suffix="read")
    unread_done = _agent("research.unread", "DONE", suffix="unread")
    unread_failed = _agent("research.failed", "FAILED", suffix="failed")
    wrong_generation = _agent("research.old", "DONE", suffix="old")
    wrong_generation.agent_clan_generation = "old-generation"
    container.runtime_children = [
        read_done,
        unread_done,
        unread_failed,
        unread_done,
        wrong_generation,
    ]

    counts = clan_member_counts(
        container,
        {unread_done.identity, unread_failed.identity, wrong_generation.identity},
    )

    assert clan_members(container) == (
        read_done,
        unread_done,
        unread_failed,
        unread_done,
    )
    assert counts == ClanStatusCounts(failed=1, unread=2, done=1)


def test_clan_queue_count_projects_parallel_member_behind_family() -> None:
    container = _agent("research", "WAITING", suffix=None)
    container.is_clan_container = True
    family = _agent("research.family", "WAITING", suffix="family")
    family.agent_family_parallel = True
    queued = _agent("research.family.phase", "QUEUED", suffix="phase")
    queued.agent_family_parallel = True
    queued.parent_timestamp = family.raw_suffix
    queued.pid = 100
    queued.wait_runners = 9
    queued.slot_requested_at = "2026-07-17T10:00:00Z"
    family.runtime_children = [queued]
    container.runtime_children = [family]

    counts = clan_member_counts(container)

    assert (counts.queued, counts.waiting) == (1, 0)


def test_clan_member_counts_ignores_slot_queued_leaf() -> None:
    leaf = _agent("solo", "WAITING", suffix="solo")
    leaf.agent_clan = None
    leaf.pid = 100
    leaf.wait_runners = 9
    leaf.wait_runners_explicit = True
    leaf.slot_requested_at = "2026-07-17T10:00:00Z"

    assert clan_member_counts(leaf) == ClanStatusCounts()


def test_cleanup_cascades_from_container_but_not_from_member() -> None:
    container = _agent("research", "RUNNING", suffix=None)
    container.is_clan_container = True
    one = _agent("research.one", "RUNNING", suffix="one")
    two = _agent("research.two", "WAITING", suffix="two")
    agents = [container, one, two]

    assert clan_members_for_container(container, agents) == [one, two]
    assert clan_members_for_container(one, agents) == []
