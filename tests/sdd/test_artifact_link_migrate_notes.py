from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BeadProject
from sase.sdd.artifact_link_migrate_notes import (
    apply_related_note_migration,
    plan_related_note_migration,
)
from tests._conftest_environment import redirect_sase_home


def test_migrate_notes_worklist_and_convertible_rows() -> None:
    left = Issue("sase-aa", "Left", issue_type=IssueType.PLAN, status=Status.OPEN)
    right = Issue("sase-bb", "Right", issue_type=IssueType.PLAN, status=Status.OPEN)
    left.notes = (
        "RELATED: sase-bb — shares the ACE-TUI flake root cause\n"
        "RELATED: not a parseable line\n"
        "RELATED: deadbeefdeadbeefdeadbeefdeadbeefdeadbeef — mystery commit\n"
    )
    plan = plan_related_note_migration((left, right))
    assert len(plan.conversions) == 1
    assert plan.conversions[0].targets == ("bead:sase-bb",)
    assert plan.conversions[0].why == "shares the ACE-TUI flake root cause"
    reasons = {item.reason for item in plan.worklist}
    assert any("does not match" in reason for reason in reasons)
    assert any("unparseable target" in reason for reason in reasons)


def test_migrate_notes_apply_writes_events_and_migrated_notes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        left = project.create("Left", IssueType.PLAN)
        right = project.create("Right", IssueType.PLAN)
        project.append_note(
            left.id, f"RELATED: {right.id} — shares the ACE-TUI flake root cause"
        )
        plan = plan_related_note_migration(project.list_issues())
        applied = apply_related_note_migration(project, plan)
        reloaded = project.show(left.id)
    assert applied["converted"] == 1
    assert "MIGRATED: linked as related/" in reloaded.notes
    assert "RELATED:" in reloaded.notes
    assert reloaded.links[0].origin == "migrated"
    assert reloaded.links[0].target_ref == f"bead:{right.id}"


def test_migrate_notes_apply_is_available_without_feature_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    with BeadProject.init(tmp_path) as project:
        left = project.create("Left", IssueType.PLAN)
        right = project.create("Right", IssueType.PLAN)
        project.append_note(left.id, f"RELATED: {right.id} — because")
        plan = plan_related_note_migration(project.list_issues())
        applied = apply_related_note_migration(project, plan)
        reloaded = project.show(left.id)
    assert applied["converted"] == 1
    assert reloaded.links[0].target_ref == f"bead:{right.id}"
