"""Mixed-version-safe untracking of the ``issues.jsonl`` projection.

Covers projection-off (sase-1h8.11): the migration untracks the projection
with ``git rm --cached`` and drops its stale working copy inside the next
bead commit, stays idempotent, leaves legacy stores alone, and keeps both
mixed-version scenarios safe at the git level.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.bead._projection_migration import migrate_projection_off_track


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _run_git(repo, "config", "user.name", "SASE Test")
    _run_git(repo, "config", "user.email", "sase-test@example.invalid")


def _tracked(repo: Path, rel_path: str) -> bool:
    return rel_path in _run_git(repo, "ls-files").split()


def _make_event_store(repo: Path, beads_dir: Path, *, tracked_projection: bool) -> None:
    """Build a minimal event store, optionally with a tracked projection."""
    events = beads_dir / "events" / "streams"
    events.mkdir(parents=True)
    (beads_dir / "events" / "manifest.json").write_text(
        '{"schema_version":1,"stream_count":0}\n', encoding="utf-8"
    )
    (beads_dir / "config.json").write_text(
        '{"issue_prefix":"beads","next_counter":1}\n', encoding="utf-8"
    )
    (beads_dir / "issues.jsonl").write_text('{"id":"beads-1"}\n', encoding="utf-8")
    if tracked_projection:
        _run_git(repo, "add", ".")
        _run_git(repo, "commit", "-q", "-m", "tracked projection")


def test_migration_drops_stale_copy_for_next_commit(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    beads_dir = repo / "beads"
    _make_event_store(repo, beads_dir, tracked_projection=True)
    assert _tracked(repo, "beads/issues.jsonl")

    changed, gitignore_updated = migrate_projection_off_track(beads_dir, repo)

    assert changed is True
    assert gitignore_updated is True
    # The worktree copy is dropped but the normal add/commit flow stages
    # and records the deletion, so the file stays tracked until committed.
    assert _tracked(repo, "beads/issues.jsonl")
    assert not (beads_dir / "issues.jsonl").exists()
    gitignore = (repo / ".gitignore").read_text(encoding="utf-8")
    assert "beads/issues.jsonl\n" in gitignore

    # The next bead commit lands the untracking.
    _run_git(repo, "add", ".gitignore", "beads")
    _run_git(repo, "commit", "-q", "-m", "projection off the commit path")
    assert not _tracked(repo, "beads/issues.jsonl")


def test_migration_is_idempotent(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    beads_dir = repo / "beads"
    _make_event_store(repo, beads_dir, tracked_projection=True)

    assert migrate_projection_off_track(beads_dir, repo) == (True, True)
    _run_git(repo, "add", ".gitignore", "beads")
    _run_git(repo, "commit", "-q", "-m", "projection off the commit path")
    assert migrate_projection_off_track(beads_dir, repo) == (False, False)


def test_migration_ignores_legacy_stores(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    beads_dir = repo / "beads"
    beads_dir.mkdir(parents=True)
    (beads_dir / "config.json").write_text("{}\n", encoding="utf-8")
    (beads_dir / "issues.jsonl").write_text('{"id":"beads-1"}\n', encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "legacy store")

    assert migrate_projection_off_track(beads_dir, repo) == (False, False)

    assert _tracked(repo, "beads/issues.jsonl")
    assert (beads_dir / "issues.jsonl").is_file()


def test_old_client_regeneration_is_never_staged(tmp_path: Path) -> None:
    """An old client that regenerates the ignored file never stages it."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    beads_dir = repo / "beads"
    _make_event_store(repo, beads_dir, tracked_projection=True)
    assert migrate_projection_off_track(beads_dir, repo) == (True, True)

    # The next bead commit lands the untracking plus the ignore rule.
    _run_git(repo, "add", ".gitignore", "beads")
    _run_git(repo, "commit", "-q", "-m", "projection off the commit path")

    # Old client regenerates the projection on its next mutation.
    (beads_dir / "issues.jsonl").write_text('{"id":"beads-1"}\n', encoding="utf-8")

    # The commit path lists changes with --exclude-standard: the ignored
    # regeneration is invisible, so it is never staged.
    others = _run_git(repo, "ls-files", "--others", "--exclude-standard").split()
    assert "beads/issues.jsonl" not in others
    assert _run_git(repo, "status", "--porcelain").strip() == ""

    # A repeat migration leaves the untracked regeneration alone.
    assert migrate_projection_off_track(beads_dir, repo) == (False, False)
    assert (beads_dir / "issues.jsonl").is_file()


def test_retracked_projection_is_untracked_again(tmp_path: Path) -> None:
    """An old conflict resolution re-tracks the file; migration untracks it."""
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    beads_dir = repo / "beads"
    _make_event_store(repo, beads_dir, tracked_projection=True)
    assert migrate_projection_off_track(beads_dir, repo) == (True, True)
    _run_git(repo, "add", ".gitignore", "beads")
    _run_git(repo, "commit", "-q", "-m", "projection off the commit path")
    assert not _tracked(repo, "beads/issues.jsonl")

    # Old client's conflict resolution re-tracks and commits the file.
    (beads_dir / "issues.jsonl").write_text('{"id":"beads-1"}\n', encoding="utf-8")
    _run_git(repo, "add", "-f", "beads/issues.jsonl")
    _run_git(repo, "commit", "-q", "-m", "old client re-tracks projection")
    assert _tracked(repo, "beads/issues.jsonl")

    changed, _ = migrate_projection_off_track(beads_dir, repo)

    assert changed is True
    assert not (beads_dir / "issues.jsonl").exists()
    # The next new-client mutation untracks it again.
    _run_git(repo, "add", "beads")
    _run_git(repo, "commit", "-q", "-m", "untrack re-tracked projection")
    assert not _tracked(repo, "beads/issues.jsonl")


def test_migration_supports_root_layout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    _make_event_store(repo, repo, tracked_projection=True)
    assert _tracked(repo, "issues.jsonl")

    changed, gitignore_updated = migrate_projection_off_track(repo, repo)

    assert changed is True
    assert gitignore_updated is True
    assert not (repo / "issues.jsonl").exists()
    gitignore = (repo / ".gitignore").read_text(encoding="utf-8")
    assert "\nissues.jsonl\n" in f"\n{gitignore}"
    _run_git(repo, "add", ".gitignore", "issues.jsonl")
    _run_git(repo, "commit", "-q", "-m", "projection off the commit path")
    assert not _tracked(repo, "issues.jsonl")
