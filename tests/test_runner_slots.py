"""Unit tests for pure runner-slot admission decisions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    FamilyShellWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
    WorkflowStateWire,
)
from sase.core.runner_slots import (
    DEFAULT_WAIT_PRIORITY,
    RunnerSlotWaiter,
    better_priority_agent_pending,
    deference_satisfied,
    deference_window_seconds,
    is_runner_slot_user_agent_record,
    live_runner_slot_waiters,
    may_start,
    normalize_wait_priority,
    runner_slot_queue_display_key,
    runner_slot_waiter_sort_key,
    running_agent_slot_count,
)


def _record(
    artifact_dir: str,
    *,
    project_name: str = "proj",
    pid: int = 100,
    run_started: bool = False,
    requested_at: str | None = None,
    wait_runners: int | None = None,
    wait_priority: int | None = None,
    meta_wait_priority: int | None = None,
    parent_timestamp: str | None = None,
    agent_family: str | None = None,
    agent_family_role: str | None = None,
    agent_family_parallel: bool = False,
    monitor_id: str | None = None,
    appears_as_agent: bool = True,
    done: bool = False,
    pending_question: bool = False,
    stopped_at: str | None = None,
) -> AgentArtifactRecordWire:
    return AgentArtifactRecordWire(
        project_name=project_name,
        project_dir=f"/projects/{project_name}",
        project_file=f"/projects/{project_name}/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir=artifact_dir,
        timestamp=artifact_dir.rsplit("/", 1)[-1],
        agent_meta=AgentMetaWire(
            pid=pid,
            parent_timestamp=parent_timestamp,
            agent_family=agent_family,
            agent_family_role=agent_family_role,
            agent_family_parallel=agent_family_parallel,
            family_shell=(
                FamilyShellWire(kind="monitor", id=monitor_id)
                if monitor_id is not None
                else None
            ),
            wait_priority=meta_wait_priority,
            run_started_at=("2026-07-12T12:00:00+00:00" if run_started else None),
            stopped_at=stopped_at,
        ),
        waiting=(
            WaitingMarkerWire(
                wait_runners=wait_runners,
                wait_priority=wait_priority,
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


def test_normalize_wait_priority_defaults_missing_and_invalid_values() -> None:
    assert normalize_wait_priority(3) == 3
    assert normalize_wait_priority(None) == DEFAULT_WAIT_PRIORITY
    assert normalize_wait_priority(True) == DEFAULT_WAIT_PRIORITY
    assert normalize_wait_priority(-1) == DEFAULT_WAIT_PRIORITY
    assert normalize_wait_priority("3") == DEFAULT_WAIT_PRIORITY


def test_deference_window_scales_only_worse_priorities_and_clamps() -> None:
    assert deference_window_seconds(1, seconds_per_step=3, max_seconds=60) == 0.0
    assert (
        deference_window_seconds(
            DEFAULT_WAIT_PRIORITY,
            seconds_per_step=3,
            max_seconds=60,
        )
        == 0.0
    )
    assert deference_window_seconds(12, seconds_per_step=3, max_seconds=60) == 6.0
    assert deference_window_seconds(40, seconds_per_step=3, max_seconds=60) == 60.0


def test_deference_satisfied_requires_valid_elapsed_timestamp() -> None:
    now = datetime(2026, 7, 25, 12, 0, tzinfo=UTC)

    assert deference_satisfied(None, now, 0)
    assert not deference_satisfied(None, now, 30)
    assert not deference_satisfied("not-a-time", now, 30)
    assert not deference_satisfied((now + timedelta(seconds=1)).isoformat(), now, 30)
    assert not deference_satisfied(
        (now - timedelta(seconds=29)).isoformat(),
        now,
        30,
    )
    assert deference_satisfied(
        (now - timedelta(seconds=30)).isoformat(),
        now,
        30,
    )


def test_better_priority_agent_pending_finds_only_plausible_arrivals() -> None:
    me = "/me"
    candidate = _record("/candidate", meta_wait_priority=2)

    assert better_priority_agent_pending(
        [candidate],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [candidate],
        lambda _record: False,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record("/started", run_started=True, meta_wait_priority=2)],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [
            _record(
                "/parked",
                requested_at="2026-07-25T12:00:00+00:00",
                meta_wait_priority=2,
            )
        ],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record("/done", done=True, meta_wait_priority=2)],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record("/step", appears_as_agent=False, meta_wait_priority=2)],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record("/equal", meta_wait_priority=20)],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record("/worse", meta_wait_priority=30)],
        lambda _record: True,
        priority=20,
        me=me,
    )
    assert not better_priority_agent_pending(
        [_record(me, meta_wait_priority=2)],
        lambda _record: True,
        priority=20,
        me=me,
    )


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


def _always_live(_record: AgentArtifactRecordWire) -> bool:
    return True


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


def _live_unless_stopped(record: AgentArtifactRecordWire) -> bool:
    meta = record.agent_meta
    return meta is not None and meta.stopped_at is None


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
    assert [waiter.priority for waiter in queue] == [
        DEFAULT_WAIT_PRIORITY,
        DEFAULT_WAIT_PRIORITY,
    ]


def test_live_waiter_queue_orders_priority_before_fifo() -> None:
    records = [
        _record(
            "/older-default",
            requested_at="2026-07-12T12:00:00+00:00",
            wait_priority=DEFAULT_WAIT_PRIORITY,
        ),
        _record(
            "/newer-urgent",
            requested_at="2026-07-12T12:00:01+00:00",
            wait_priority=1,
        ),
    ]

    queue = live_runner_slot_waiters(records, lambda _record: True)

    assert [waiter.artifact_dir for waiter in queue] == [
        "/newer-urgent",
        "/older-default",
    ]


def test_live_waiter_queue_preserves_fifo_within_priority() -> None:
    records = [
        _record(
            "/later",
            requested_at="2026-07-12T12:00:02+00:00",
            wait_priority=4,
        ),
        _record(
            "/earlier",
            requested_at="2026-07-12T12:00:01+00:00",
            wait_priority=4,
        ),
    ]

    queue = live_runner_slot_waiters(records, lambda _record: True)

    assert [waiter.artifact_dir for waiter in queue] == ["/earlier", "/later"]


def test_live_waiter_queue_defaults_missing_or_invalid_priorities() -> None:
    requested_at = "2026-07-12T12:00:00+00:00"
    records = [
        _record("/missing", requested_at=requested_at),
        _record("/boolean", requested_at=requested_at, wait_priority=True),
        _record("/negative", requested_at=requested_at, wait_priority=-1),
        _record("/explicit", requested_at=requested_at, wait_priority=2),
    ]

    queue = live_runner_slot_waiters(records, lambda _record: True)

    assert queue[0].artifact_dir == "/explicit"
    assert {waiter.priority for waiter in queue[1:]} == {DEFAULT_WAIT_PRIORITY}


def _display_key(
    name: str,
    *,
    running_count: int,
    threshold: int | None,
    priority: int | None = None,
    requested_at: str = "2026-07-12T12:00:00+00:00",
) -> tuple[int, int, int, int, datetime, str, str]:
    return runner_slot_queue_display_key(
        running_count=running_count,
        threshold=threshold,
        priority=priority,
        slot_requested_at=requested_at,
        timestamp=name,
        artifact_dir=f"/{name}",
    )


def test_display_key_places_parked_waiter_after_admissible_waiter() -> None:
    ordered = sorted(
        ("drain", "default"),
        key=lambda name: _display_key(
            name,
            running_count=1,
            threshold=0 if name == "drain" else 9,
            priority=1 if name == "drain" else 20,
        ),
    )

    assert ordered == ["default", "drain"]


def test_display_key_orders_parked_waiters_by_threshold_descending() -> None:
    ordered = sorted(
        ("deep", "near"),
        key=lambda name: _display_key(
            name,
            running_count=5,
            threshold=0 if name == "deep" else 4,
            requested_at="2026-07-12T12:00:00+00:00",
        ),
    )

    assert ordered == ["near", "deep"]


def test_display_key_keeps_priority_then_fifo_for_admissible_waiters() -> None:
    ordered = sorted(
        ("older-default", "newer-urgent", "newer-default"),
        key=lambda name: _display_key(
            name,
            running_count=1,
            threshold=9,
            priority=1 if name == "newer-urgent" else DEFAULT_WAIT_PRIORITY,
            requested_at=(
                "2026-07-12T12:00:00+00:00"
                if name == "older-default"
                else "2026-07-12T12:00:01+00:00"
            ),
        ),
    )

    assert ordered == ["newer-urgent", "older-default", "newer-default"]


def test_display_key_treats_missing_threshold_as_zero() -> None:
    missing = _display_key("waiter", running_count=1, threshold=None)
    explicit_zero = _display_key("waiter", running_count=1, threshold=0)

    assert missing == explicit_zero


def test_display_key_degrades_to_admission_key_at_zero_running_count() -> None:
    display = runner_slot_queue_display_key(
        running_count=0,
        threshold=0,
        priority=1,
        slot_requested_at="2026-07-12T12:00:00+00:00",
        timestamp="1",
        artifact_dir="/drain",
    )
    admission = runner_slot_waiter_sort_key(
        priority=1,
        slot_requested_at="2026-07-12T12:00:00+00:00",
        timestamp="1",
        artifact_dir="/drain",
    )

    assert display[:2] == (0, 0)
    assert display[2:] == admission


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
    drain = RunnerSlotWaiter(
        "/drain",
        "2026-07-12T12:00:00+00:00",
        "1",
        threshold=0,
        priority=1,
    )
    immediate = RunnerSlotWaiter(
        "/immediate",
        "2026-07-12T12:00:01+00:00",
        "2",
        threshold=9,
        priority=20,
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
