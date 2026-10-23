"""Collector tests over fixture artifact directories."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from sase.agent.handoff_inflight import HANDOFF_INFLIGHT_MARKER
from sase.agent.pending_handoff import PENDING_HANDOFF_MARKERS
from sase.bead.stranded import load_stranded_report
from sase.bead.stranded_facts import collect_issue_titles, collect_stranded_work_input
from sase.core.agent_scan_wire import DoneMarkerWire
from sase.core.stranded_work_facade import StrandedWorkReport
from tests._stranded_collector_helpers import (
    PROJECT,
    bead_facts,
    child_plan,
    epic,
    phase,
    record,
    task,
    wire_collector,
    write_submission,
)

_NOW = 1_700_000_000.0
_PID = os.getpid()


def _dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "artifacts" / name
    path.mkdir(parents=True)
    return path


def test_keep_chain_records_declared_keep(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-1n6.2")
    write_submission(artifact, "keep")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1n6.2", assignee="sase-1n6.2")],
        [
            record(
                artifact,
                name="sase-1n6.2",
                session="sase-1n6.2",
                done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 3600),
            )
        ],
    )
    payload = collect_stranded_work_input(PROJECT, now=_NOW)
    member = bead_facts(payload, "sase-1n6.2")["members"][0]
    assert member["lifecycle"] == "done"
    assert member["declared_bead_action"] == "keep"
    assert member["process_live"] is False


def test_unclosed_turn_has_no_declared_action(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 10),
            )
        ],
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["declared_bead_action"] is None
    assert member["lifecycle"] == "done"


def test_failed_and_stopped_lifecycles(monkeypatch, tmp_path: Path) -> None:
    failed_dir = _dir(tmp_path, "failed")
    stopped_dir = _dir(tmp_path, "stopped")
    wire_collector(
        monkeypatch,
        tmp_path,
        [
            phase("sase-1.2", assignee="sase-1.2"),
            phase("sase-1.3", assignee="sase-1.3"),
        ],
        [
            record(
                failed_dir,
                name="sase-1.2",
                session="sase-1.2",
                done=DoneMarkerWire(outcome="failed", finished_at=_NOW - 10),
            ),
            record(
                stopped_dir,
                name="sase-1.3",
                session="sase-1.3",
                done=DoneMarkerWire(
                    outcome="completed",
                    repeat_stopped=True,
                    finished_at=_NOW - 10,
                ),
            ),
        ],
    )
    payload = collect_stranded_work_input(PROJECT, now=_NOW)
    assert bead_facts(payload, "sase-1.2")["members"][0]["lifecycle"] == "failed"
    assert bead_facts(payload, "sase-1.3")["members"][0]["lifecycle"] == "stopped"


def test_declared_close_while_bead_still_open(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    write_submission(artifact, "close")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 10),
            )
        ],
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["declared_bead_action"] == "close"


def test_dismissed_session_is_still_collected(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    write_submission(artifact, "keep")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                hidden=True,
                done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 10),
            )
        ],
    )
    bead = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")
    assert len(bead["members"]) == 1
    assert bead["members"][0]["declared_bead_action"] == "keep"


def test_remote_non_terminal_member_is_live_owner(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                run_started_at="2026-10-22T12:00:00-04:00",
                source_machine="apollo",
            )
        ],
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["remote"] is True
    assert member["lifecycle"] == "running"
    assert member["process_live"] is False


@pytest.mark.parametrize("marker", PENDING_HANDOFF_MARKERS)
def test_pending_handoff_marker_owns_the_bead(
    monkeypatch, tmp_path: Path, marker: str
) -> None:
    artifact = _dir(tmp_path, f"sase-1.2-{marker}")
    (artifact / marker).write_text("", encoding="utf-8")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 5),
            )
        ],
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["pending_handoff"] is not None
    assert member["lifecycle"] == "done"


def test_handoff_inflight_marker_is_collected(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    (artifact / HANDOFF_INFLIGHT_MARKER).write_text("{}", encoding="utf-8")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [record(artifact, name="sase-1.2", session="sase-1.2", pid=_PID)],
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["handoff_inflight"] is True


def test_plan_root_shares_the_session(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-1.2--plan")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [
            record(
                artifact,
                name="sase-1.2--plan",
                session="sase-1.2",
                plan=True,
                pid=_PID,
            )
        ],
    )
    members = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ]
    assert members[0]["name"] == "sase-1.2--plan"
    assert members[0]["process_live"] is True


def test_fork_assignee_matches_record_name(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "forked")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="forked")],
        [record(artifact, name="forked", session="sase-1.2", pid=_PID)],
    )
    bead = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")
    assert bead["assignee"] == "forked"
    assert bead["members"][0]["name"] == "forked"
    assert bead["members"][0]["process_live"] is True


def test_child_epic_is_candidate_context_for_the_phase(
    monkeypatch, tmp_path: Path
) -> None:
    parent_dir = _dir(tmp_path, "sase-1.2")
    child_dir = _dir(tmp_path, "sase-1.2.1")
    write_submission(parent_dir, "keep")
    wire_collector(
        monkeypatch,
        tmp_path,
        [
            phase("sase-1.2", assignee="sase-1.2"),
            epic("sase-1.2.1", assignee="sase-1.2.1", parent_id="sase-1.2"),
        ],
        [
            record(
                parent_dir,
                name="sase-1.2",
                session="sase-1.2",
                done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 100),
            ),
            record(
                child_dir,
                name="sase-1.2.1",
                session="sase-1.2.1",
                pid=_PID,
                run_started_at="2026-10-22T12:00:00-04:00",
            ),
        ],
    )
    payload = collect_stranded_work_input(PROJECT, now=_NOW)
    parent = bead_facts(payload, "sase-1.2")
    child = bead_facts(payload, "sase-1.2.1")
    assert parent["kind"] == "phase"
    assert parent["candidate"] is True
    assert child["kind"] == "epic"
    assert child["candidate"] is True
    assert child["parent_id"] == "sase-1.2"
    assert child["members"][0]["process_live"] is True


def test_closed_child_plan_is_context_not_candidate(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    wire_collector(
        monkeypatch,
        tmp_path,
        [
            phase("sase-1.2", assignee="sase-1.2"),
            child_plan(
                "sase-1.2.1",
                parent_id="sase-1.2",
                closed_at="20261022130000",
            ),
        ],
        [
            record(
                artifact,
                name="sase-1.2",
                session="sase-1.2",
                done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 10),
            )
        ],
    )
    payload = collect_stranded_work_input(PROJECT, now=_NOW)
    child = bead_facts(payload, "sase-1.2.1")
    assert child["candidate"] is False
    assert child["kind"] == "plan"
    assert child["closed_at"] is not None
    assert child["members"] == []


def test_in_progress_task_beads_are_candidates(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-9")
    wire_collector(
        monkeypatch,
        tmp_path,
        [task("sase-9", assignee="sase-9")],
        [
            record(
                artifact,
                name="sase-9",
                session="sase-9",
                done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 10),
            )
        ],
    )
    bead = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-9")
    assert bead["kind"] == "task"
    assert bead["candidate"] is True
    titles = collect_issue_titles(PROJECT)
    assert titles["sase-9"] == "Task"


def test_missing_index_marks_records_unavailable(monkeypatch, tmp_path: Path) -> None:
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [],
    )
    monkeypatch.setattr(
        "sase.bead.stranded_facts.default_agent_artifact_index_path",
        lambda: tmp_path / "missing.sqlite",
    )
    bead = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")
    assert bead["records_available"] is False
    assert bead["members"] == []


def test_load_stranded_report_fail_open(monkeypatch, tmp_path: Path) -> None:
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [],
    )

    def boom(_facts: object) -> StrandedWorkReport:
        raise RuntimeError("reducer down")

    monkeypatch.setattr("sase.bead.stranded.reduce_stranded_work", boom)
    report = load_stranded_report(PROJECT, now=_NOW)
    assert report.generated_at == _NOW
    assert report.report.verdicts == ()
    assert report.titles == {}
