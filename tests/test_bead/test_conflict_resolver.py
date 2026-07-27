"""Tests for bead conflict resolver command behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.bead import conflict_resolver
from sase.bead.conflict_resolver import _git_add, resolve_bead_conflicts
from sase.bead.model import IssueType
from sase.bead.project import BEADS_DIRNAME, BeadProject


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _init_repo(repo: Path) -> None:
    _git(repo, "init", "--initial-branch=master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")


def test_resolve_bead_conflicts_noops_without_conflicts(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is True
    assert result.message == "no conflicted bead files"


def test_git_add_recovers_stale_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    note = tmp_path / "note.txt"
    note.write_text("resolved\n", encoding="utf-8")
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")

    _git_add(tmp_path, ["note.txt"])

    assert not lock.exists()
    assert _git(tmp_path, "diff", "--cached", "--name-only").stdout.strip() == (
        "note.txt"
    )


def test_resolve_bead_conflicts_rejects_nonmergeable_bead_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    config = tmp_path / "sdd/beads/config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"owner":"base"}\n', encoding="utf-8")
    _git(tmp_path, "add", "sdd/beads/config.json")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    config.write_text('{"owner":"other"}\n', encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    config.write_text('{"owner":"local"}\n', encoding="utf-8")
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert result.message == "unsupported bead conflicts: sdd/beads/config.json"


def test_resolve_bead_conflicts_rejects_only_non_bead_conflicts(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    (tmp_path / "sdd/beads").mkdir(parents=True)
    notes = tmp_path / "notes.txt"
    notes.write_text("base\n", encoding="utf-8")
    _git(tmp_path, "add", "notes.txt")
    _git(tmp_path, "commit", "-m", "base")
    _git(tmp_path, "checkout", "-b", "other")
    notes.write_text("other\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "other")
    _git(tmp_path, "checkout", "master")
    notes.write_text("local\n", encoding="utf-8")
    _git(tmp_path, "commit", "-am", "local")
    _git(tmp_path, "merge", "other", check=False)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert result.message == "non-bead conflicts remain: notes.txt"


def _build_stream_conflict(
    repo: Path,
    *,
    bystanders: int = 0,
    bystander_label: str = "Quiet",
) -> tuple[str, list[str]]:
    """Diverge one bead event stream, leaving *bystanders* streams untouched."""
    _init_repo(repo)
    with BeadProject.init(repo, beads_dirname=BEADS_DIRNAME) as project:
        quiet = [
            project.create(f"{bystander_label} {index}", IssueType.PLAN).id
            for index in range(bystanders)
        ]
        contested = project.create("Contested", IssueType.PLAN).id
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")

    _git(repo, "checkout", "-b", "other")
    with BeadProject(repo, beads_dirname=BEADS_DIRNAME) as project:
        project.update(contested, notes="from other")
    _git(repo, "commit", "-am", "other")

    _git(repo, "checkout", "master")
    with BeadProject(repo, beads_dirname=BEADS_DIRNAME) as project:
        project.update(contested, design="from local")
    _git(repo, "commit", "-am", "local")

    _git(repo, "merge", "other", check=False)
    return f"{BEADS_DIRNAME}/events/streams/{contested}.jsonl", quiet


def test_failed_conflict_probe_is_not_reported_as_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _init_repo(tmp_path)
    real_run_git = conflict_resolver._run_git

    def fail_conflict_probe(
        cwd: Path, args: list[str]
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["diff"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                128,
                stdout="",
                stderr="fatal: Unable to create '.git/index.lock': File exists.",
            )
        return real_run_git(cwd, args)

    monkeypatch.setattr(conflict_resolver, "_run_git", fail_conflict_probe)

    result = resolve_bead_conflicts(tmp_path)

    assert result.ok is False
    assert "could not list conflicted bead files" in result.message
    assert result.resolved_files == ()


def test_conflict_probe_retries_through_a_stale_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The probes contend on index.lock, so they use the shared retry policy."""
    contested, _quiet = _build_stream_conflict(tmp_path)
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")
    lock = tmp_path / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert contested in result.resolved_files
    assert not lock.exists()


def test_resolution_leaves_untouched_streams_alone(tmp_path: Path) -> None:
    contested, quiet = _build_stream_conflict(tmp_path, bystanders=3)
    streams = tmp_path / BEADS_DIRNAME / "events" / "streams"
    quiet_paths = [streams / f"{stream_id}.jsonl" for stream_id in quiet]
    quiet_mtimes = {path: path.stat().st_mtime_ns for path in quiet_paths}

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert set(result.resolved_files) == {
        contested,
        f"{BEADS_DIRNAME}/events/manifest.json",
        f"{BEADS_DIRNAME}/issues.jsonl",
    }
    assert {path: path.stat().st_mtime_ns for path in quiet_paths} == quiet_mtimes
    staged = _git(tmp_path, "diff", "--cached", "--name-only").stdout.split()
    assert not [path for path in staged if any(name in path for name in quiet)]
    merged = (tmp_path / contested).read_text(encoding="utf-8")
    assert "from local" in merged and "from other" in merged


def test_resolution_preserves_non_ascii_bytes_in_untouched_streams(
    tmp_path: Path,
) -> None:
    """The Rust writer emits unescaped UTF-8; escaping it here churns every file."""
    _contested, quiet = _build_stream_conflict(
        tmp_path, bystanders=2, bystander_label="Quiét — ünicode"
    )
    streams = tmp_path / BEADS_DIRNAME / "events" / "streams"
    quiet_paths = [streams / f"{stream_id}.jsonl" for stream_id in quiet]
    quiet_bytes = {path: path.read_bytes() for path in quiet_paths}
    assert all(b"Qui\xc3\xa9t" in data for data in quiet_bytes.values())
    # Written by the Rust store writer, and the merge changes no manifest field.
    manifest_path = tmp_path / BEADS_DIRNAME / "events" / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is True, result.message
    assert {path: path.read_bytes() for path in quiet_paths} == quiet_bytes
    assert manifest_path.read_bytes() == manifest_bytes
    staged = _git(tmp_path, "diff", "--cached", "--name-only").stdout.split()
    assert not [path for path in staged if any(name in path for name in quiet)]
    issues = (tmp_path / BEADS_DIRNAME / "issues.jsonl").read_bytes()
    assert b"Qui\xc3\xa9t" in issues
    assert b"\\u" not in issues


def test_failed_stage_read_does_not_silently_drop_one_side(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreadable conflict stage is an error, not an empty stream."""
    contested, _quiet = _build_stream_conflict(tmp_path)
    real_run_git = conflict_resolver._run_git

    def fail_stage_read(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["show"]:
            return subprocess.CompletedProcess(
                ["git", *args], 128, stdout="", stderr="fatal: injected show failure"
            )
        return real_run_git(cwd, args)

    monkeypatch.setattr(conflict_resolver, "_run_git", fail_stage_read)

    result = resolve_bead_conflicts(tmp_path, beads_dir=tmp_path / BEADS_DIRNAME)

    assert result.ok is False
    assert f"could not read stage 1 of {contested}" in result.message
