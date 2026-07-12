"""Unit tests for pure runner-slot admission decisions."""

from __future__ import annotations

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
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
    parent_timestamp: str | None = None,
    appears_as_agent: bool = True,
    done: bool = False,
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
            run_started_at=("2026-07-12T12:00:00+00:00" if run_started else None),
        ),
        waiting=(
            WaitingMarkerWire(slot_requested_at=requested_at)
            if requested_at is not None
            else None
        ),
        workflow_state=WorkflowStateWire(appears_as_agent=appears_as_agent),
        has_done_marker=done,
    )


def test_running_count_uses_live_started_roots_only() -> None:
    records = [
        _record("/a", pid=1, run_started=True),
        _record("/starting", pid=2),
        _record("/child", pid=3, run_started=True, parent_timestamp="parent"),
        _record("/step", pid=4, run_started=True, appears_as_agent=False),
        _record("/done", pid=5, run_started=True, done=True),
        _record("/dead", pid=6, run_started=True),
    ]

    assert (
        running_root_agent_count(records, lambda record: record.agent_meta.pid != 6)
        == 1
    )  # type: ignore[union-attr]


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


def test_may_start_enforces_threshold_and_fifo_barrier() -> None:
    first = RunnerSlotWaiter("/first", "2026-07-12T12:00:00+00:00", "1")
    second = RunnerSlotWaiter("/second", "2026-07-12T12:00:01+00:00", "2")

    assert may_start(0, 0, (), "/new")
    assert not may_start(1, 0, (), "/new")
    assert may_start(0, 0, (first, second), "/first")
    assert not may_start(0, 25, (first, second), "/second")
