"""Tests for runner-slot capacity records and queueing under sharded artifact layouts."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_runner_slots import (
    _capacity_record_from_agent,
    refresh_runner_slot_context,
)

from ._agent_runner_slots_helpers import (
    _agent,
    _assert_capacity_metrics,
    _sharded_artifacts_dir,
)


def test_capacity_record_from_agent_resolves_sharded_layout_project_and_workflow() -> (
    None
):
    agent = _agent(
        "sharded-root",
        project_file="",
        artifacts_dir=_sharded_artifacts_dir("proj", "20260712120500"),
    )

    record = _capacity_record_from_agent(agent, {})

    assert record["workflow_dir_name"] == "ace-run"
    assert record["project_name"] == "proj"


def test_capacity_record_from_agent_falls_back_for_legacy_layout() -> None:
    agent = _agent(
        "legacy-root",
        project_file="",
        artifacts_dir="/tmp/project/artifacts/ace-run/legacy-root",
    )

    record = _capacity_record_from_agent(agent, {})

    assert record["workflow_dir_name"] == "ace-run"
    assert record["project_name"] == "project"


def test_refresh_runner_slot_context_queues_sharded_layout_waiter() -> None:
    holders = [
        _agent(
            f"holder-{index}",
            project_file="",
            artifacts_dir=_sharded_artifacts_dir("proj", f"202607121140{index:02d}"),
            appears_as_agent=True,
            status="RUNNING",
            run_start_time=datetime(2026, 7, 12, 11, 40 + index),
        )
        for index in range(9)
    ]
    waiter = _agent(
        "waiter",
        project_file="",
        artifacts_dir=_sharded_artifacts_dir("proj", "20260712120001"),
        appears_as_agent=True,
        wait_runners=9,
        wait_priority=20,
        slot_requested_at="2026-07-12T12:00:01Z",
    )

    capacity = refresh_runner_slot_context([*holders, waiter], effective_limit=10)

    _assert_capacity_metrics(capacity, (10, 9, 1))
    assert waiter.status == "QUEUED"
    assert waiter.runner_slot_queue_position == 1


def test_refresh_runner_slot_context_fallback_queues_sharded_layout_waiter() -> None:
    holder = _agent(
        "holder",
        project_file="",
        artifacts_dir=_sharded_artifacts_dir("proj", "20260712114000"),
        appears_as_agent=True,
        status="RUNNING",
        run_start_time=datetime(2026, 7, 12, 11, 40),
    )
    waiter = _agent(
        "waiter",
        project_file="",
        artifacts_dir=_sharded_artifacts_dir("proj", "20260712120001"),
        appears_as_agent=True,
        wait_runners=0,
        wait_runners_explicit=True,
        slot_requested_at="2026-07-12T12:00:01Z",
    )

    refresh_runner_slot_context([holder, waiter])

    assert waiter.status == "QUEUED"
    assert waiter.runner_slot_queue_position == 1
