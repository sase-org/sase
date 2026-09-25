"""Unit tests for runner-slot occupancy accounting."""

from __future__ import annotations

from dataclasses import replace

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.paths import sase_projects_dir
from sase.core.runner_slots import (
    is_runner_slot_user_agent_record,
    live_runner_slot_waiters,
    runner_capacity_snapshot,
    running_agent_slot_count,
    runner_slot_candidate_record,
)
from tests._runner_slots_helpers import _always_live, _live_unless_stopped, _record


def _candidate_record(artifacts_dir: str) -> dict[str, object]:
    return runner_slot_candidate_record(
        artifacts_dir=artifacts_dir,
        timestamp="20260712120100",
        slot_requested_at="2026-07-12T12:01:00Z",
        wait_runners=None,
        wait_runners_explicit=False,
        wait_priority=10,
        queue_weight=1.0,
        queue_weight_explicit=False,
        eligible_since=None,
    )


def test_running_agent_slot_count_uses_live_started_agent_session_occupancy() -> None:
    records = [
        _record("/a", pid=1, run_started=True),
        _record("/starting", pid=2),
        _record(
            "/child",
            pid=3,
            run_started=True,
            parent_timestamp="parent",
            agent_session="session-b",
        ),
        _record(
            "/parallel-child",
            pid=7,
            run_started=True,
            parent_timestamp="parent",
            agent_session="session-b",
            agent_session_parallel=True,
        ),
        _record("/step", pid=4, run_started=True, appears_as_agent=False),
        _record("/done", pid=5, run_started=True, done=True),
        _record("/dead", pid=6, run_started=True),
    ]

    # /a is its own agent session (1). session-b's live serial child holds the
    # agent session's one slot (1) and its live parallel sibling holds its own
    # slot on top of that (1). /starting (not started), /step (not an agent),
    # /done, and /dead (not live) contribute nothing.
    assert (
        running_agent_slot_count(records, lambda record: record.agent_meta.pid != 6)
        == 3
    )  # type: ignore[union-attr]


def test_multiplier_waiter_projects_resolved_admission_limit() -> None:
    """A multiplier survives the scan projection into the live waiter view."""
    record = _record(
        "/multiplier",
        requested_at="2026-09-25T12:00:00Z",
        queue_weight=0.25,
        queue_weight_explicit=True,
    )
    assert record.waiting is not None
    record = replace(
        record,
        waiting=replace(record.waiting, queue_capacity_multiplier=1.5),
    )

    snapshot = runner_capacity_snapshot([record], _always_live, effective_limit=5.0)
    (waiter,) = live_runner_slot_waiters([record], _always_live, effective_limit=5.0)

    assert snapshot["waiters"][0]["queue_capacity_multiplier"] == 1.5
    assert snapshot["waiters"][0]["admission_limit"] == 7.5
    assert waiter.queue_capacity is None
    assert waiter.queue_capacity_multiplier == 1.5
    assert waiter.admission_limit == 7.5


def test_runner_slot_user_agent_record_predicate_covers_admission_cases() -> None:
    root = _record("/root")
    parallel_child = _record(
        "/parallel",
        parent_timestamp="parent",
        agent_session_parallel=True,
    )
    serial_child = _record("/serial", parent_timestamp="parent")
    done = _record("/done", done=True)

    assert is_runner_slot_user_agent_record(root)
    assert is_runner_slot_user_agent_record(parallel_child)
    assert not is_runner_slot_user_agent_record(serial_child)
    assert not is_runner_slot_user_agent_record(done)


def test_standalone_agent_occupies_one_slot() -> None:
    records = [_record("/standalone", run_started=True)]

    assert running_agent_slot_count(records, _always_live) == 1


def test_root_plus_live_serial_child_occupies_exactly_one_slot() -> None:
    records = [
        _record("/root", agent_session="fam", run_started=True),
        _record(
            "/serial",
            agent_session="fam",
            parent_timestamp="root_ts",
            run_started=True,
        ),
    ]

    assert running_agent_slot_count(records, _always_live) == 1


def test_dead_root_with_live_monitor_member_still_occupies_one_slot() -> None:
    records = [
        _record("/root", agent_session="fam", run_started=True),
        _record(
            "/monitor",
            agent_session="fam",
            agent_session_role="monitor",
            monitor_id="mon-1",
        ),
    ]

    def is_live(record: AgentArtifactRecordWire) -> bool:
        return record.artifact_dir != "/root"

    assert running_agent_slot_count(records, is_live) == 1


def test_settled_monitor_with_live_followup_still_occupies_one_slot() -> None:
    records = [
        _record("/root", agent_session="fam", run_started=True, done=True),
        _record(
            "/monitor",
            agent_session="fam",
            agent_session_role="monitor",
            monitor_id="mon-1",
            done=True,
        ),
        _record(
            "/followup",
            agent_session="fam",
            parent_timestamp="/root",
            run_started=True,
        ),
    ]

    assert running_agent_slot_count(records, _always_live) == 1


def test_monitor_followup_handoff_counts_live_monitor_before_successor_starts() -> None:
    records = [
        _record(
            "/monitor",
            agent_session="fam",
            agent_session_role="monitor",
            monitor_id="mon-1",
        ),
        _record(
            "/followup",
            agent_session="fam",
            parent_timestamp="monitor_ts",
        ),
    ]

    assert running_agent_slot_count(records, _live_unless_stopped) == 1


