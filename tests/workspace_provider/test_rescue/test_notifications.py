"""Workspace-rescue notices dedup per rescued workspace and rescue cause."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.axe.runner_workspace_sidecar import report_sidecar_may_be_lost
from sase.notifications.models import Notification
from sase.notifications.store import load_notifications, mark_dismissed
from sase.workspace_provider.rescue import (
    RESCUE_NOTIFICATION_SENDER,
    quarantine_directory,
    rescue_dedup_key,
)


@pytest.fixture(autouse=True)
def _sase_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    return home


def _rescue_rows(*, include_dismissed: bool = False) -> list[Notification]:
    return [
        row
        for row in load_notifications(include_dismissed=include_dismissed)
        if row.sender == RESCUE_NOTIFICATION_SENDER
    ]


def _quarantine(workspace: Path, name: str, reason: str) -> Path:
    leftover = workspace / "sase" / "repos" / name
    leftover.mkdir(parents=True)
    (leftover / "notes.txt").write_text("unpublished\n", encoding="utf-8")
    record = quarantine_directory(
        leftover,
        workspace_dir=workspace,
        workspace_num=10,
        label=f"linked-{name}",
        reason=reason,
    )
    assert record is not None
    return record.rescue_dir


def test_repeated_rescues_of_one_workspace_share_one_row(tmp_path: Path) -> None:
    workspace = tmp_path / "project_10"
    reason = "launch-time eviction of linked or external repo clone"

    first_dir = _quarantine(workspace, "sase-core", reason)
    second_dir = _quarantine(workspace, "bob-plugins", reason)
    third_dir = _quarantine(workspace, "sase-core", reason)

    rows = _rescue_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.dedup_key == rescue_dedup_key(workspace, reason)
    assert row.files == [str(first_dir)]
    notes = [plus_one.note for plus_one in row.plus_ones]
    assert len(notes) == 2
    assert str(second_dir) in notes[0]
    assert notes[0].startswith("Rescued linked-bob-plugins again: ")
    assert str(third_dir) in notes[1]


def test_rescue_causes_and_workspaces_keep_separate_rows(tmp_path: Path) -> None:
    eviction = "launch-time eviction of linked or external repo clone"
    nested = "launch-time eviction: nested repository preservation"

    _quarantine(tmp_path / "project_10", "a", eviction)
    _quarantine(tmp_path / "project_10", "b", nested)
    _quarantine(tmp_path / "project_11", "a", eviction)

    assert len(_rescue_rows()) == 3


def test_rescue_after_dismissal_opens_a_fresh_row(tmp_path: Path) -> None:
    workspace = tmp_path / "project_10"
    reason = "self-heal: checkout has rebase"

    _quarantine(workspace, "a", reason)
    first = _rescue_rows()[0]
    assert mark_dismissed(first.id)
    second_dir = _quarantine(workspace, "b", reason)

    live = _rescue_rows()
    assert len(live) == 1
    assert live[0].id != first.id
    assert live[0].files == [str(second_dir)]


def test_rescue_cause_ignores_run_numbers_and_ids(tmp_path: Path) -> None:
    workspace = tmp_path / "project_27"

    assert rescue_dedup_key(
        workspace, "failed finalization for host run 27"
    ) == rescue_dedup_key(workspace, "failed finalization for host run 31")
    assert rescue_dedup_key(
        workspace,
        "bead store held 2 unpublished local bead commit(s) "
        "(retained at refs/sase/recovery/20261119T101500Z-main-b3a9c1d2e)",
    ) == rescue_dedup_key(
        workspace,
        "bead store held 1 unpublished local bead commit(s) "
        "(retained at refs/sase/recovery/20261120T080000Z-main-0f1e2d3c4)",
    )
    assert rescue_dedup_key(
        workspace, "self-heal: checkout has rebase"
    ) != rescue_dedup_key(workspace, "self-heal: rebase onto origin/master conflicted")
    assert rescue_dedup_key(workspace, "same cause") != rescue_dedup_key(
        tmp_path / "project_28", "same cause"
    )


def test_unrescued_sidecar_reports_share_one_row(tmp_path: Path) -> None:
    repo_root = tmp_path / "project_10" / "sase" / "repos" / "beads"

    report_sidecar_may_be_lost(repo_root=repo_root, remaining=2, detail="push failed")
    report_sidecar_may_be_lost(
        repo_root=repo_root, remaining=3, detail="rebase conflicted"
    )

    rows = _rescue_rows()
    assert len(rows) == 1
    assert rows[0].notes[0].startswith("Sidecar commits in beads could not be rescued")
    assert [plus_one.note for plus_one in rows[0].plus_ones] == [
        "Still could not rescue beads: rebase conflicted"
    ]
