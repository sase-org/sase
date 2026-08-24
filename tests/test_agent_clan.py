"""Rootless clan model and cleanup helpers."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._clan_cleanup import clan_members_for_container
from sase.ace.tui.models._agent_clan import (
    ClanStatusCounts,
    aggregate_clan_status,
    clan_current_lane_rows,
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
    container.is_clan_container = True
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


def test_clan_queue_count_uses_parallel_family_root() -> None:
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

    assert (counts.queued, counts.waiting) == (0, 1)


def test_clan_member_counts_ignores_slot_queued_leaf() -> None:
    leaf = _agent("solo", "WAITING", suffix="solo")
    leaf.agent_clan = None
    leaf.pid = 100
    leaf.wait_runners = 9
    leaf.wait_runners_explicit = True
    leaf.slot_requested_at = "2026-07-17T10:00:00Z"

    assert clan_member_counts(leaf) == ClanStatusCounts()


def test_clan_current_lane_rows_single_shell_lane_represents_itself() -> None:
    container = _agent("research", "RUNNING", suffix=None)
    container.is_clan_container = True
    running = _agent("research.one", "RUNNING", suffix="one")
    container.runtime_children = [running]

    assert clan_current_lane_rows(container) == (running,)


def test_clan_current_lane_rows_family_lane_resolves_to_current_shell() -> None:
    container = _agent("research", "RUNNING", suffix=None)
    container.is_clan_container = True
    root = _agent("research.family", "DONE", suffix="root")
    root.agent_name = "family--0"
    root.agent_family = "family"
    root.agent_family_role = "root"
    root.stop_time = datetime(2026, 7, 19, 9, 1, 0)
    coder = _agent("research.family.code", "RUNNING", suffix="coder")
    coder.agent_name = "family--code"
    coder.parent_timestamp = root.raw_suffix
    coder.agent_family = "family"
    coder.agent_family_role = "code"
    root.runtime_children = [coder]
    root.followup_agents = [coder]
    container.runtime_children = [root]

    assert clan_current_lane_rows(container) == (coder,)


def test_clan_current_lane_rows_family_lane_resolves_to_running_monitor() -> None:
    container = _agent("research", "RUNNING", suffix=None)
    container.is_clan_container = True
    root = _agent("research.family", "DONE", suffix="root")
    root.agent_name = "family--0"
    root.agent_family = "family"
    root.agent_family_role = "root"
    root.stop_time = datetime(2026, 7, 19, 9, 1, 0)
    coder = _agent("research.family.code", "DONE", suffix="coder")
    coder.agent_name = "family--code"
    coder.parent_timestamp = root.raw_suffix
    coder.agent_family = "family"
    coder.agent_family_role = "code"
    coder.stop_time = datetime(2026, 7, 19, 9, 2, 0)
    monitor = _agent("research.family.mon", "MONITORING", suffix="monitor")
    monitor.agent_name = "family--mon"
    monitor.parent_timestamp = coder.raw_suffix
    monitor.agent_family = "family"
    monitor.agent_family_role = "monitor"
    monitor.role_suffix = "--mon"
    monitor.monitor_id = "m-family"
    monitor.monitor_state = "running"
    root.runtime_children = [coder]
    root.followup_agents = [coder]
    coder.runtime_children = [monitor]
    coder.followup_agents = [monitor]
    container.runtime_children = [root]

    assert clan_current_lane_rows(container) == (monitor,)


def test_clan_current_lane_rows_skips_settled_waiting_failed_lanes() -> None:
    container = _agent("research", "RUNNING", suffix=None)
    container.is_clan_container = True
    done = _agent("research.done", "DONE", suffix="done")
    waiting = _agent("research.waiting", "WAITING", suffix="waiting")
    failed = _agent("research.failed", "FAILED", suffix="failed")
    container.runtime_children = [done, waiting, failed]

    assert clan_current_lane_rows(container) == ()


def test_clan_current_lane_rows_excludes_other_clan_and_generation() -> None:
    container = _agent("research", "RUNNING", suffix=None)
    container.is_clan_container = True
    running = _agent("research.one", "RUNNING", suffix="one")
    other_clan = _agent("other.one", "RUNNING", suffix="other")
    other_clan.agent_clan = "other"
    wrong_generation = _agent("research.old", "RUNNING", suffix="old")
    wrong_generation.agent_clan_generation = "old-generation"
    container.runtime_children = [running, other_clan, wrong_generation]

    assert clan_current_lane_rows(container) == (running,)


def test_clan_current_lane_rows_returns_empty_for_non_clan_row() -> None:
    leaf = _agent("solo", "RUNNING", suffix="solo")

    assert clan_current_lane_rows(leaf) == ()


def test_cleanup_cascades_from_container_but_not_from_member() -> None:
    container = _agent("research", "RUNNING", suffix=None)
    container.is_clan_container = True
    one = _agent("research.one", "RUNNING", suffix="one")
    two = _agent("research.two", "WAITING", suffix="two")
    agents = [container, one, two]

    assert clan_members_for_container(container, agents) == [one, two]
    assert clan_members_for_container(one, agents) == []
