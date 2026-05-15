"""Tests for sase.bead.sync."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.bead.sync import (
    bead_state_is_clean,
    commit_bead_work_launch,
    git_sync,
    push_bead_work_launch,
    rebuild_from_jsonl,
)


def _sync_status(beads_dir: Path) -> bool:
    return bead_state_is_clean(beads_dir)


def _init_git_repo(path):
    """Initialize a git repo at the given path."""
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=path,
        capture_output=True,
        check=True,
    )
    # Create initial commit so HEAD exists
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "init"],
        cwd=path,
        capture_output=True,
        check=True,
    )


def test_sync_status_clean_when_no_jsonl(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    assert _sync_status(beads_dir) is True


def test_sync_status_clean_when_committed(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text("")
    subprocess.run(["git", "add", str(jsonl)], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add jsonl"], cwd=tmp_path, capture_output=True
    )
    assert _sync_status(beads_dir) is True


def test_sync_status_dirty_when_modified(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text("")
    subprocess.run(["git", "add", str(jsonl)], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add jsonl"], cwd=tmp_path, capture_output=True
    )
    jsonl.write_text('{"id":"test"}\n')
    assert _sync_status(beads_dir) is False


def test_sync_status_dirty_when_event_stream_untracked(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text("")
    subprocess.run(["git", "add", "sdd/beads"], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add bead state"],
        cwd=tmp_path,
        capture_output=True,
    )

    stream = beads_dir / "events/streams/test.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"test"}\n')

    assert _sync_status(beads_dir) is False


def test_git_sync_stages_bead_state(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    stream = beads_dir / "events/streams/test.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"test"}\n')

    git_sync(beads_dir)

    # Verify the bead state was staged but not committed.
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert "issues.jsonl" in result.stdout
    assert "events/streams/test.jsonl" in result.stdout


def test_git_sync_noop_when_clean(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text("")
    subprocess.run(["git", "add", str(jsonl)], cwd=tmp_path, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"], cwd=tmp_path, capture_output=True
    )

    # Sync again with no changes — nothing should be staged
    git_sync(beads_dir)
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""


def test_commit_bead_work_launch_commits_bead_state(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    stream = beads_dir / "events/streams/sase-1.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"sase-1:000001"}\n')

    committed = commit_bead_work_launch(
        beads_dir,
        "sase-1",
        "Test epic",
        kind="epic",
    )

    assert committed is True
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert subject.stdout.strip() == "chore: mark bead work launched for sase-1"
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert files.stdout.strip().splitlines() == [
        "sdd/beads/events/streams/sase-1.jsonl",
        "sdd/beads/issues.jsonl",
    ]


def test_commit_bead_work_launch_noops_outside_git(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"test"}\n')

    assert (
        commit_bead_work_launch(beads_dir, "sase-1", "Test epic", kind="epic") is False
    )


def test_commit_bead_work_launch_noops_when_bead_state_has_no_change(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    subprocess.run(["git", "add", "sdd/beads/issues.jsonl"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "add jsonl"], cwd=tmp_path, check=True)

    assert (
        commit_bead_work_launch(beads_dir, "sase-1", "Test epic", kind="epic") is False
    )
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert subject.stdout.strip() == "add jsonl"


def test_commit_bead_work_launch_leaves_unrelated_staged_files_staged(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    other = tmp_path / "notes.txt"
    jsonl.write_text('{"id":"initial"}\n')
    other.write_text("initial\n")
    subprocess.run(
        ["git", "add", "sdd/beads/issues.jsonl", "notes.txt"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "commit", "-m", "initial files"], cwd=tmp_path, check=True)

    jsonl.write_text('{"id":"changed"}\n')
    other.write_text("changed\n")
    subprocess.run(["git", "add", "notes.txt"], cwd=tmp_path, check=True)

    committed = commit_bead_work_launch(
        beads_dir,
        "sase-1",
        "Test epic",
        kind="epic",
    )

    assert committed is True
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert files.stdout.strip() == "sdd/beads/issues.jsonl"
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert staged.stdout.strip() == "notes.txt"


def test_rebuild_from_jsonl_creates_db(tmp_path):
    from sase.bead.db import create_issue, get_issue, init_db
    from sase.bead.jsonl import export_to_jsonl
    from sase.bead.model import Issue, IssueType

    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    db_path = beads_dir / "beads.db"
    jsonl_path = beads_dir / "issues.jsonl"

    # Create a database with an issue, export to JSONL
    conn = init_db(db_path)
    create_issue(
        conn,
        Issue(
            id="test-1",
            title="Test",
            issue_type=IssueType.PLAN,
            created_at="2024-01-01",
            updated_at="2024-01-01",
        ),
    )
    export_to_jsonl(conn, jsonl_path)
    conn.close()

    # Delete the db
    db_path.unlink()
    assert not db_path.exists()

    # Rebuild from JSONL
    result = rebuild_from_jsonl(beads_dir)
    assert result is True
    assert db_path.exists()

    # Verify the issue was restored
    conn = init_db(db_path)
    issue = get_issue(conn, "test-1")
    conn.close()
    assert issue is not None
    assert issue.title == "Test"


def test_rebuild_from_jsonl_noop_when_db_newer(tmp_path):
    import time

    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl_path = beads_dir / "issues.jsonl"
    db_path = beads_dir / "beads.db"

    jsonl_path.write_text("")
    time.sleep(0.01)
    db_path.write_text("")

    result = rebuild_from_jsonl(beads_dir)
    assert result is False


def test_push_bead_work_launch_skips_when_no_remote(tmp_path):
    _init_git_repo(tmp_path)
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
    _init_git_repo(repo)
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


def test_push_bead_work_launch_returns_error_on_failure(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
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
    assert "git push failed" in outcome.error
