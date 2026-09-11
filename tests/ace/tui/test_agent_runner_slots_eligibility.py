"""Tests for runner-slot status transitions, queue eligibility, and chip display."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

from sase.ace.tui.agent_count_chip import format_agent_count_chip
from sase.ace.tui.models._agent_clan import sase_agent_status_counts
from sase.ace.tui.models.agent_runner_slots import (
    RunnerCapacitySnapshot,
    refresh_runner_slot_context,
)
from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel

from ._agent_runner_slots_helpers import _agent, _assert_capacity_metrics


def test_question_paused_root_is_excluded_from_displayed_occupancy() -> None:
    running = _agent(
        "running",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
    )
    paused = _agent(
        "paused",
        status="QUESTION",
        run_start_time=datetime(2026, 7, 12, 11, 58),
        runner_slot_yielded=True,
    )
    answered_waiter = _agent(
        "answered",
        status="WAITING",
        run_start_time=datetime(2026, 7, 12, 11, 57),
        runner_slot_yielded=True,
        wait_runners=1,
        slot_requested_at="2026-07-12T12:00:01Z",
    )

    capacity = refresh_runner_slot_context(
        [running, paused, answered_waiter], effective_limit=10
    )

    _assert_capacity_metrics(capacity, (10, 1, 1))
    assert answered_waiter.runner_slots_in_use == 1
    assert answered_waiter.runner_slot_queue_position == 1


def test_runner_capacity_empty_pool_and_neutral_fallback() -> None:
    assert refresh_runner_slot_context([], effective_limit=7) == (
        RunnerCapacitySnapshot(7, 0, 0, occupied_capacity=0.0)
    )
    assert refresh_runner_slot_context([]) == RunnerCapacitySnapshot()


def test_runner_capacity_excludes_only_non_slot_waits_from_queue() -> None:
    implicit = _agent(
        "implicit",
        wait_runners=9,
        wait_runners_explicit=False,
        slot_requested_at="2026-07-12T12:00:01Z",
    )
    explicit = _agent(
        "explicit",
        wait_runners=0,
        wait_runners_explicit=True,
        slot_requested_at="2026-07-12T12:00:02Z",
    )
    dependency_wait = _agent(
        "dependency",
        waiting_for=["other-agent"],
        slot_requested_at=None,
    )

    capacity = refresh_runner_slot_context(
        [explicit, dependency_wait, implicit], effective_limit=10
    )

    _assert_capacity_metrics(capacity, (10, 0, 2))
    assert implicit.runner_slot_queue_position == 1
    assert explicit.runner_slot_queue_position == 2
    assert implicit.runner_slot_queue_size == 2
    assert explicit.runner_slot_queue_size == 2
    assert dependency_wait.runner_slot_queue_position is None


def test_slot_queue_derivation_matches_capacity_and_rejects_other_waits() -> None:
    implicit = _agent(
        "implicit",
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    explicit = _agent(
        "explicit",
        wait_runners=0,
        wait_runners_explicit=True,
        slot_requested_at="2026-07-12T12:00:01Z",
    )
    dependency = _agent("dependency", waiting_for=["other"], slot_requested_at=None)
    dead = _agent(
        "dead",
        pid=None,
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:02Z",
    )
    yielded_question = _agent(
        "question",
        status="QUESTION",
        runner_slot_yielded=True,
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:03Z",
    )
    serial_child = _agent(
        "serial-child",
        parent_timestamp="parent",
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:04Z",
    )
    clan_container = _agent(
        "clan",
        is_clan_container=True,
        agent_clan="clan",
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:05Z",
    )
    agents = [
        implicit,
        explicit,
        dependency,
        dead,
        yielded_question,
        serial_child,
        clan_container,
    ]

    capacity = refresh_runner_slot_context(
        agents,
        effective_limit=10,
    )
    assert [agent.status for agent in agents] == [
        "QUEUED",
        "QUEUED",
        "WAITING",
        "WAITING",
        "QUESTION",
        "QUEUED",
        "WAITING",
    ]
    assert capacity.queued_count == sum(agent.status == "QUEUED" for agent in agents)


def test_runner_slot_status_promotion_demotion_and_idempotence() -> None:
    implicit = _agent(
        "implicit",
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    explicit = _agent(
        "explicit",
        wait_runners=0,
        wait_runners_explicit=True,
        slot_requested_at="2026-07-12T12:00:01Z",
    )

    first = refresh_runner_slot_context([implicit, explicit], effective_limit=10)
    _assert_capacity_metrics(first, (10, 0, 2))
    assert (implicit.status, explicit.status) == ("QUEUED", "QUEUED")
    assert (
        implicit.runner_slot_queue_position,
        explicit.runner_slot_queue_position,
    ) == (
        1,
        2,
    )

    second = refresh_runner_slot_context([implicit, explicit], effective_limit=10)
    assert second == first
    assert (implicit.status, explicit.status) == ("QUEUED", "QUEUED")
    assert (
        implicit.runner_slot_queue_position,
        explicit.runner_slot_queue_position,
    ) == (
        1,
        2,
    )

    implicit.wait_runners_explicit = True
    third = refresh_runner_slot_context([implicit, explicit], effective_limit=10)
    _assert_capacity_metrics(third, (10, 0, 2))
    assert implicit.status == "QUEUED"


def test_stale_queued_status_demotes_without_a_live_slot_request() -> None:
    agent = _agent("stale", status="QUEUED", slot_requested_at=None)

    capacity = refresh_runner_slot_context([agent], effective_limit=10)

    assert capacity == RunnerCapacitySnapshot(10, 0, 0, occupied_capacity=0.0)
    assert agent.status == "WAITING"


def test_queued_rows_match_chip_header_summary_and_capacity_counts() -> None:
    first = _agent(
        "first",
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    second = _agent(
        "second",
        wait_runners=0,
        wait_runners_explicit=True,
        slot_requested_at="2026-07-12T12:00:01Z",
    )
    blocked = _agent("blocked", waiting_for=["dependency"])
    agents = [first, second, blocked]

    capacity = refresh_runner_slot_context(agents, effective_limit=10)
    displayed_queued = sum(agent.status == "QUEUED" for agent in agents)
    counts = sase_agent_status_counts(agents, ())
    chip = format_agent_count_chip(
        queued=counts.queued,
        waiting=counts.waiting,
    )
    panel = AgentInfoPanel()
    panel._runner_limit = capacity.effective_limit
    panel._running_count = capacity.slots_in_use
    panel._runner_queue_count = capacity.queued_count
    captured: list[str] = []
    with patch.object(
        panel,
        "update",
        lambda text, **_kwargs: captured.append(text.plain),
    ):
        panel._update_display()

    assert displayed_queued == 2
    assert counts.queued == displayed_queued
    assert capacity.queued_count == displayed_queued == len(capacity.queue)
    assert "Q2" in chip.plain
    assert "2 queued" in captured[-1]


def test_runner_capacity_counts_only_live_rows_and_excludes_yielded_question() -> None:
    """The loader has already PID-filtered active rows before this runs.

    ``refresh_runner_slot_context`` derives ``R`` from each row's own
    ``status``/``status_bucket`` (via ``sase_agent_status_counts``), not from
    re-checking ``pid`` liveness -- that check already happened upstream, so
    a dead waiter's queue-eligibility (still pid-gated, unchanged) and a
    yielded QUESTION row are what this covers now.
    """
    live_holder = _agent(
        "live-holder",
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 59),
    )
    dead_waiter = _agent(
        "dead-waiter",
        pid=None,
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:01Z",
    )
    yielded_question = _agent(
        "question",
        status="QUESTION",
        run_start_time=datetime(2026, 7, 12, 11, 57),
        runner_slot_yielded=True,
        wait_runners=9,
        slot_requested_at="2026-07-12T12:00:02Z",
    )

    capacity = refresh_runner_slot_context(
        [dead_waiter, yielded_question, live_holder],
        effective_limit=10,
    )

    assert capacity == RunnerCapacitySnapshot(10, 1, 0, occupied_capacity=1.0)
