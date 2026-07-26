"""Bead claim lifecycle and publication tests."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_bead import claim_bead_for_agent_launch
from sase.bead.claims import (
    BeadClaimReleaseOutcome,
    claim_bead_for_waiting_agent,
    release_bead_claim_for_agent,
)
from sase.bead.model import IssueType, Status
from sase.bead.project import BeadProject
from sase.bead.sync import _PushOutcome
from sase.sdd.store import SddStore

from .claims_test_helpers import commit_count, project_with_committed_phase
from .sync_test_helpers import init_git_repo


def test_claim_reclaim_and_release_use_canonical_store_without_commit_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    beads_dir, bead_id = project_with_committed_phase(tmp_path)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    initial_commits = commit_count(tmp_path)

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    assert commit_count(tmp_path) == initial_commits + 1
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.CLAIMED, "worker")

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    assert commit_count(tmp_path) == initial_commits + 1

    assert (
        release_bead_claim_for_agent(
            project_name="proj",
            bead_id=bead_id,
            agent_name="worker",
        )
        is BeadClaimReleaseOutcome.RELEASED
    )
    assert commit_count(tmp_path) == initial_commits + 2
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


def test_claim_publication_failures_warn_and_preserve_local_transitions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    beads_dir, bead_id = project_with_committed_phase(tmp_path)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    publish_calls: list[Path] = []
    log_path = tmp_path / "managed-sync.log"

    def fail_publication(path: Path) -> _PushOutcome:
        publish_calls.append(path)
        return _PushOutcome(
            pushed=False,
            skipped_no_remote=False,
            error="git push failed: rejected",
            log_path=log_path,
        )

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fail_publication)
    monkeypatch.setattr("sase.bead.sync._is_in_tree_beads_dir", lambda _path: False)

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.CLAIMED, "worker")

    assert (
        release_bead_claim_for_agent(
            project_name="proj",
            bead_id=bead_id,
            agent_name="worker",
        )
        is BeadClaimReleaseOutcome.RELEASED
    )
    with BeadProject(tmp_path) as project:
        issue = project.show(bead_id)
        assert (issue.status, issue.assignee) == (Status.OPEN, "")

    assert publish_calls == [beads_dir, beads_dir]
    stderr = capsys.readouterr().err
    assert stderr.count("Failed to publish bead claim transition") == 2
    assert bead_id in stderr
    assert "worker" in stderr
    assert "git push failed: rejected" in stderr
    assert str(log_path) in stderr


def test_wait_claim_release_and_launch_promotion_publish_to_remote(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )
    canonical = tmp_path / "canonical"
    canonical.mkdir()
    init_git_repo(canonical)
    subprocess.run(
        ["git", "branch", "-M", "main"],
        cwd=canonical,
        check=True,
        capture_output=True,
    )
    (canonical / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(canonical, beads_dirname="beads") as project:
        bead_id = project.create("Remote claim", IssueType.PLAN).id
    subprocess.run(
        ["git", "add", ".gitignore", "beads"],
        cwd=canonical,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "seed remote bead"],
        cwd=canonical,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)],
        cwd=canonical,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=canonical,
        check=True,
        capture_output=True,
    )
    beads_dir = canonical / "beads"
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )

    def observe_remote(name: str) -> tuple[Status, str]:
        clone = tmp_path / name
        subprocess.run(
            ["git", "clone", str(remote), str(clone)],
            check=True,
            capture_output=True,
        )
        with BeadProject(clone, beads_dirname="beads") as project:
            issue = project.show(bead_id)
            return issue.status, issue.assignee

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    assert observe_remote("claimed") == (Status.CLAIMED, "worker")

    assert (
        release_bead_claim_for_agent(
            project_name="proj",
            bead_id=bead_id,
            agent_name="worker",
        )
        is BeadClaimReleaseOutcome.RELEASED
    )
    assert observe_remote("released") == (Status.OPEN, "")

    assert claim_bead_for_waiting_agent(
        project_name="proj",
        bead_id=bead_id,
        agent_name="worker",
    )
    store = SddStore(
        storage="separate_repo",
        sdd_dir=canonical,
        repo_root=canonical,
        remote_url=str(remote),
    )
    with patch("sase.sdd.store.resolve_sdd_store", return_value=store):
        promoted = claim_bead_for_agent_launch(
            agent_name="worker",
            bead_id=bead_id,
            workspace_dir=str(tmp_path),
            workspace_num=1,
            artifacts_dir=str(tmp_path / "artifacts"),
        )

    assert (promoted.status, promoted.assignee) == (Status.IN_PROGRESS, "worker")
    assert observe_remote("promoted") == (Status.IN_PROGRESS, "worker")


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
    assert (
        release_bead_claim_for_agent(
            project_name="proj",
            bead_id="sase-1",
            agent_name="worker",
        )
        is BeadClaimReleaseOutcome.ERROR
    )

    stderr = capsys.readouterr().err
    assert "Warning: Failed to claim bead 'sase-1'" in stderr
    assert "Warning: Failed to release bead claim on 'sase-1'" in stderr


def test_release_claim_distinguishes_nothing_to_release(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    beads_dir, bead_id = project_with_committed_phase(tmp_path)
    monkeypatch.setattr(
        "sase.bead.store_locator.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )

    assert (
        release_bead_claim_for_agent(
            project_name="proj",
            bead_id=bead_id,
            agent_name="worker",
        )
        is BeadClaimReleaseOutcome.NOTHING_TO_RELEASE
    )
