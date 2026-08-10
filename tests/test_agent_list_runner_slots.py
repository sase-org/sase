"""Tests for runner-slot context in rich agent list entries."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent as TuiAgent
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from sase.core.agent_scan_wire import AgentMetaWire, PendingQuestionMarkerWire
from sase.core.agent_scan_wire import WaitingMarkerWire
from sase.core.runner_slots import live_runner_slot_waiters
from sase.integrations.agent_list_entries import (
    _attach_runner_slot_context,
    _build_agent_list_entry,
)
from tests._agent_list_entries_helpers import agent, record


def test_runner_slot_wait_info_includes_live_count_and_queue_position() -> None:
    first = _build_agent_list_entry(
        agent(name="first", status="WAITING"),
        record=record(
            timestamp="20260709120001",
            artifact_dir="/tmp/sase/artifacts/ace-run/20260709120001",
            agent_meta=AgentMetaWire(),
            waiting=WaitingMarkerWire(
                wait_runners=9,
                wait_priority=20,
                slot_requested_at="2026-07-12T12:00:01Z",
            ),
        ),
    )
    second = _build_agent_list_entry(
        agent(name="second", status="WAITING"),
        record=record(
            timestamp="20260709120002",
            artifact_dir="/tmp/sase/artifacts/ace-run/20260709120002",
            agent_meta=AgentMetaWire(),
            waiting=WaitingMarkerWire(
                wait_runners=0,
                wait_runners_explicit=True,
                wait_priority=1,
                slot_requested_at="2026-07-12T12:00:02Z",
            ),
        ),
    )

    first, second = _attach_runner_slot_context(
        [first, second], 7, runner_slot_holders=("phase",)
    )

    assert first.wait.wait_runners == 9
    assert first.wait.wait_priority == 20
    assert first.wait.runner_slots_in_use == 7
    assert first.status == "QUEUED"
    assert first.status_bucket == "Queued"
    assert first.status_glyph == "…"
    assert first.wait.runner_slot_queue_position == 1
    assert first.wait.runner_slot_queue_size == 2
    assert first.wait.runner_slot_holders == ("phase",)
    assert second.wait.wait_runners_explicit is True
    assert second.wait.wait_priority == 1
    assert second.status == "QUEUED"
    assert second.status_bucket == "Queued"
    assert second.status_glyph == "…"
    assert second.wait.runner_slot_queue_position == 2
    assert second.wait.runner_slot_queue_size == 2
    assert second.wait.runner_slot_holders == ("phase",)


def test_runner_slot_queue_orders_priority_before_fifo_with_default_priority() -> None:
    def waiter(
        *,
        name: str,
        timestamp: str,
        requested_at: str,
        priority: int | None,
    ):
        return _build_agent_list_entry(
            agent(
                name=name,
                status="WAITING",
                artifacts_dir=f"/tmp/sase/artifacts/ace-run/{timestamp}",
            ),
            record=record(
                timestamp=timestamp,
                artifact_dir=f"/tmp/sase/artifacts/ace-run/{timestamp}",
                agent_meta=AgentMetaWire(),
                waiting=WaitingMarkerWire(
                    wait_runners=9,
                    wait_priority=priority,
                    slot_requested_at=requested_at,
                ),
            ),
        )

    older_low_priority = waiter(
        name="older-low-priority",
        timestamp="20260712120001",
        requested_at="2026-07-12T12:00:01Z",
        priority=20,
    )
    older_default = waiter(
        name="older-default",
        timestamp="20260712120002",
        requested_at="2026-07-12T12:00:02Z",
        priority=None,
    )
    newer_explicit_default = waiter(
        name="newer-explicit-default",
        timestamp="20260712120003",
        requested_at="2026-07-12T12:00:03Z",
        priority=10,
    )
    newer_urgent = waiter(
        name="newer-urgent",
        timestamp="20260712120004",
        requested_at="2026-07-12T12:00:04Z",
        priority=1,
    )

    entries = _attach_runner_slot_context(
        [
            older_low_priority,
            older_default,
            newer_explicit_default,
            newer_urgent,
        ],
        0,
    )
    positions = {entry.name: entry.wait.runner_slot_queue_position for entry in entries}

    assert positions == {
        "older-low-priority": 4,
        "older-default": 2,
        "newer-explicit-default": 3,
        "newer-urgent": 1,
    }


def test_runner_slot_queue_orders_parked_waiters_after_open_thresholds() -> None:
    specs = (
        ("barrier-a", "20260712120001", 0, True, 1),
        ("x0", "20260712120002", 9, False, None),
        ("barrier-b", "20260712120003", 0, True, 1),
        ("x1", "20260712120004", 9, False, None),
    )

    def waiter(
        *,
        name: str,
        timestamp: str,
        wait_runners: int,
        explicit: bool = False,
        priority: int | None = None,
    ):
        return _build_agent_list_entry(
            agent(
                name=name,
                status="WAITING",
                artifacts_dir=f"/tmp/sase/artifacts/ace-run/{timestamp}",
            ),
            record=record(
                timestamp=timestamp,
                artifact_dir=f"/tmp/sase/artifacts/ace-run/{timestamp}",
                agent_meta=AgentMetaWire(),
                waiting=WaitingMarkerWire(
                    wait_runners=wait_runners,
                    wait_runners_explicit=explicit,
                    wait_priority=priority,
                    slot_requested_at=f"2026-07-12T12:00:{timestamp[-2:]}Z",
                ),
            ),
        )

    entries = _attach_runner_slot_context(
        [
            waiter(
                name=name,
                timestamp=timestamp,
                wait_runners=wait_runners,
                explicit=explicit,
                priority=priority,
            )
            for name, timestamp, wait_runners, explicit, priority in specs
        ],
        9,
    )
    positions = {entry.name: entry.wait.runner_slot_queue_position for entry in entries}
    holders = [
        TuiAgent(
            agent_type=AgentType.RUNNING,
            cl_name=f"holder-{index}",
            project_file="/tmp/project/project.sase",
            status="RUNNING",
            start_time=datetime(2026, 7, 12, 12, 0),
            raw_suffix=f"holder-{index}",
            pid=200 + index,
            artifacts_dir=f"/tmp/project/artifacts/ace-run/holder-{index}",
            run_start_time=datetime(2026, 7, 12, 11, 40 + index),
        )
        for index in range(9)
    ]
    tui_waiters = [
        TuiAgent(
            agent_type=AgentType.RUNNING,
            cl_name=name,
            project_file="/tmp/project/project.sase",
            status="WAITING",
            start_time=datetime(2026, 7, 12, 12, 0),
            raw_suffix=timestamp,
            pid=100 + index,
            artifacts_dir=f"/tmp/project/artifacts/ace-run/{timestamp}",
            wait_runners=wait_runners,
            wait_runners_explicit=explicit,
            wait_priority=priority,
            slot_requested_at=f"2026-07-12T12:00:{timestamp[-2:]}Z",
        )
        for index, (name, timestamp, wait_runners, explicit, priority) in enumerate(
            specs
        )
    ]
    refresh_runner_slot_context([*holders, *tui_waiters], effective_limit=10)
    tui_positions = {
        agent.cl_name: agent.runner_slot_queue_position for agent in tui_waiters
    }

    expected = {
        "x0": 1,
        "x1": 2,
        "barrier-a": 3,
        "barrier-b": 4,
    }
    assert positions == tui_positions == expected


def test_runner_slot_queue_rank_matches_tui_projection() -> None:
    specs = (
        ("older", "20260712120001", "2026-07-12T12:00:01Z", 20),
        ("default", "20260712120002", "2026-07-12T12:00:02Z", None),
        ("tie-later", "20260712120005", "2026-07-12T12:00:02Z", 10),
        ("tie-earlier", "20260712120004", "2026-07-12T12:00:02Z", 10),
        ("urgent", "20260712120003", "2026-07-12T12:00:03Z", 1),
    )
    entries = [
        _build_agent_list_entry(
            agent(
                name=name,
                status="WAITING",
                artifacts_dir=f"/tmp/sase/artifacts/ace-run/{timestamp}",
            ),
            record=record(
                timestamp=timestamp,
                artifact_dir=f"/tmp/sase/artifacts/ace-run/{timestamp}",
                agent_meta=AgentMetaWire(),
                waiting=WaitingMarkerWire(
                    wait_runners=9,
                    wait_priority=priority,
                    slot_requested_at=requested_at,
                ),
            ),
        )
        for name, timestamp, requested_at, priority in specs
    ]
    tui_agents = [
        TuiAgent(
            agent_type=AgentType.RUNNING,
            cl_name=name,
            project_file="/tmp/project/project.sase",
            status="WAITING",
            start_time=datetime(2026, 7, 12, 12, 0),
            raw_suffix=timestamp,
            pid=100 + index,
            artifacts_dir=f"/tmp/project/artifacts/ace-run/{timestamp}",
            wait_runners=9,
            wait_priority=priority,
            slot_requested_at=requested_at,
        )
        for index, (name, timestamp, requested_at, priority) in enumerate(specs)
    ]

    entries = _attach_runner_slot_context(entries, 10)
    refresh_runner_slot_context(tui_agents, effective_limit=10)
    core_queue = live_runner_slot_waiters(
        (
            record(
                timestamp=timestamp,
                artifact_dir=f"/tmp/sase/artifacts/ace-run/{timestamp}",
                agent_meta=AgentMetaWire(),
                waiting=WaitingMarkerWire(
                    wait_runners=9,
                    wait_priority=priority,
                    slot_requested_at=requested_at,
                ),
            )
            for _name, timestamp, requested_at, priority in specs
        ),
        lambda _record: True,
    )

    integration_positions = {
        entry.name: entry.wait.runner_slot_queue_position for entry in entries
    }
    tui_positions = {
        agent.cl_name: agent.runner_slot_queue_position for agent in tui_agents
    }
    integration_order = [
        entry.timestamp
        for entry in sorted(
            entries,
            key=lambda entry: entry.wait.runner_slot_queue_position or 0,
        )
    ]
    tui_order = [
        agent.raw_suffix
        for agent in sorted(
            tui_agents,
            key=lambda agent: agent.runner_slot_queue_position or 0,
        )
    ]
    core_order = [waiter.timestamp for waiter in core_queue]
    assert integration_order == tui_order == core_order
    assert (
        integration_positions
        == tui_positions
        == {
            "older": 5,
            "default": 2,
            "tie-later": 4,
            "tie-earlier": 3,
            "urgent": 1,
        }
    )


def test_runner_slot_queue_defaults_invalid_priorities() -> None:
    def waiter(name: str, timestamp: str, priority: int | None):
        return _build_agent_list_entry(
            agent(
                name=name,
                status="WAITING",
                artifacts_dir=f"/tmp/sase/artifacts/ace-run/{timestamp}",
            ),
            record=record(
                timestamp=timestamp,
                artifact_dir=f"/tmp/sase/artifacts/ace-run/{timestamp}",
                agent_meta=AgentMetaWire(),
                waiting=WaitingMarkerWire(
                    wait_runners=9,
                    wait_priority=priority,
                    slot_requested_at=f"2026-07-12T12:00:{timestamp[-2:]}Z",
                ),
            ),
        )

    invalid_boolean = waiter("invalid-boolean", "20260712120001", True)
    invalid_negative = waiter("invalid-negative", "20260712120002", -1)
    explicit_priority = waiter("explicit-priority", "20260712120003", 2)

    entries = _attach_runner_slot_context(
        [invalid_boolean, invalid_negative, explicit_priority], 0
    )
    positions = {entry.name: entry.wait.runner_slot_queue_position for entry in entries}

    assert positions == {
        "invalid-boolean": 2,
        "invalid-negative": 3,
        "explicit-priority": 1,
    }


def test_answered_question_runner_wait_has_waiting_precedence(tmp_path) -> None:
    request_path = tmp_path / "question_request.json"
    request_path.write_text("{}")
    (tmp_path / "question_response.json").write_text("{}")
    entry = _build_agent_list_entry(
        agent(status="RUNNING"),
        record=record(
            agent_meta=AgentMetaWire(run_started_at="2026-07-09T12:00:00Z"),
            pending_question=PendingQuestionMarkerWire(
                session_id="q1", request_path=str(request_path)
            ),
            waiting=WaitingMarkerWire(
                wait_runners=0,
                slot_requested_at="2026-07-09T12:05:00Z",
            ),
        ),
    )

    assert entry.status == "WAITING"
    assert entry.wait.wait_runners == 0
    assert entry.wait.slot_requested_at == "2026-07-09T12:05:00Z"

    (entry,) = _attach_runner_slot_context([entry], 0)
    assert entry.wait.runner_slot_queue_position == 1
