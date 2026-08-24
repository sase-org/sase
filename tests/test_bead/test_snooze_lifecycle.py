"""End-to-end snooze lifecycle through the Rust-backed bead store."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead import db as bead_db
from sase.bead.jsonl import import_from_jsonl
from sase.bead.model import IssueType, PhaseSize, Status
from sase.bead.project import BeadProject

UNTIL = "2026-08-09T09:00:00-04:00"
FROZEN_NOW = "2026-08-06T13:00:00Z"


@pytest.fixture(autouse=True)
def frozen_snooze_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("sase.bead.project._now", lambda: FROZEN_NOW)


def _ready_task(project: BeadProject) -> str:
    task = project.create(
        "A deferrable task",
        IssueType.TASK,
        task_type="bug",
        size=PhaseSize.MEDIUM,
        created_by="creator-agent",
    )
    project.update(task.id, status=Status.READY.value)
    return task.id


def test_snooze_round_trips_through_every_persistence_surface(
    tmp_path: Path,
) -> None:
    with BeadProject.init(tmp_path) as project:
        task_id = _ready_task(project)

        issue = project.snooze(
            task_id.rsplit("-", 1)[-1],
            until=UNTIL,
            actor="bryanbugyi34@gmail.com",
            plus_ones=2,
            reason="waiting on upstream",
        )

        assert issue.status is Status.SNOOZED
        assert issue.snooze is not None
        assert issue.snooze.until == UNTIL
        assert issue.snooze.snoozed_by == "bryanbugyi34@gmail.com"
        assert issue.snooze.reason == "waiting on upstream"
        assert issue.snooze.plus_one_target == 2
        assert issue.snooze.plus_one_baseline == 0

        # The snooze note is what survives the wake that clears the record
        # above, so every persistence surface below must carry it unchanged.
        assert issue.notes_text.startswith(
            f"[{issue.snooze.snoozed_at} · {issue.snooze.snoozed_by}] "
            f"Snoozed until {UNTIL} (in "
        )
        assert issue.notes_text.endswith(
            "Also wakes at 2 more +1s. Reason: waiting on upstream"
        )

        assert project.show(task_id).snooze == issue.snooze
        assert project.show(task_id).notes == issue.notes

        # A snoozed bead stays live work: default filters must not hide it.
        assert task_id in {row.id for row in project.list_issues()}

        beads_dir = project.beads_dir
        conn = bead_db.init_db(beads_dir / "mirror.db")
        try:
            import_from_jsonl(beads_dir / "issues.jsonl", conn)
            mirrored = bead_db.get_issue(conn, task_id)
        finally:
            conn.close()

    assert mirrored is not None
    assert mirrored.status is Status.SNOOZED
    assert mirrored.snooze == issue.snooze
    assert mirrored.notes == issue.notes


def test_cancel_snooze_returns_the_bead_to_ready(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path) as project:
        task_id = _ready_task(project)
        project.snooze(task_id, until=UNTIL, actor="owner")

        issue = project.cancel_snooze(task_id, actor="owner")

        assert issue.status is Status.READY
        assert issue.snooze is None


def test_plus_one_target_wakes_the_bead_with_the_preset_note(
    tmp_path: Path,
) -> None:
    with BeadProject.init(tmp_path) as project:
        task_id = _ready_task(project)
        project.snooze(task_id, until=UNTIL, actor="owner", plus_ones=2)

        below, _ = project.plus_one(task_id, "hit this too", reporter="agent-a")
        assert below.status is Status.SNOOZED
        assert below.snooze is not None

        woken, _ = project.plus_one(task_id, "and again", reporter="agent-b")
        assert woken.status is Status.READY
        assert woken.snooze is None
        assert "Reopened by +1 threshold: reached 2 +1s" in woken.notes_text


def test_update_refuses_the_snoozed_status_shortcut(tmp_path: Path) -> None:
    with BeadProject.init(tmp_path) as project:
        task_id = _ready_task(project)

        with pytest.raises(ValueError, match="use: sase bead snooze"):
            project.update(task_id, status="snoozed")


def test_snoozing_rejects_past_wake_times_and_non_task_beads(
    tmp_path: Path,
) -> None:
    with BeadProject.init(tmp_path) as project:
        task_id = _ready_task(project)
        with pytest.raises(ValueError, match="wake time must be in the future"):
            project.snooze(task_id, until="2020-01-01T00:00:00Z", actor="owner")

        epic = project.create("An epic", IssueType.PLAN)
        with pytest.raises(ValueError, match="only applies to task beads"):
            project.snooze(epic.id, until=UNTIL, actor="owner")
