"""Tests for sase.bead.sync."""

from __future__ import annotations

import subprocess

from sase.bead.sync import (
    commit_bead_work_launch,
    git_sync,
    rebuild_from_jsonl,
    sync_status,
)


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
    assert sync_status(beads_dir) is True


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
    assert sync_status(beads_dir) is True


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
    assert sync_status(beads_dir) is False


def test_git_sync_stages_jsonl(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')

    git_sync(beads_dir)

    # Verify the file was staged but not committed
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert "issues.jsonl" in result.stdout


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


def test_commit_bead_work_launch_commits_jsonl(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')

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
    assert files.stdout.strip() == "sdd/beads/issues.jsonl"


def test_commit_bead_work_launch_noops_outside_git(tmp_path):
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"test"}\n')

    assert (
        commit_bead_work_launch(beads_dir, "sase-1", "Test epic", kind="epic") is False
    )


def test_commit_bead_work_launch_noops_when_jsonl_has_no_change(tmp_path):
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
