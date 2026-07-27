"""Tests for sase.bead.sync."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from sase.bead.sync import (
    _is_in_tree_beads_dir,
    bead_sync_diagnostics,
    bead_state_is_clean,
    commit_bead_work_launch,
    git_sync,
    rebuild_from_jsonl,
)
from sase.bead._sync_git import BeadWorkLaunchCommitError
from sase.sdd._repository_transaction import SddRepositoryHealthError

from .sync_test_helpers import init_git_repo as _init_git_repo


def _sync_status(beads_dir: Path) -> bool:
    return bead_state_is_clean(beads_dir)


def test_split_beads_sidecar_is_not_an_in_tree_store(tmp_path: Path) -> None:
    assert not _is_in_tree_beads_dir(tmp_path / "sase" / "repos" / "beads")


def _redirect_sync_logs(monkeypatch: pytest.MonkeyPatch, log_dir: Path) -> None:
    log_dir.mkdir()

    def fake_ensure_sase_directory(name: str) -> Path:
        assert name == "bead_push_logs"
        return log_dir

    monkeypatch.setattr(
        "sase.core.paths.ensure_sase_directory",
        fake_ensure_sase_directory,
    )


def _write_sync_log(
    log_dir: Path,
    name: str,
    repo_root: Path,
    *,
    event: str,
    mtime: float,
    error: str | None = None,
) -> Path:
    records = [
        {
            "ts": mtime,
            "event": "started",
            "repo_root": str(repo_root.resolve()),
            "beads_dir": str((repo_root / "beads").resolve(strict=False)),
        }
    ]
    if event == "failed":
        records.append(
            {
                "ts": mtime + 0.1,
                "event": "failed",
                "error": error or "injected failure",
                "integrated": False,
            }
        )
    else:
        records.append(
            {
                "ts": mtime + 0.1,
                "event": event,
                "pushed": event == "completed",
                "integrated": event == "completed",
            }
        )
    path = log_dir / name
    path.write_text(
        "".join(f"{json.dumps(record, sort_keys=True)}\n" for record in records),
        encoding="utf-8",
    )
    os.utime(path, (mtime, mtime))
    return path


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


def test_sync_status_dirty_when_probe_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)

    def fail_probe(_beads_dir: Path, _repo_root: Path) -> list[str]:
        raise BeadWorkLaunchCommitError("git ls-files failed")

    monkeypatch.setattr("sase.bead._sync_git._list_bead_state_changes", fail_probe)

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
        kind="epic",
    )

    assert committed is True
    message = subprocess.run(
        ["git", "log", "-1", "--format=%B"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert message.stdout.strip() == (
        "chore: mark bead work launched for sase-1\n\nSASE_TYPE=bead_work"
    )
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

    assert commit_bead_work_launch(beads_dir, "sase-1", kind="epic") is False


def test_commit_bead_work_launch_noops_when_bead_state_has_no_change(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"test"}\n')
    subprocess.run(["git", "add", "sdd/beads/issues.jsonl"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "add jsonl"], cwd=tmp_path, check=True)

    assert commit_bead_work_launch(beads_dir, "sase-1", kind="epic") is False
    subject = subprocess.run(
        ["git", "log", "-1", "--format=%s"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    assert subject.stdout.strip() == "add jsonl"


def test_bead_sync_diagnostics_reports_recurring_managed_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "beads"
    beads_dir.mkdir()
    log_dir = tmp_path / "logs"
    _redirect_sync_logs(monkeypatch, log_dir)

    incident_error = (
        "Could not apply 17e1c56a... chore(beads): claim sase-9w.6; "
        "semantic bead conflict resolution failed: validation: cannot merge "
        "non-append-only bead event stream sase-9w: theirs rewrote base event 21"
    )
    _write_sync_log(
        log_dir,
        "sync-20260727T120000Z-1.log",
        tmp_path,
        event="failed",
        error=incident_error,
        mtime=1,
    )
    latest = _write_sync_log(
        log_dir,
        "sync-20260727T120001Z-2.log",
        tmp_path,
        event="failed",
        error=incident_error,
        mtime=2,
    )

    messages = bead_sync_diagnostics(beads_dir)

    warning = next(
        message for message in messages if "bead managed sync has" in message
    )
    assert "2 consecutive failed integration(s)" in warning
    assert "dominant error class: unresolved rebase (2/2)" in warning
    assert str(latest) in warning


def test_bead_sync_diagnostics_stays_quiet_after_healthy_same_clone_sync(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    beads_dir = repo / "beads"
    beads_dir.mkdir()
    other_repo = tmp_path / "other"
    other_repo.mkdir()
    _init_git_repo(other_repo)
    log_dir = tmp_path / "logs"
    _redirect_sync_logs(monkeypatch, log_dir)

    _write_sync_log(
        log_dir,
        "sync-20260727T120000Z-1.log",
        repo,
        event="failed",
        mtime=1,
        error="git rebase failed: Could not apply abc123",
    )
    _write_sync_log(
        log_dir,
        "sync-20260727T120001Z-2.log",
        repo,
        event="completed",
        mtime=2,
    )
    _write_sync_log(
        log_dir,
        "sync-20260727T120002Z-3.log",
        other_repo,
        event="failed",
        mtime=3,
        error="git rebase failed: Could not apply def456",
    )

    assert bead_sync_diagnostics(beads_dir) == []


@pytest.mark.parametrize("marker", ["rebase-merge", "MERGE_HEAD"])
def test_bead_git_writers_refuse_operations_before_staging(
    tmp_path: Path,
    marker: str,
) -> None:
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    state = beads_dir / "issues.jsonl"
    state.write_text('{"id":"test"}\n', encoding="utf-8")
    marker_path = tmp_path / ".git" / marker
    if "." in marker:
        marker_path.write_text("blocked\n", encoding="utf-8")
    else:
        marker_path.mkdir()
    before = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    with pytest.raises(SddRepositoryHealthError):
        git_sync(beads_dir)
    with pytest.raises(SddRepositoryHealthError):
        commit_bead_work_launch(
            beads_dir,
            "sase-1",
            kind="epic",
        )

    assert state.read_text(encoding="utf-8") == '{"id":"test"}\n'
    assert (
        subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == before
    )


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


def _init_repo_with_beads_db_ignored(tmp_path: Path) -> None:
    """Init a git repo with ``sdd/beads/beads.db*`` listed in ``.gitignore``."""
    _init_git_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("sdd/beads/beads.db*\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "add gitignore"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )


def test_git_sync_succeeds_when_gitignored_beads_db_present(tmp_path):
    _init_repo_with_beads_db_ignored(tmp_path)

    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"test"}\n')
    (beads_dir / "beads.db").write_bytes(b"SQLite")
    stream = beads_dir / "events/streams/sase-1.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"sase-1:000001"}\n')

    git_sync(beads_dir)

    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "sdd/beads/issues.jsonl" in staged
    assert "sdd/beads/events/streams/sase-1.jsonl" in staged
    assert "sdd/beads/beads.db" not in staged


def test_commit_bead_work_launch_succeeds_when_gitignored_beads_db_present(tmp_path):
    _init_repo_with_beads_db_ignored(tmp_path)

    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"test"}\n')
    (beads_dir / "beads.db").write_bytes(b"SQLite")
    (beads_dir / "beads.db-wal").write_bytes(b"WAL")
    (beads_dir / "beads.db-shm").write_bytes(b"SHM")
    stream = beads_dir / "events/streams/sase-1.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"sase-1:000001"}\n')

    committed = commit_bead_work_launch(beads_dir, "sase-1", kind="epic")

    assert committed is True
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "sdd/beads/beads.db" not in files
    assert "sdd/beads/beads.db-wal" not in files
    assert "sdd/beads/beads.db-shm" not in files
    assert "sdd/beads/issues.jsonl" in files
    assert "sdd/beads/events/streams/sase-1.jsonl" in files


def test_commit_bead_work_launch_records_event_stream_deletion(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    jsonl = beads_dir / "issues.jsonl"
    jsonl.write_text('{"id":"sase-1"}\n')
    stream = beads_dir / "events/streams/sase-1.jsonl"
    stream.parent.mkdir(parents=True)
    stream.write_text('{"event_id":"sase-1:000001"}\n')
    subprocess.run(["git", "add", "sdd/beads"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial bead state"],
        cwd=tmp_path,
        capture_output=True,
        check=True,
    )

    stream.unlink()
    jsonl.write_text('{"id":"sase-1","updated":true}\n')

    committed = commit_bead_work_launch(beads_dir, "sase-1", kind="epic")

    assert committed is True
    name_status = subprocess.run(
        ["git", "show", "--name-status", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "D\tsdd/beads/events/streams/sase-1.jsonl" in name_status
    assert "M\tsdd/beads/issues.jsonl" in name_status


def test_commit_bead_work_launch_noops_when_only_ignored_db_changed(tmp_path):
    _init_repo_with_beads_db_ignored(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "beads.db").write_bytes(b"SQLite")

    committed = commit_bead_work_launch(beads_dir, "sase-1", kind="epic")

    assert committed is False
    log_count = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert log_count == "2"  # init + .gitignore commit only


def test_commit_bead_work_launch_picks_up_new_nested_subdirectory_files(tmp_path):
    _init_git_repo(tmp_path)
    beads_dir = tmp_path / "sdd/beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "issues.jsonl").write_text('{"id":"sase-2"}\n')
    nested = beads_dir / "events/streams/sase-2.jsonl"
    nested.parent.mkdir(parents=True)
    nested.write_text('{"event_id":"sase-2:000001"}\n')

    committed = commit_bead_work_launch(beads_dir, "sase-2", kind="epic")

    assert committed is True
    files = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    assert "sdd/beads/events/streams/sase-2.jsonl" in files


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
