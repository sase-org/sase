"""CLI coverage for the atomic multi-ID ``sase bead update`` mutation."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.bead import cli as bead_cli
from sase.bead.model import Issue, IssueType, Status
from sase.bead.project import BeadProject


def _create_issue(project_dir: Path, title: str) -> Issue:
    with BeadProject(project_dir) as proj:
        return proj.create(title, IssueType.TASK)


def _update_args(ids: list[str], **fields: object) -> argparse.Namespace:
    base: dict[str, object] = {
        "ids": ids,
        "status": None,
        "title": None,
        "description": None,
        "notes": None,
        "design": None,
        "assignee": None,
        "tier": None,
        "model": None,
        "size": None,
    }
    base.update(fields)
    return argparse.Namespace(**base)


def _issues_jsonl(project_dir: Path) -> Path:
    return project_dir / "sdd" / "beads" / "issues.jsonl"


def test_multi_id_update_applies_same_field_and_returns_issues_in_argument_order(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = _create_issue(project_dir, "First")
    second = _create_issue(project_dir, "Second")
    third = _create_issue(project_dir, "Third")

    bead_cli.handle_bead_update(
        _update_args([third.id, first.id, second.id], status="in_progress")
    )

    output = capsys.readouterr().out
    assert output.splitlines() == [
        f"✓ Updated issue: {third.id} — {third.title}",
        f"✓ Updated issue: {first.id} — {first.title}",
        f"✓ Updated issue: {second.id} — {second.title}",
    ]
    with BeadProject(project_dir) as proj:
        for issue_id in (first.id, second.id, third.id):
            assert proj.show(issue_id).status is Status.IN_PROGRESS


def test_multi_id_update_commits_once_with_ids_in_argument_order(
    project_dir: Path,
) -> None:
    first = _create_issue(project_dir, "First")
    second = _create_issue(project_dir, "Second")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_update(_update_args([second.id, first.id], status="ready"))

    auto_commit.assert_called_once_with(
        f"chore(beads): update {second.id} {first.id}",
        push_after_commit=False,
        already_locked=False,
    )


def test_mixed_batch_commits_only_changed_ids_and_prints_unchanged_rows(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    stale = _create_issue(project_dir, "Already there")
    with BeadProject(project_dir) as proj:
        stale = proj.update(stale.id, status="in_progress")
    fresh = _create_issue(project_dir, "Needs the update")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_update(
            _update_args([stale.id, fresh.id], status="in_progress")
        )

    auto_commit.assert_called_once_with(
        f"chore(beads): update {fresh.id}",
        push_after_commit=False,
        already_locked=False,
    )
    output = capsys.readouterr().out
    assert f"· Unchanged: {stale.id} — {stale.title}" in output
    assert f"✓ Updated issue: {fresh.id} — {fresh.title}" in output


def test_all_no_op_batch_makes_no_commit(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = _create_issue(project_dir, "Same title")
    second = _create_issue(project_dir, "Same title")

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_update(
            _update_args([first.id, second.id], title="Same title")
        )

    auto_commit.assert_not_called()
    output = capsys.readouterr().out
    assert f"· Unchanged: {first.id} — {first.title}" in output
    assert f"· Unchanged: {second.id} — {second.title}" in output


def test_unknown_id_in_the_middle_exits_without_writing(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = _create_issue(project_dir, "First")
    second = _create_issue(project_dir, "Second")
    jsonl_path = _issues_jsonl(project_dir)
    before = jsonl_path.read_bytes()

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        with pytest.raises(SystemExit) as excinfo:
            bead_cli.handle_bead_update(
                _update_args([first.id, "missing", second.id], status="in_progress")
            )

    assert excinfo.value.code == 1
    auto_commit.assert_not_called()
    assert "Error: issue not found: missing" in capsys.readouterr().err
    assert jsonl_path.read_bytes() == before


def test_invalid_field_value_leaves_every_target_unmodified(
    project_dir: Path,
) -> None:
    first = _create_issue(project_dir, "First")
    second = _create_issue(project_dir, "Second")
    jsonl_path = _issues_jsonl(project_dir)
    before = jsonl_path.read_bytes()

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        with pytest.raises(SystemExit) as excinfo:
            bead_cli.handle_bead_update(
                _update_args([first.id, second.id], model="bad\nmodel")
            )

    assert excinfo.value.code == 1
    auto_commit.assert_not_called()
    assert jsonl_path.read_bytes() == before


def test_shorthand_and_full_form_of_same_bead_collapse_to_one_update(
    project_dir: Path,
) -> None:
    issue = _create_issue(project_dir, "Collapsible")
    shorthand = issue.id.rsplit("-", 1)[1]

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        bead_cli.handle_bead_update(
            _update_args([issue.id, shorthand], status="in_progress")
        )

    auto_commit.assert_called_once_with(
        f"chore(beads): update {issue.id}",
        push_after_commit=False,
        already_locked=False,
    )
    with BeadProject(project_dir) as proj:
        assert proj.show(issue.id).status is Status.IN_PROGRESS


@pytest.mark.parametrize("child_first", [False, True])
def test_status_closed_succeeds_across_parent_and_child_in_either_order(
    project_dir: Path,
    child_first: bool,
) -> None:
    with BeadProject(project_dir) as proj:
        parent = proj.create("Parent", IssueType.PLAN)
        child = proj.create("Child", IssueType.PHASE, parent_id=parent.id)

    ids = [child.id, parent.id] if child_first else [parent.id, child.id]
    bead_cli.handle_bead_update(_update_args(ids, status="closed"))

    with BeadProject(project_dir) as proj:
        assert proj.show(parent.id).status is Status.CLOSED
        assert proj.show(child.id).status is Status.CLOSED


def test_status_closed_rejects_batch_with_out_of_batch_descendant(
    project_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with BeadProject(project_dir) as proj:
        parent = proj.create("Parent", IssueType.PLAN)
        in_batch_child = proj.create("In batch", IssueType.PHASE, parent_id=parent.id)
        out_of_batch_child = proj.create(
            "Out of batch", IssueType.PHASE, parent_id=parent.id
        )
    jsonl_path = _issues_jsonl(project_dir)
    before = jsonl_path.read_bytes()

    with patch("sase.bead.cli_crud.auto_commit_bead_store") as auto_commit:
        with pytest.raises(SystemExit) as excinfo:
            bead_cli.handle_bead_update(
                _update_args([parent.id, in_batch_child.id], status="closed")
            )

    assert excinfo.value.code == 1
    auto_commit.assert_not_called()
    assert out_of_batch_child.id in capsys.readouterr().err
    assert jsonl_path.read_bytes() == before
