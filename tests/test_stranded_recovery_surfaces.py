"""Recovery-surface integration: collector, reducer, and waiter release."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

from sase.bead.model import IssueType, PhaseSize, Resolution, Status
from sase.bead.project import BeadProject
from sase.bead.stranded import load_stranded_report
from sase.bead.stranded_facts import collect_stranded_work_input
from sase.bead.wait_status import closed_bead_ids_for_waits
from sase.core import bead_mutation_facade as rust_beads
from sase.core.agent_scan_wire import DoneMarkerWire
from sase.core.stranded_work_facade import reduce_stranded_work
from tests._stranded_collector_helpers import PROJECT, bead_facts, record
from tests._wait_epic_follow_release_helpers import (
    build_release_index,
    decide_release,
    make_release_marker,
    make_release_planner,
    make_release_waiter,
)

_FAILED_AT = "2026-10-26T18:00:00+00:00"
_NOW = datetime.fromisoformat(_FAILED_AT).timestamp() + 3_600.0
_PID = os.getpid()


def _seed_git_store(root: Path) -> BeadProject:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "config", "user.name", "probe"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "probe@example.invalid"], cwd=root, check=True
    )
    return BeadProject.init(root)


def _recover_unassigned_task(project: BeadProject, tmp_path: Path) -> str:
    task = project.create(
        "Unassigned source task",
        IssueType.TASK,
        task_type="bug",
        size=PhaseSize.SMALL,
        created_by="probe",
    )
    project.close(
        [task.id],
        resolution=Resolution.DONE,
        close_provenance={
            "run_id": "origin-run",
            "agent_name": "origin-agent",
            "artifact_dir": str(tmp_path / "artifacts"),
        },
    )
    report = rust_beads.recover_failed_closes(
        project.beads_dir,
        {
            "run_id": "origin-run",
            "failed_at": "2026-10-26T18:00:00Z",
            "failure_code": "hook_failed",
            "evidence_locations": [str(tmp_path / "artifacts")],
            "note": "STITCH FAILED: hook failed for run origin-run.",
            "actor": "origin-agent",
        },
    )
    assert report["changed"] is True
    return task.id


def _point_collector_at_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, beads_dir: Path
) -> None:
    monkeypatch.setattr(
        "sase.bead.stranded_facts.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    monkeypatch.setattr(
        "sase.bead.stranded_facts.default_agent_artifact_index_path",
        lambda: tmp_path / "missing-index.sqlite",
    )


def test_recovered_bead_feeds_stranded_report_after_settle_grace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _seed_git_store(tmp_path / "store") as project:
        task_id = _recover_unassigned_task(project, tmp_path)
        beads_dir = project.beads_dir
        recovered = project.show(task_id)
        assert recovered.status == Status.OPEN
        assert recovered.assignee == ""
        assert recovered.completion_failure is not None
        notes = [
            note.text
            for note in recovered.notes
            if note.text.startswith("STITCH FAILED:")
        ]
        assert len(notes) == 1
        rust_beads.recover_failed_closes(
            project.beads_dir,
            {
                "run_id": "origin-run",
                "failed_at": "2026-10-26T18:01:00Z",
                "failure_code": "hook_failed",
                "evidence_locations": [str(tmp_path / "artifacts")],
                "note": "STITCH FAILED: hook failed for run origin-run.",
                "actor": "origin-agent",
            },
        )
        retried = project.show(task_id)
        assert (
            len(
                [
                    note
                    for note in retried.notes
                    if note.text.startswith("STITCH FAILED:")
                ]
            )
            == 1
        )
    _point_collector_at_store(monkeypatch, tmp_path, beads_dir)
    payload = collect_stranded_work_input(PROJECT, now=_NOW)
    bead = bead_facts(payload, task_id)
    assert bead["status"] == "open"
    assert bead["assignee"] is None
    assert bead["candidate"] is True
    assert bead["completion_failure"]["run_id"] == "origin-run"
    report = reduce_stranded_work(payload)
    assert report.stranded_ids == (task_id,)
    assert report.verdicts[0].reason == "failed"
    assert report.verdicts[0].completion_failure is not None
    loaded = load_stranded_report(PROJECT, now=_NOW)
    assert loaded.report.stranded_ids == (task_id,)
    assert loaded.titles[task_id] == "Unassigned source task"


def test_live_successor_owns_recovered_work(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _seed_git_store(tmp_path / "store") as project:
        task_id = _recover_unassigned_task(project, tmp_path)
        claimed = project.claim_for_agent_launch(task_id, "successor")
        assert claimed.status == Status.IN_PROGRESS
        assert claimed.assignee == "successor"
        assert claimed.completion_failure is None
        beads_dir = project.beads_dir
    artifact = tmp_path / "artifacts" / "successor"
    artifact.mkdir(parents=True)
    live = record(
        artifact,
        name="successor",
        session="successor",
        pid=_PID,
        run_started_at="2026-10-26T19:00:00-04:00",
    )
    _point_collector_at_store(monkeypatch, tmp_path, beads_dir)
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_bytes(b"")
    monkeypatch.setattr(
        "sase.bead.stranded_facts.default_agent_artifact_index_path", lambda: index
    )
    from sase.core.agent_scan_wire import (
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
    )

    def query(_index_path, projects_root, _query, options):
        return AgentArtifactScanWire(
            schema_version=12,
            projects_root=str(projects_root),
            options=options or AgentArtifactScanOptionsWire(),
            stats=AgentArtifactScanStatsWire(),
            records=[live],
        )

    monkeypatch.setattr("sase.bead.stranded_facts.query_agent_artifact_index", query)
    report = reduce_stranded_work(collect_stranded_work_input(PROJECT, now=_NOW))
    assert report.stranded_ids == ()
    assert report.verdicts[0].bead_id == task_id
    assert report.verdicts[0].state == "owned"


def test_new_close_clears_stranded_verdict(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _seed_git_store(tmp_path / "store") as project:
        task_id = _recover_unassigned_task(project, tmp_path)
        project.close([task_id], resolution=Resolution.DONE)
        closed = project.show(task_id)
        assert closed.status == Status.CLOSED
        assert closed.completion_failure is None
        beads_dir = project.beads_dir
    _point_collector_at_store(monkeypatch, tmp_path, beads_dir)
    payload = collect_stranded_work_input(PROJECT, now=_NOW)
    assert all(item["id"] != task_id for item in payload["beads"])
    report = reduce_stranded_work(payload)
    assert report.stranded_ids == ()
    assert report.verdicts == ()


def test_in_progress_parent_is_blocked_by_recovered_phase(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _seed_git_store(tmp_path / "store") as project:
        plan = project.create("Recovery plan", IssueType.PLAN, tier="epic")
        phase = project.create(
            "Recovery phase",
            IssueType.PHASE,
            parent_id=plan.id,
            size=PhaseSize.MEDIUM,
            created_by="probe",
        )
        project.update(plan.id, status="in_progress", assignee="sase-plan.land")
        project.close(
            [phase.id],
            resolution=Resolution.DONE,
            close_provenance={
                "run_id": "origin-run",
                "agent_name": "origin-agent",
                "artifact_dir": str(tmp_path / "artifacts"),
            },
        )
        rust_beads.recover_failed_closes(
            project.beads_dir,
            {
                "run_id": "origin-run",
                "failed_at": "2026-10-26T18:00:00Z",
                "failure_code": "hook_failed",
                "evidence_locations": [str(tmp_path / "artifacts")],
                "note": "STITCH FAILED: hook failed for run origin-run.",
                "actor": "origin-agent",
            },
        )
        recovered = project.show(phase.id)
        parent = project.show(plan.id)
        assert recovered.status == Status.OPEN
        assert parent.status == Status.IN_PROGRESS
        beads_dir = project.beads_dir
        phase_id = phase.id
        plan_id = plan.id
    lander = tmp_path / "artifacts" / "lander"
    origin = tmp_path / "artifacts" / "origin"
    lander.mkdir(parents=True)
    origin.mkdir(parents=True)
    live_parent = record(
        lander,
        name="sase-plan.land",
        session="sase-plan.land",
        pid=_PID,
        run_started_at="2026-10-26T19:00:00-04:00",
    )
    dead_phase = record(
        origin,
        name="origin-agent",
        session="origin-session",
        done=DoneMarkerWire(outcome="failed", finished_at=_NOW - 3600),
    )
    _point_collector_at_store(monkeypatch, tmp_path, beads_dir)
    index = tmp_path / "agent_artifact_index.sqlite"
    index.write_bytes(b"")
    monkeypatch.setattr(
        "sase.bead.stranded_facts.default_agent_artifact_index_path", lambda: index
    )
    from sase.core.agent_scan_wire import (
        AgentArtifactScanOptionsWire,
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
    )

    def query(_index_path, projects_root, _query, options):
        return AgentArtifactScanWire(
            schema_version=12,
            projects_root=str(projects_root),
            options=options or AgentArtifactScanOptionsWire(),
            stats=AgentArtifactScanStatsWire(),
            records=[live_parent, dead_phase],
        )

    monkeypatch.setattr("sase.bead.stranded_facts.query_agent_artifact_index", query)
    report = reduce_stranded_work(collect_stranded_work_input(PROJECT, now=_NOW))
    assert phase_id in report.stranded_ids
    assert plan_id in report.blocked_ids


def test_reopened_bead_keeps_waiter_parked_until_verified_close(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with _seed_git_store(tmp_path / "store") as project:
        task_id = _recover_unassigned_task(project, tmp_path)
        beads_dir = project.beads_dir
        monkeypatch.setattr(
            "sase.bead.store_locator.canonical_beads_dir_for_project",
            lambda _project: beads_dir,
        )
        monkeypatch.setattr(
            "sase.bead.wait_status.enabled_project_store_snapshots",
            lambda: (),
        )
        planner = make_release_planner(tmp_path, "20261026180000")
        waiter = make_release_waiter(tmp_path)
        index = build_release_index(planner)
        closed = closed_bead_ids_for_waits("proj", [task_id]).closed_ids
        assert task_id not in (closed or frozenset())
        agent_only = decide_release(
            index, make_release_marker(["planner"], None), waiter, closed=closed
        )
        assert agent_only.releasable is True
        parked = decide_release(
            index,
            make_release_marker(["planner"], None, wait_for_beads=[task_id]),
            waiter,
            closed=closed,
        )
        assert parked.status.resolved is False
        assert parked.releasable is False
        assert task_id in parked.status.blocked_on
        project.close([task_id], resolution=Resolution.DONE)
        released_closed = closed_bead_ids_for_waits("proj", [task_id]).closed_ids
        released = decide_release(
            index,
            make_release_marker(["planner"], None, wait_for_beads=[task_id]),
            waiter,
            closed=released_closed,
        )
        assert task_id in (released_closed or frozenset())
        assert released.status.resolved is True
        assert released.releasable is True
