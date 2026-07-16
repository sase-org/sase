"""Unit tests for pure runner-slot admission decisions."""

from __future__ import annotations

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
)
from sase.core.runner_slots import (
    RunnerSlotWaiter,
    live_runner_slot_waiters,
    may_start,
    running_root_agent_count,
)


def _record(
    artifact_dir: str,
    *,
    pid: int = 100,
    run_started: bool = False,
    requested_at: str | None = None,
    wait_runners: int | None = None,
    parent_timestamp: str | None = None,
    agent_family_parallel: bool = False,
    appears_as_agent: bool = True,
    done: bool = False,
    pending_question: bool = False,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/projects/proj",
        project_file="/projects/proj/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir=artifact_dir,
        timestamp=artifact_dir.rsplit("/", 1)[-1],
        agent_meta=AgentMetaWire(
            pid=pid,
            parent_timestamp=parent_timestamp,
            agent_family_parallel=agent_family_parallel,
            run_started_at=("2026-07-12T12:00:00+00:00" if run_started else None),
        ),
        waiting=(
            WaitingMarkerWire(
                wait_runners=wait_runners,
                slot_requested_at=requested_at,
            )
            if requested_at is not None
            else None
        ),
        workflow_state=WorkflowStateWire(appears_as_agent=appears_as_agent),
        has_done_marker=done,
        pending_question=(
            PendingQuestionMarkerWire(session_id="question")
            if pending_question
            else None
        ),
    )


def test_running_count_uses_live_started_roots_only() -> None:
    records = [
        _record("/a", pid=1, run_started=True),
        _record("/starting", pid=2),
        _record("/child", pid=3, run_started=True, parent_timestamp="parent"),
        _record(
            "/parallel-child",
            pid=7,
            run_started=True,
            parent_timestamp="parent",
            agent_family_parallel=True,
        ),
        _record("/step", pid=4, run_started=True, appears_as_agent=False),
        _record("/done", pid=5, run_started=True, done=True),
        _record("/dead", pid=6, run_started=True),
    ]

    assert (
        running_root_agent_count(records, lambda record: record.agent_meta.pid != 6)
        == 2
    )  # type: ignore[union-attr]


def test_question_paused_root_yields_until_pause_marker_is_removed() -> None:
    records = [
        _record("/ordinary", pid=1, run_started=True),
        _record("/question", pid=2, run_started=True, pending_question=True),
    ]

    assert running_root_agent_count(records, lambda _record: True) == 1

    resumed = [
        _record("/ordinary", pid=1, run_started=True),
        _record("/question", pid=2, run_started=True),
    ]
    assert running_root_agent_count(resumed, lambda _record: True) == 2


def test_live_waiter_queue_is_fifo_and_filters_stale_processes() -> None:
    records = [
        _record("/later", pid=2, requested_at="2026-07-12T12:00:02+00:00"),
        _record("/earlier", pid=1, requested_at="2026-07-12T12:00:01+00:00"),
        _record("/dead", pid=9, requested_at="2026-07-12T11:00:00+00:00"),
    ]

    queue = live_runner_slot_waiters(
        records,
        lambda record: record.agent_meta.pid != 9,  # type: ignore[union-attr]
    )

    assert [waiter.artifact_dir for waiter in queue] == ["/earlier", "/later"]
    assert [waiter.threshold for waiter in queue] == [0, 0]


def test_queue_ties_have_deterministic_timestamp_then_path_order() -> None:
    requested_at = "2026-07-12T12:00:00+00:00"
    records = [
        _record("/z/20260712120001", requested_at=requested_at),
        _record("/b/20260712120000", requested_at=requested_at),
        _record("/a/20260712120000", requested_at=requested_at),
    ]

    queue = live_runner_slot_waiters(records, lambda _record: True)

    assert [waiter.artifact_dir for waiter in queue] == [
        "/a/20260712120000",
        "/b/20260712120000",
        "/z/20260712120001",
    ]


def test_older_ineligible_drain_waiter_does_not_block_eligible_waiter() -> None:
    drain = RunnerSlotWaiter("/drain", "2026-07-12T12:00:00+00:00", "1", threshold=0)
    immediate = RunnerSlotWaiter(
        "/immediate", "2026-07-12T12:00:01+00:00", "2", threshold=9
    )

    assert not may_start(1, 0, (drain, immediate), "/drain")
    assert may_start(1, 9, (drain, immediate), "/immediate")


def test_fifo_order_is_preserved_among_currently_eligible_waiters() -> None:
    first = RunnerSlotWaiter("/first", "2026-07-12T12:00:00+00:00", "1", threshold=9)
    second = RunnerSlotWaiter("/second", "2026-07-12T12:00:01+00:00", "2", threshold=9)

    assert may_start(0, 0, (), "/new")
    assert not may_start(1, 0, (), "/new")
    assert may_start(1, 9, (first, second), "/first")
    assert not may_start(1, 9, (first, second), "/second")


def test_drain_waiter_wins_deterministically_once_count_reaches_zero() -> None:
    first = RunnerSlotWaiter("/drain", "2026-07-12T12:00:00+00:00", "1", threshold=0)
    second = RunnerSlotWaiter(
        "/immediate", "2026-07-12T12:00:01+00:00", "2", threshold=9
    )

    assert may_start(0, 0, (first, second), "/drain")
    assert not may_start(0, 25, (first, second), "/second")


def test_live_waiter_queue_excludes_non_root_and_terminal_records() -> None:
    requested_at = "2026-07-12T12:00:00+00:00"
    records = [
        _record("/root", requested_at=requested_at, wait_runners=4),
        _record("/dead", pid=9, requested_at=requested_at, wait_runners=4),
        _record(
            "/child",
            requested_at=requested_at,
            wait_runners=4,
            parent_timestamp="parent",
        ),
        _record(
            "/step",
            requested_at=requested_at,
            wait_runners=4,
            appears_as_agent=False,
        ),
        _record("/done", requested_at=requested_at, wait_runners=4, done=True),
    ]

    queue = live_runner_slot_waiters(
        records,
        lambda record: record.agent_meta.pid != 9,  # type: ignore[union-attr]
    )

    assert queue == (RunnerSlotWaiter("/root", requested_at, "root", threshold=4),)


def test_parallel_member_joins_fifo_queue_while_serial_child_stays_exempt() -> None:
    records = [
        _record(
            "/serial",
            requested_at="2026-07-12T12:00:00+00:00",
            parent_timestamp="parent",
        ),
        _record(
            "/parallel",
            requested_at="2026-07-12T12:00:01+00:00",
            parent_timestamp="parent",
            agent_family_parallel=True,
        ),
        _record("/root", requested_at="2026-07-12T12:00:02+00:00"),
    ]

    queue = live_runner_slot_waiters(records, lambda _record: True)

    assert [waiter.artifact_dir for waiter in queue] == ["/parallel", "/root"]
    assert may_start(0, 0, queue, "/parallel")
    assert not may_start(0, 0, queue, "/root")
