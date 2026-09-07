"""Phase 3E: snapshot-backed `list_running_agents`.

These tests exercise the post-Phase-3E call sites in
:mod:`sase.agent.running` against the Phase 3A golden artifact tree. They
pin the filters that the previous direct-walk implementation enforced
(parent-timestamp dedup, `appears_as_agent` skip) on the snapshot adapter,
plus slot occupancy for parallel family children.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.agent.running import (
    _active_status_for_record,
    list_running_agents,
)
from sase.agent.running_listing import _running_from_snapshot
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentMetaWire,
    PendingQuestionMarkerWire,
    WaitingMarkerWire,
)
from sase.core.runner_slots import running_agent_slot_count
from tests._running_agents_snapshot_helpers import (
    artifact_timestamp,
    fixture_processes,
    projects_root_for,
    synthetic_record,
    synthetic_snapshot,
)
from tests.agent_scan_golden.fixture_builder import (
    TS_ACE_RUN_RETRIED_CHILD,
    TS_ACE_RUN_RUNNING,
    TS_HOME_RUNNING,
    build_fixture_tree,
)


def test_list_running_agents_filters_done_and_dead(
    tmp_path: Path,
) -> None:
    """Running listing only emits live ace-run agents without done.json."""
    build_fixture_tree(projects_root_for(tmp_path))
    with fixture_processes(tmp_path, alive=True):
        running = list_running_agents()

    by_ts = {artifact_timestamp(info): info for info in running}

    # The retried child (TS_ACE_RUN_RETRIED_CHILD) has no done.json and
    # carries a live PID. Records without run_started_at are visible as
    # STARTING until execution reaches the RUN timestamp write.
    assert set(by_ts) == {
        TS_HOME_RUNNING,
        TS_ACE_RUN_RUNNING,
        TS_ACE_RUN_RETRIED_CHILD,
    }
    assert by_ts[TS_HOME_RUNNING].status == "RUNNING"
    assert by_ts[TS_ACE_RUN_RUNNING].status == "STARTING"
    assert by_ts[TS_ACE_RUN_RETRIED_CHILD].status == "STARTING"
    assert by_ts[TS_ACE_RUN_RUNNING].duration == "?"
    assert by_ts[TS_ACE_RUN_RUNNING].duration_seconds is None
    assert by_ts[TS_HOME_RUNNING].project == "home"
    assert by_ts[TS_ACE_RUN_RUNNING].project == "myproj"
    # Most-recent-first ordering preserved.
    assert [artifact_timestamp(info) for info in running] == sorted(by_ts, reverse=True)


def test_list_running_agents_empty_when_processes_dead(tmp_path: Path) -> None:
    """When no PIDs are alive, the running list is empty even with markers present."""
    build_fixture_tree(projects_root_for(tmp_path))
    with fixture_processes(tmp_path, alive=False):
        running = list_running_agents()
    assert running == []


def test_list_running_agents_skips_appears_as_agent_false(tmp_path: Path) -> None:
    """An ace-run dir with `appears_as_agent=False` workflow_state is skipped."""
    projects_root = projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    # Drop a workflow_state.json next to the live ace-run agent flagging it
    # as a multi-step orchestrator that should NOT surface as its own row.
    wf_path = (
        projects_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "workflow_state.json"
    )
    wf_path.write_text(
        json.dumps({"workflow_name": "wf", "appears_as_agent": False}),
        encoding="utf-8",
    )

    with fixture_processes(tmp_path, alive=True):
        running = list_running_agents()

    assert TS_ACE_RUN_RUNNING not in {artifact_timestamp(info) for info in running}


def test_list_running_agents_skips_non_parallel_parent_timestamp_followups(
    tmp_path: Path,
) -> None:
    """Non-slot family helpers stay folded instead of becoming CLI rows."""
    projects_root = projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    meta_path = (
        projects_root
        / "myproj"
        / "artifacts"
        / "ace-run"
        / TS_ACE_RUN_RUNNING
        / "agent_meta.json"
    )
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    data["parent_timestamp"] = "20260101000000"
    meta_path.write_text(json.dumps(data), encoding="utf-8")

    with fixture_processes(tmp_path, alive=True):
        running = list_running_agents()

    assert TS_ACE_RUN_RUNNING not in {artifact_timestamp(info) for info in running}


def test_list_running_agents_surfaces_slot_relevant_parallel_children(
    tmp_path: Path,
) -> None:
    root_timestamp = "20260717120000"
    records = [
        synthetic_record(
            tmp_path,
            root_timestamp,
            "root",
            waiting_for=["dependency"],
        ),
        synthetic_record(
            tmp_path,
            "20260717120001",
            "running-phase",
            run_started=True,
            parent_timestamp=root_timestamp,
            agent_family_parallel=True,
        ),
        synthetic_record(
            tmp_path,
            "20260717120002",
            "serial-helper",
            run_started=True,
            parent_timestamp=root_timestamp,
        ),
        synthetic_record(
            tmp_path,
            "20260717120003",
            "dependency-phase",
            parent_timestamp=root_timestamp,
            agent_family_parallel=True,
            waiting_for=["dependency"],
        ),
        synthetic_record(
            tmp_path,
            "20260717120004",
            "queued-phase",
            parent_timestamp=root_timestamp,
            agent_family_parallel=True,
            slot_requested_at="2026-07-17T12:00:04-04:00",
        ),
    ]
    snapshot = synthetic_snapshot(tmp_path, records)

    with (
        fixture_processes(tmp_path, alive=True),
        patch(
            "sase.agent.listing_snapshot._scan_listing_snapshot",
            return_value=snapshot,
        ),
    ):
        running = list_running_agents()

    by_name = {info.name: info for info in running}
    # A live serial child -- a real agent shell doing work, not a monitor --
    # must never go missing from the listing just because it never itself
    # waits at the admission gate.
    assert set(by_name) == {
        "root",
        "running-phase",
        "serial-helper",
        "queued-phase",
    }
    assert by_name["root"].status == "WAITING"
    assert by_name["running-phase"].status == "RUNNING"
    assert by_name["running-phase"].holds_runner_slot is True
    assert by_name["serial-helper"].status == "RUNNING"
    assert by_name["serial-helper"].holds_runner_slot is True
    assert by_name["queued-phase"].status == "WAITING"
    assert by_name["queued-phase"].holds_runner_slot is False


def test_running_listing_slot_occupancy_matches_admission_count(tmp_path: Path) -> None:
    root_timestamp = "20260717130000"
    records = [
        synthetic_record(
            tmp_path,
            root_timestamp,
            "root",
            run_started=True,
            agent_family="root",
        ),
        synthetic_record(
            tmp_path,
            "20260717130001",
            "parallel",
            run_started=True,
            parent_timestamp=root_timestamp,
            agent_family="root",
            agent_family_parallel=True,
        ),
        synthetic_record(
            tmp_path,
            "20260717130002",
            "serial",
            run_started=True,
            parent_timestamp=root_timestamp,
            agent_family="root",
        ),
        synthetic_record(
            tmp_path,
            "20260717130003",
            "done",
            run_started=True,
            done=True,
        ),
        synthetic_record(
            tmp_path,
            "20260717130004",
            "question",
            run_started=True,
            pending_question=True,
        ),
    ]
    snapshot = synthetic_snapshot(tmp_path, records)

    with fixture_processes(tmp_path, alive=True):
        listed = _running_from_snapshot(snapshot)

    admission_count = running_agent_slot_count(records, lambda _record: True)
    assert admission_count == sum(bool(info.holds_runner_slot) for info in listed)


def test_list_running_agents_reports_waiting_marker(tmp_path: Path) -> None:
    """A live pre-run wait marker is reported as WAITING, not RUNNING."""
    projects_root = projects_root_for(tmp_path)
    build_fixture_tree(projects_root)
    artifact_dir = (
        projects_root / "myproj" / "artifacts" / "ace-run" / TS_ACE_RUN_RUNNING
    )
    (artifact_dir / "waiting.json").write_text(
        json.dumps({"waiting_for": ["upstream"]}),
        encoding="utf-8",
    )

    with fixture_processes(tmp_path, alive=True):
        running = list_running_agents()

    by_ts = {artifact_timestamp(info): info for info in running}
    assert by_ts[TS_ACE_RUN_RUNNING].status == "WAITING"
    assert by_ts[TS_ACE_RUN_RUNNING].duration == "?"
    assert by_ts[TS_ACE_RUN_RUNNING].duration_seconds is None


def test_active_status_for_record_reports_wait_completed_as_running() -> None:
    """Post-wait/pre-run-start records are active RUNNING rows."""
    record = AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/tmp/proj",
        project_file="/tmp/proj/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir="/tmp/proj/artifacts/ace-run/20260513120000",
        timestamp="20260513120000",
        agent_meta=AgentMetaWire(wait_completed_at="2026-05-13T16:00:00Z"),
    )

    assert _active_status_for_record(record) == "RUNNING"


def test_active_status_for_answered_question_queued_on_runner_slot(
    tmp_path: Path,
) -> None:
    request_path = tmp_path / "question_request.json"
    request_path.write_text("{}")
    (tmp_path / "question_response.json").write_text("{}")
    record = AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/tmp/proj",
        project_file="/tmp/proj/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir="/tmp/proj/artifacts/ace-run/20260513120000",
        timestamp="20260513120000",
        agent_meta=AgentMetaWire(run_started_at="2026-05-13T16:00:00Z"),
        pending_question=PendingQuestionMarkerWire(request_path=str(request_path)),
        waiting=WaitingMarkerWire(
            wait_runners=0,
            slot_requested_at="2026-05-13T16:05:00Z",
        ),
    )

    assert _active_status_for_record(record) == "WAITING"
