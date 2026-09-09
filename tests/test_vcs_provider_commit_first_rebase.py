"""Integration coverage for git commit-first rebase dispatch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

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


def test_create_commit_records_unpushed_marker_when_push_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _origin, seed, worker = _clone_origin(tmp_path)
    _git(worker, "remote", "set-url", "origin", str(seed))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")

    (worker / "data.txt").write_text("local\nthree\n", encoding="utf-8")

    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "worker local commit", "files": ["data.txt"]},
        str(worker),
    )

    assert ok is False
    assert err is not None
    assert "created locally; git push failed" in err
    assert "refusing to update checked out branch" in err
    assert _git(worker, "status", "--short").stdout.strip() == ""
    sha = _git(worker, "rev-parse", "HEAD").stdout.strip()
    tree = _git(worker, "rev-parse", "HEAD^{tree}").stdout.strip()
    markers = json.loads((artifacts / "commit_results.json").read_text())
    assert len(markers) == 1
    assert markers[0]["cwd"] == str(worker)
    assert markers[0]["result"] == sha
    assert markers[0]["commit_sha"] == sha
    assert markers[0]["commit_tree"] == tree
    assert markers[0]["pushed"] is False


def test_finalize_commit_records_unpushed_marker_when_push_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _origin, seed, worker = _clone_origin(tmp_path)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")

    (worker / "data.txt").write_text("local\nthree\n", encoding="utf-8")
    _git(worker, "add", "data.txt")
    _git(worker, "commit", "-m", "worker local commit")
    _git(worker, "remote", "set-url", "origin", str(seed))

    ok, err = BareGitPlugin().vcs_finalize_commit(
        {"message": "worker local commit"},
        str(worker),
    )

    assert ok is False
    assert err is not None
    assert "created locally; git push failed" in err
    assert "refusing to update checked out branch" in err
    sha = _git(worker, "rev-parse", "HEAD").stdout.strip()
    tree = _git(worker, "rev-parse", "HEAD^{tree}").stdout.strip()
    markers = json.loads((artifacts / "commit_results.json").read_text())
    assert len(markers) == 1
    assert markers[0]["cwd"] == str(worker)
    assert markers[0]["result"] == sha
    assert markers[0]["commit_sha"] == sha
    assert markers[0]["commit_tree"] == tree
    assert markers[0]["pushed"] is False
    assert not (artifacts / "commit_result.json").exists()


def test_create_commit_reports_local_sha_when_push_to_checked_out_origin_refused(
    tmp_path: Path,
) -> None:
    origin = tmp_path / "origin"
    worker = tmp_path / "worker"
    origin.mkdir()
    _git(origin, "init", "--initial-branch=master")
    _configure_user(origin)
    (origin / "data.txt").write_text("base\n", encoding="utf-8")
    _git(origin, "add", "data.txt")
    _git(origin, "commit", "-m", "base")
    _git(tmp_path, "clone", str(origin), str(worker))
    _configure_user(worker)

    (worker / "data.txt").write_text("worker\n", encoding="utf-8")
    ok, err = BareGitPlugin().vcs_create_commit(
        {"message": "worker change", "files": ["data.txt"]},
        str(worker),
    )

    head = _git(worker, "rev-parse", "HEAD").stdout.strip()
    assert ok is False
    assert err is not None
    assert f"commit {head} created locally" in err
    assert "git push failed" in err
    assert _git(worker, "status", "--porcelain").stdout == ""