def test_monitor_followup_handoff_overlap_counts_one_slot() -> None:
    records = [
        _record(
            "/monitor",
            agent_session="fam",
            agent_session_role="monitor",
            monitor_id="mon-1",
        ),
        _record(
            "/followup",
            agent_session="fam",
            parent_timestamp="monitor_ts",
            run_started=True,
        ),
    ]

    assert running_agent_slot_count(records, _live_unless_stopped) == 1


def test_stopped_monitor_with_started_followup_counts_one_slot() -> None:
    records = [
        _record(
            "/monitor",
            agent_session="fam",
            agent_session_role="monitor",
            monitor_id="mon-1",
            stopped_at="2026-09-06T12:00:00+00:00",
        ),
        _record(
            "/followup",
            agent_session="fam",
            parent_timestamp="monitor_ts",
            run_started=True,
        ),
    ]

    assert running_agent_slot_count(records, _live_unless_stopped) == 1


def test_stopped_monitor_before_followup_start_documents_old_gap() -> None:
    records = [
        _record(
            "/monitor",
            agent_session="fam",
            agent_session_role="monitor",
            monitor_id="mon-1",
            stopped_at="2026-09-06T12:00:00+00:00",
        ),
        _record(
            "/followup",
            agent_session="fam",
            parent_timestamp="monitor_ts",
        ),
    ]

    assert running_agent_slot_count(records, _live_unless_stopped) == 0


def test_two_independent_agent_sessions_occupy_two_slots() -> None:
    records = [
        _record("/a", agent_session="fam-a", run_started=True),
        _record("/b", agent_session="fam-b", run_started=True),
    ]

    assert running_agent_slot_count(records, _always_live) == 2


def test_clan_members_launched_independently_count_individually() -> None:
    records = [
        _record("/clan-a", run_started=True),
        _record("/clan-b", run_started=True),
    ]

    assert running_agent_slot_count(records, _always_live) == 2


def test_live_parallel_agent_session_members_count_individually() -> None:
    records = [
        _record("/root", agent_session="fam", run_started=True, done=True),
        _record(
            "/parallel-1",
            agent_session="fam",
            parent_timestamp="/root",
            agent_session_parallel=True,
            run_started=True,
        ),
        _record(
            "/parallel-2",
            agent_session="fam",
            parent_timestamp="/root",
            agent_session_parallel=True,
            run_started=True,
        ),
    ]

    assert running_agent_slot_count(records, _always_live) == 2


def test_pending_question_on_agent_sessions_only_live_shell_frees_its_slot() -> None:
    records = [
        _record(
            "/root",
            agent_session="fam",
            run_started=True,
            pending_question=True,
        ),
    ]

    assert running_agent_slot_count(records, _always_live) == 0


def test_done_marker_and_dead_pid_members_do_not_occupy() -> None:
    records = [
        _record("/done", agent_session="fam", run_started=True, done=True),
        _record("/dead", agent_session="fam", run_started=True),
    ]

    def is_live(record: AgentArtifactRecordWire) -> bool:
        return record.artifact_dir != "/dead"

    assert running_agent_slot_count(records, is_live) == 0


def test_monitor_member_with_pid_but_no_run_started_at_occupies_one_slot() -> None:
    records = [_record("/monitor", agent_session_role="monitor", monitor_id="mon-1")]

    assert running_agent_slot_count(records, _always_live) == 1


def test_inherited_monitor_id_without_monitor_role_uses_run_started_at() -> None:
    records = [
        _record("/starter", agent_session_role="root", monitor_id="mon-1"),
        _record("/followup", agent_session_role="code", monitor_id="mon-1"),
    ]

    assert running_agent_slot_count(records, _always_live) == 0


def test_non_agent_workflow_step_record_does_not_occupy() -> None:
    records = [_record("/step", run_started=True, appears_as_agent=False)]

    assert running_agent_slot_count(records, _always_live) == 0


def test_records_from_two_projects_sharing_an_agent_session_name_count_separately() -> (
    None
):
    records = [
        _record("/a", project_name="proj-a", agent_session="fam", run_started=True),
        _record("/b", project_name="proj-b", agent_session="fam", run_started=True),
    ]

    assert running_agent_slot_count(records, _always_live) == 2


def test_question_paused_root_yields_until_pause_marker_is_removed() -> None:
    records = [
        _record("/ordinary", pid=1, run_started=True),
        _record("/question", pid=2, run_started=True, pending_question=True),
    ]

    assert running_agent_slot_count(records, lambda _record: True) == 1

    resumed = [
        _record("/ordinary", pid=1, run_started=True),
        _record("/question", pid=2, run_started=True),
    ]
    assert running_agent_slot_count(resumed, lambda _record: True) == 2


def test_runner_slot_candidate_record_resolves_sharded_layout_project_name() -> None:
    artifacts_dir = str(
        sase_projects_dir()
        / "proj"
        / "artifacts"
        / "ace-run"
        / "202607"
        / "12"
        / "20260712120100"
    )

    candidate = _candidate_record(artifacts_dir)

    assert candidate["project_name"] == "proj"
    assert candidate["workflow_dir_name"] == "ace-run"


def test_runner_slot_candidate_record_falls_back_for_unparseable_artifact_dir() -> None:
    artifacts_dir = "/tmp/elsewhere/proj/artifacts/ace-run/20260712120100"

    candidate = _candidate_record(artifacts_dir)

    assert candidate["project_name"] == "proj"
    assert candidate["workflow_dir_name"] == "ace-run"
