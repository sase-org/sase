"""Waiting-agent bead claim lifecycle tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.bead.claims import (
    claim_bead_for_waiting_agent,
    release_bead_claim_for_agent,
)
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject

from .sync_test_helpers import init_git_repo


def _project_with_committed_phase(tmp_path: Path) -> tuple[Path, str]:
    init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("sdd/beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(tmp_path) as project:
        epic = project.create("Epic", IssueType.PLAN)
        phase = project.create("Phase", IssueType.PHASE, parent_id=epic.id)
        beads_dir = project.beads_dir
    subprocess.run(
        ["git", "add", ".gitignore", "sdd/beads"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "initial bead"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return beads_dir, phase.id


def _commit_count(repo: Path) -> int:
    result = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip())


def test_claim_reclaim_and_release_use_canonical_store_without_commit_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beads_dir, bead_id = _project_with_committed_phase(tmp_path)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    initial_commits = _commit_count(tmp_path)

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    assert _commit_count(tmp_path) == initial_commits + 1
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.CLAIMED, "worker")

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    assert _commit_count(tmp_path) == initial_commits + 1

    assert release_bead_claim_for_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    assert _commit_count(tmp_path) == initial_commits + 2
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.OPEN, "")

    subjects = subprocess.run(
        ["git", "log", "-2", "--format=%s"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert subjects == [
        f"chore(beads): release claim on {bead_id} from worker",
        f"chore(beads): claim {bead_id} for worker",
    ]


def test_declined_wait_claim_leaves_in_progress_store_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beads_dir, bead_id = _project_with_committed_phase(tmp_path)
    with BeadProject(tmp_path) as project:
        project.update(bead_id, status=Status.IN_PROGRESS.value, assignee="active")
    subprocess.run(["git", "add", "sdd/beads"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "mark active"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    before = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    commits = _commit_count(tmp_path)

    assert not claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="waiting",
    )

    assert _commit_count(tmp_path) == commits
    assert (
        subprocess.run(
            ["git", "status", "--porcelain=v1"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == before
    )
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.IN_PROGRESS, "active")


def test_claim_helpers_degrade_store_failures_to_warnings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: (_ for _ in ()).throw(RuntimeError("store unavailable")),
    )

    assert not claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )
    assert not release_bead_claim_for_agent(
        project_name="proj",
        bead_id="sase-1",
        agent_name="worker",
    )

    stderr = capsys.readouterr().err
    assert "Warning: Failed to claim bead 'sase-1'" in stderr
    assert "Warning: Failed to release bead claim on 'sase-1'" in stderr
