"""Integration coverage for git commit-first rebase dispatch."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.vcs_provider.plugins.bare_git import BareGitPlugin


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def _configure_user(cwd: Path) -> None:
    _git(cwd, "config", "user.email", "test@example.com")
    _git(cwd, "config", "user.name", "Test User")


def _clone_origin(tmp_path: Path) -> tuple[Path, Path, Path]:
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    clone = tmp_path / "worker"
    _git(tmp_path, "init", "--bare", "--initial-branch=master", str(origin))
    _git(tmp_path, "clone", str(origin), str(seed))
    _configure_user(seed)
    (seed / "data.txt").write_text("one\nthree\n", encoding="utf-8")
    _git(seed, "add", "data.txt")
    _git(seed, "commit", "-m", "base")
    _git(seed, "push", "origin", "master")
    _git(tmp_path, "clone", str(origin), str(clone))
    _configure_user(clone)
    return origin, seed, clone


def test_create_commit_rebases_clean_upstream_movement_first_try(
    tmp_path: Path,
) -> None:
    origin, _seed, worker = _clone_origin(tmp_path)
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(origin), str(peer))
    _configure_user(peer)

    (worker / "data.txt").write_text("ONE\nthree\n", encoding="utf-8")
    (peer / "peer.txt").write_text("peer\n", encoding="utf-8")
    _git(peer, "add", "peer.txt")
    _git(peer, "commit", "-m", "peer change")
    _git(peer, "push", "origin", "master")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "worker change", "files": ["data.txt"]},
        str(worker),
    )

    assert ok is True, err
    _git(worker, "fetch", "origin", "master")
    assert _git(worker, "status", "--short", "--branch").stdout.strip() == (
        "## master...origin/master"
    )
    assert (worker / "data.txt").read_text(encoding="utf-8") == "ONE\nthree\n"
    assert (worker / "peer.txt").read_text(encoding="utf-8") == "peer\n"


def test_create_commit_leaves_genuine_rebase_conflict_resumable(tmp_path: Path) -> None:
    origin, _seed, worker = _clone_origin(tmp_path)
    peer = tmp_path / "peer"
    _git(tmp_path, "clone", str(origin), str(peer))
    _configure_user(peer)

    (worker / "data.txt").write_text("worker\nthree\n", encoding="utf-8")
    (peer / "data.txt").write_text("peer\nthree\n", encoding="utf-8")
    _git(peer, "add", "data.txt")
    _git(peer, "commit", "-m", "peer conflict")
    _git(peer, "push", "origin", "master")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "worker conflict", "files": ["data.txt"]},
        str(worker),
    )

    assert ok is False
    assert err is not None and "Conflicted files: data.txt" in err
    assert (worker / ".git/rebase-merge").is_dir() or (
        worker / ".git/rebase-apply"
    ).is_dir()
    assert _git(worker, "diff", "--name-only", "--diff-filter=U").stdout.strip() == (
        "data.txt"
    )
