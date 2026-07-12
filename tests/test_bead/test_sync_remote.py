"""Tests for remote bead synchronization."""

from __future__ import annotations

import json
import subprocess

from sase.bead.sync import push_bead_work_launch
from sase.bead.sync_worker import run_managed_sync_worker

from .sync_test_helpers import configure_git_identity, init_git_repo


def test_push_bead_work_launch_skips_when_no_remote(tmp_path):
    init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is True
    assert outcome.error is None


def test_push_bead_work_launch_skips_outside_git_repo(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is True
    assert outcome.error is None


def test_push_bead_work_launch_pushes_to_remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)],
        capture_output=True,
        check=True,
    )

    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "push", "-u", "origin", branch],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    subprocess.run(
        ["git", "add", "sdd/beads/issues.jsonl"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "add jsonl"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is True
    assert outcome.skipped_no_remote is False
    assert outcome.error is None

    local_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    remote_head = subprocess.run(
        ["git", "rev-parse", f"refs/heads/{branch}"],
        cwd=bare,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert local_head == remote_head


def test_push_bead_work_launch_rebases_and_retries_rejected_push(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True,
        check=True,
    )

    seed = tmp_path / "seed"
    seed.mkdir()
    init_git_repo(seed)
    subprocess.run(["git", "branch", "-M", "main"], cwd=seed, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", str(bare)],
        cwd=seed,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=seed,
        capture_output=True,
        check=True,
    )

    repo = tmp_path / "repo"
    other = tmp_path / "other"
    subprocess.run(
        ["git", "clone", str(bare), str(repo)], capture_output=True, check=True
    )
    subprocess.run(
        ["git", "clone", str(bare), str(other)], capture_output=True, check=True
    )
    configure_git_identity(repo)
    configure_git_identity(other)

    (other / "remote.md").write_text("remote\n", encoding="utf-8")
    subprocess.run(
        ["git", "add", "remote.md"], cwd=other, capture_output=True, check=True
    )
    subprocess.run(
        ["git", "commit", "-m", "remote change"],
        cwd=other,
        capture_output=True,
        check=True,
    )
    subprocess.run(["git", "push"], cwd=other, capture_output=True, check=True)

    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"local"}\n', encoding="utf-8")
    subprocess.run(
        ["git", "add", "sdd/beads/issues.jsonl"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "local bead change"],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is True
    assert outcome.skipped_no_remote is False
    assert outcome.error is None
    assert (repo / "remote.md").read_text(encoding="utf-8") == "remote\n"

    verify = tmp_path / "verify"
    subprocess.run(
        ["git", "clone", str(bare), str(verify)],
        capture_output=True,
        check=True,
    )
    assert (verify / "remote.md").read_text(encoding="utf-8") == "remote\n"
    assert (verify / "sdd/beads/issues.jsonl").read_text(encoding="utf-8") == (
        '{"id":"local"}\n'
    )


def test_push_bead_work_launch_returns_error_on_failure(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init_git_repo(repo)
    subprocess.run(
        ["git", "remote", "add", "origin", str(tmp_path / "does-not-exist.git")],
        cwd=repo,
        capture_output=True,
        check=True,
    )

    beads_dir = repo / "sdd/beads"
    beads_dir.mkdir(parents=True)

    outcome = push_bead_work_launch(beads_dir)

    assert outcome.pushed is False
    assert outcome.skipped_no_remote is False
    assert outcome.error is not None
    assert "git fetch failed" in outcome.error


def test_managed_sync_worker_converges_companion_store_mutations(tmp_path):
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        check=True,
        capture_output=True,
    )
    seed = tmp_path / "seed"
    seed.mkdir()
    init_git_repo(seed)
    subprocess.run(["git", "branch", "-M", "main"], cwd=seed, check=True)
    (seed / ".gitignore").write_text("beads/beads.db*\n", encoding="utf-8")
    with BeadProject.init(seed, beads_dirname="beads") as project:
        first = project.create("First", IssueType.PLAN)
        second = project.create("Second", IssueType.PLAN)
    subprocess.run(["git", "add", "."], cwd=seed, check=True)
    subprocess.run(
        ["git", "commit", "-m", "seed beads"],
        cwd=seed,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=seed, check=True)
    subprocess.run(
        ["git", "push", "-u", "origin", "main"],
        cwd=seed,
        check=True,
        capture_output=True,
    )

    left = tmp_path / "left"
    right = tmp_path / "right"
    subprocess.run(
        ["git", "clone", str(bare), str(left)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "clone", str(bare), str(right)], check=True, capture_output=True
    )
    configure_git_identity(left)
    configure_git_identity(right)

    with BeadProject(left, beads_dirname="beads") as project:
        project.update(first.id, title="First from left")
    subprocess.run(["git", "add", "beads"], cwd=left, check=True)
    subprocess.run(
        ["git", "commit", "-m", "left mutation"],
        cwd=left,
        check=True,
        capture_output=True,
    )

    with BeadProject(right, beads_dirname="beads") as project:
        project.update(second.id, title="Second from right")
    subprocess.run(["git", "add", "beads"], cwd=right, check=True)
    subprocess.run(
        ["git", "commit", "-m", "right mutation"],
        cwd=right,
        check=True,
        capture_output=True,
    )
    subprocess.run(["git", "push"], cwd=right, check=True, capture_output=True)

    log_path = tmp_path / "managed-sync.log"
    outcome = run_managed_sync_worker(
        left,
        left / "beads",
        log_path=log_path,
    )

    assert outcome.pushed is True
    assert outcome.integrated is True
    assert not (left / ".git/rebase-merge").exists()
    assert not (left / ".git/rebase-apply").exists()
    assert (
        subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=left,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
    verify = tmp_path / "verify-convergence"
    subprocess.run(
        ["git", "clone", str(bare), str(verify)], check=True, capture_output=True
    )
    with BeadProject(verify, beads_dirname="beads") as project:
        assert project.show(first.id).title == "First from left"
        assert project.show(second.id).title == "Second from right"
    log_events = [
        json.loads(line)["event"]
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert log_events[-1] == "completed"
