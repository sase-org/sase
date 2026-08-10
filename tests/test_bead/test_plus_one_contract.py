"""Structured task +1 domain, facade, and compatibility persistence tests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from sase.bead.model import IssueType, PhaseSize, Resolution, Status
from sase.bead.project import BeadProject
from sase.bead import db as bead_db
from sase.bead.jsonl import import_from_jsonl


def test_project_plus_one_promotes_and_round_trips_all_persistence(
    tmp_path: Path,
) -> None:
    with BeadProject.init(tmp_path) as project:
        task = project.create(
            "Corroborated task",
            IssueType.TASK,
            size=PhaseSize.MEDIUM,
            created_by="creator-agent",
        )
        project.close(
            [task.id],
            reason="stale close",
            resolution=Resolution.CANCELED,
        )

        issue, changed = project.plus_one(
            task.id.rsplit("-", 1)[-1],
            "reproduced with a clean config",
            reporter="reporter-agent",
            refs=[
                "research:202608/repro.md",
                "research:202608/repro.md",
                "bead:sase-related",
            ],
        )

        assert changed
        assert issue.status == Status.READY
        assert issue.closed_at is None
        assert issue.close_reason is None
        assert issue.resolution is None
        assert issue.plus_one_count == 1
        assert issue.plus_one_evidence[0].reporter == "reporter-agent"
        assert issue.refs == [
            "research:202608/repro.md",
            "bead:sase-related",
        ]
        assert project.stats()["plus_one"] == 1

        projection = json.loads(
            (project.beads_dir / "issues.jsonl").read_text(encoding="utf-8")
        )
        assert projection["plus_one_evidence"][0]["note"] == (
            "reproduced with a clean config"
        )
        mirror = bead_db.init_db(tmp_path / "compatibility-mirror.db")
        import_from_jsonl(project.beads_dir / "issues.jsonl", mirror)
        mirrored = mirror.execute(
            "SELECT plus_one_evidence FROM issues WHERE id = ?", (task.id,)
        ).fetchone()
        assert mirrored is not None
        assert json.loads(mirrored[0])[0]["reporter"] == "reporter-agent"
        mirror.close()

    with BeadProject(tmp_path) as reopened:
        issue = reopened.show(task.id)
        assert issue.plus_one_count == 1
        assert issue.plus_one_evidence[0].refs == (
            "research:202608/repro.md",
            "bead:sase-related",
        )


def test_project_plus_one_creator_and_repeat_are_noops(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path) as project:
        task = project.create(
            "Corroborated task",
            IssueType.TASK,
            size=PhaseSize.SMALL,
            created_by="creator-agent",
        )
        issues_path = project.beads_dir / "issues.jsonl"
        before_creator = issues_path.read_bytes()

        creator_issue, creator_changed = project.plus_one(
            task.id,
            "creator retry",
            reporter="creator-agent",
        )
        assert not creator_changed
        assert creator_issue.plus_one_count == 0
        assert issues_path.read_bytes() == before_creator

        _, first_changed = project.plus_one(
            task.id,
            "first reproduction",
            reporter="reporter-agent",
        )
        assert first_changed
        before_repeat = issues_path.read_bytes()
        repeat_issue, repeat_changed = project.plus_one(
            task.id,
            "supplemental detail",
            reporter="reporter-agent",
            refs=["research:202608/later.md"],
        )
        assert not repeat_changed
        assert repeat_issue.plus_one_count == 1
        assert issues_path.read_bytes() == before_repeat


def test_project_plus_one_with_stale_observed_since_records_but_withholds_reopen(
    tmp_path: Path,
) -> None:
    with BeadProject.init(tmp_path) as project:
        task = project.create(
            "Corroborated task",
            IssueType.TASK,
            size=PhaseSize.SMALL,
            assignee="finisher-agent",
            created_by="creator-agent",
        )
        project.close([task.id], reason="fixed", resolution=Resolution.DONE)
        closed = project.show(task.id)
        assert closed.closed_at is not None

        issue, changed = project.plus_one(
            task.id,
            "saw this before the fix landed",
            reporter="reporter-agent",
            observed_since="2026-01-01T00:00:00Z",
        )

        assert changed
        assert issue.status == Status.CLOSED
        assert issue.assignee == "finisher-agent"
        outcome = project.last_mutation_outcome
        assert outcome["reopen_withheld"] is True
        assert outcome["reopen_withheld_closed_at"] == closed.closed_at

        projection = json.loads(
            (project.beads_dir / "issues.jsonl").read_text(encoding="utf-8")
        )
        assert projection["plus_one_evidence"][0]["observed_since"] == (
            "2026-01-01T00:00:00Z"
        )
        mirror = bead_db.init_db(tmp_path / "compatibility-mirror.db")
        import_from_jsonl(project.beads_dir / "issues.jsonl", mirror)
        mirrored = mirror.execute(
            "SELECT plus_one_evidence FROM issues WHERE id = ?", (task.id,)
        ).fetchone()
        assert mirrored is not None
        assert json.loads(mirrored[0])[0]["observed_since"] == ("2026-01-01T00:00:00Z")
        mirror.close()


def test_project_plus_one_with_fresh_observed_since_reopens_and_clears_assignee(
    tmp_path: Path,
) -> None:
    with BeadProject.init(tmp_path) as project:
        task = project.create(
            "Corroborated task",
            IssueType.TASK,
            size=PhaseSize.SMALL,
            assignee="finisher-agent",
            created_by="creator-agent",
        )
        project.close([task.id], reason="fixed", resolution=Resolution.DONE)

        issue, changed = project.plus_one(
            task.id,
            "reproduced after the fix landed",
            reporter="reporter-agent",
            observed_since="2099-01-01T00:00:00Z",
        )

        assert changed
        assert issue.status == Status.READY
        assert issue.assignee == ""
        outcome = project.last_mutation_outcome
        assert outcome["reopen_withheld"] is False
        assert outcome.get("reopen_withheld_closed_at") is None


def test_project_plus_one_without_observed_since_still_reopens_legacy_style(
    tmp_path: Path,
) -> None:
    with BeadProject.init(tmp_path) as project:
        task = project.create(
            "Corroborated task",
            IssueType.TASK,
            size=PhaseSize.SMALL,
            created_by="creator-agent",
        )
        project.close([task.id], reason="fixed", resolution=Resolution.DONE)

        issue, changed = project.plus_one(
            task.id,
            "no observation window provided",
            reporter="reporter-agent",
        )

        assert changed
        assert issue.status == Status.READY
        outcome = project.last_mutation_outcome
        assert outcome["reopen_withheld"] is False


def test_project_rejects_plus_one_on_non_task_without_writes(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path) as project:
        plan = project.create("Plan", IssueType.PLAN)
        issues_path = project.beads_dir / "issues.jsonl"
        before = issues_path.read_bytes()

        with pytest.raises(ValueError, match="only applies to task beads"):
            project.plus_one(plan.id, "not a task", reporter="reporter-agent")

        assert issues_path.read_bytes() == before


def test_core_create_requires_size_but_legacy_sizeless_task_still_loads(
    tmp_path: Path,
) -> None:
    with BeadProject.init(tmp_path) as project:
        issues_path = project.beads_dir / "issues.jsonl"
        before = issues_path.read_bytes()
        with pytest.raises(ValueError, match="requires an explicit size"):
            project.create("Missing size", IssueType.TASK)
        assert issues_path.read_bytes() == before

    legacy = {
        "id": "sase-legacy",
        "title": "Legacy sizeless task",
        "status": "open",
        "issue_type": "task",
        "parent_id": None,
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "dependencies": [],
    }
    issues_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    events_dir = issues_path.parent / "events"
    if events_dir.exists():
        shutil.rmtree(events_dir)

    with BeadProject(tmp_path) as project:
        loaded = project.show("sase-legacy")
        assert loaded.issue_type == IssueType.TASK
        assert loaded.size is None
        assert loaded.plus_one_count == 0
