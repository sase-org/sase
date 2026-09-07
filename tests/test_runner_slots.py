"""Unit tests for runner-slot occupancy accounting."""

from __future__ import annotations

from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.core.runner_slots import (
    is_runner_slot_user_agent_record,
    running_agent_slot_count,
)
from tests._runner_slots_helpers import _always_live, _live_unless_stopped, _record


def test_running_agent_slot_count_uses_live_started_family_occupancy() -> None:
    records = [
        _record("/a", pid=1, run_started=True),
        _record("/starting", pid=2),
        _record(
            "/child",
            pid=3,
            run_started=True,
            parent_timestamp="parent",
            agent_family="family-b",
        ),
        _record(
            "/parallel-child",
            pid=7,
            run_started=True,
            parent_timestamp="parent",
            agent_family="family-b",
            agent_family_parallel=True,
        ),
        _record("/step", pid=4, run_started=True, appears_as_agent=False),
        _record("/done", pid=5, run_started=True, done=True),
        _record("/dead", pid=6, run_started=True),
    ]

    # /a is its own family (1). family-b's live serial child holds the
    # family's one slot (1) and its live parallel sibling holds its own slot
    # on top of that (1). /starting (not started), /step (not an agent),
    # /done, and /dead (not live) contribute nothing.
    assert (
        running_agent_slot_count(records, lambda record: record.agent_meta.pid != 6)
        == 3
    )  # type: ignore[union-attr]


def test_runner_slot_user_agent_record_predicate_covers_admission_cases() -> None:
    root = _record("/root")
    parallel_child = _record(
        "/parallel",
        parent_timestamp="parent",
        agent_family_parallel=True,
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
        _record("/root", agent_family="fam", run_started=True),
        _record(
            "/serial",
            agent_family="fam",
            parent_timestamp="root_ts",
            run_started=True,
        ),
    ]

    assert running_agent_slot_count(records, _always_live) == 1


def test_dead_root_with_live_monitor_member_still_occupies_one_slot() -> None:
    records = [
        _record("/root", agent_family="fam", run_started=True),
        _record(
            "/monitor",
            agent_family="fam",
            agent_family_role="monitor",
            monitor_id="mon-1",
        ),
    ]

    def is_live(record: AgentArtifactRecordWire) -> bool:
        return record.artifact_dir != "/root"

    assert running_agent_slot_count(records, is_live) == 1


def test_settled_monitor_with_live_followup_still_occupies_one_slot() -> None:
    records = [
        _record("/root", agent_family="fam", run_started=True, done=True),
        _record(
            "/monitor",
            agent_family="fam",
            agent_family_role="monitor",
            monitor_id="mon-1",
            done=True,
        ),
        _record(
            "/followup",
            agent_family="fam",
            parent_timestamp="/root",
            run_started=True,
        ),
    ]

    assert running_agent_slot_count(records, _always_live) == 1


def test_monitor_followup_handoff_counts_live_monitor_before_successor_starts() -> None:
    records = [
        _record(
            "/monitor",
            agent_family="fam",
            agent_family_role="monitor",
            monitor_id="mon-1",
        ),
        _record(
            "/followup",
            agent_family="fam",
            parent_timestamp="monitor_ts",
        ),
    ]

    assert running_agent_slot_count(records, _live_unless_stopped) == 1


def test_monitor_followup_handoff_overlap_counts_one_slot() -> None:
    records = [
        _record(
            "/monitor",
            agent_family="fam",
            agent_family_role="monitor",
            monitor_id="mon-1",
        ),
        _record(
            "/followup",
            agent_family="fam",
            parent_timestamp="monitor_ts",
            run_started=True,
        ),
    ]

    assert running_agent_slot_count(records, _live_unless_stopped) == 1


def test_stopped_monitor_with_started_followup_counts_one_slot() -> None:
    records = [
        _record(
            "/monitor",
            agent_family="fam",
            agent_family_role="monitor",
            monitor_id="mon-1",
            stopped_at="2026-09-06T12:00:00+00:00",
        ),
        _record(
            "/followup",
            agent_family="fam",
            parent_timestamp="monitor_ts",
            run_started=True,
        ),
    ]

    assert running_agent_slot_count(records, _live_unless_stopped) == 1


def test_stopped_monitor_before_followup_start_documents_old_gap() -> None:
    records = [
        _record(
            "/monitor",
            agent_family="fam",
            agent_family_role="monitor",
            monitor_id="mon-1",
            stopped_at="2026-09-06T12:00:00+00:00",
        ),
        _record(
            "/followup",
            agent_family="fam",
            parent_timestamp="monitor_ts",
        ),
    ]

    assert running_agent_slot_count(records, _live_unless_stopped) == 0


def test_two_independent_families_occupy_two_slots() -> None:
    records = [
        _record("/a", agent_family="fam-a", run_started=True),
        _record("/b", agent_family="fam-b", run_started=True),
    ]

    assert running_agent_slot_count(records, _always_live) == 2


def test_clan_members_launched_independently_count_individually() -> None:
    records = [
        _record("/clan-a", run_started=True),
        _record("/clan-b", run_started=True),
    ]

    assert running_agent_slot_count(records, _always_live) == 2


def test_live_parallel_family_members_count_individually() -> None:
    records = [
        _record("/root", agent_family="fam", run_started=True, done=True),
        _record(
            "/parallel-1",
            agent_family="fam",
            parent_timestamp="/root",
            agent_family_parallel=True,
            run_started=True,
        ),
        _record(
            "/parallel-2",
            agent_family="fam",
            parent_timestamp="/root",
            agent_family_parallel=True,
            run_started=True,
        ),
    ]

    assert running_agent_slot_count(records, _always_live) == 2


def test_pending_question_on_familys_only_live_shell_frees_its_slot() -> None:
    records = [
        _record(
            "/root",
            agent_family="fam",
            run_started=True,
            pending_question=True,
        ),
    ]

    assert running_agent_slot_count(records, _always_live) == 0


def test_done_marker_and_dead_pid_members_do_not_occupy() -> None:
    records = [
        _record("/done", agent_family="fam", run_started=True, done=True),
        _record("/dead", agent_family="fam", run_started=True),
    ]

    def is_live(record: AgentArtifactRecordWire) -> bool:
        return record.artifact_dir != "/dead"

    assert running_agent_slot_count(records, is_live) == 0


def test_monitor_member_with_pid_but_no_run_started_at_occupies_one_slot() -> None:
    records = [_record("/monitor", agent_family_role="monitor", monitor_id="mon-1")]

    assert running_agent_slot_count(records, _always_live) == 1


def test_inherited_monitor_id_without_monitor_role_uses_run_started_at() -> None:
    records = [
        _record("/starter", agent_family_role="root", monitor_id="mon-1"),
        _record("/followup", agent_family_role="code", monitor_id="mon-1"),
    ]

    assert running_agent_slot_count(records, _always_live) == 0


def test_non_agent_workflow_step_record_does_not_occupy() -> None:
    records = [_record("/step", run_started=True, appears_as_agent=False)]

    assert running_agent_slot_count(records, _always_live) == 0


def test_records_from_two_projects_sharing_a_family_name_count_separately() -> None:
    records = [
        _record("/a", project_name="proj-a", agent_family="fam", run_started=True),
        _record("/b", project_name="proj-b", agent_family="fam", run_started=True),
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
