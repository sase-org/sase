"""Shared builders for durable rescue-store tests."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "test@test.com")
    git(path, "config", "user.name", "Test")
    git(path, "config", "commit.gpgsign", "false")
    git(path, "commit", "--allow-empty", "-m", "init")


def commit_file(repo: Path, relpath: str, text: str, message: str) -> str:
    target = repo / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    git(repo, "add", "--", relpath)
    git(repo, "commit", "-m", message)
    return git(repo, "rev-parse", "HEAD").stdout.strip()


def redirect_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, list[tuple[object, ...]]]:
    """Point SASE_HOME and notifications at tmp; return home and sent notes."""
    home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(home))
    notified: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        "sase.notifications.notify_workflow_complete",
        lambda *args, **kwargs: notified.append((*args, kwargs)),
    )
    return home, notified


def seed_remote_clone(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Return (workspace, clone, remote) with the clone tracking a bare remote."""
    remote = tmp_path / "origin.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    seed = tmp_path / "seed"
    init_repo(seed)
    commit_file(seed, "base.txt", "base\n", "seed base")
    git(seed, "remote", "add", "origin", str(remote))
    git(seed, "push", "-u", "origin", "main")
    workspace = tmp_path / "project_7"
    workspace.mkdir()
    clone = workspace / "sase" / "repos" / "plans"
    clone.parent.mkdir(parents=True)
    subprocess.run(
        ["git", "clone", str(remote), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(clone, "config", "user.email", "test@test.com")
    git(clone, "config", "user.name", "Test")
    git(clone, "config", "commit.gpgsign", "false")
    return workspace, clone, remote


def bundle_lists_sha(bundle: Path, sha: str) -> bool:
    """Return whether the bundle advertises *sha* as a head."""
    listing = subprocess.run(
        ["git", "bundle", "list-heads", str(bundle)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return sha in listing


def clone_and_fetch(bundle: Path, base: Path, dest: Path) -> Path:
    """Clone *base* (which holds the bundle's prerequisites) and fetch it."""
    subprocess.run(
        ["git", "clone", "-q", str(base), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "fetch", str(bundle), "refs/*:refs/sase/rescued/x/*"],
        cwd=dest,
        check=True,
        capture_output=True,
        text=True,
    )
    return dest


def holds_object(repo: Path, sha: str) -> bool:
    return (
        subprocess.run(
            ["git", "cat-file", "-e", sha], cwd=repo, capture_output=True
        ).returncode
        == 0
    )


def rescue_entries(home: Path) -> list[Path]:
    root = home / "rescue"
    if not root.is_dir():
        return []
    return sorted(
        entry
        for month in root.iterdir()
        if month.is_dir()
        for entry in month.iterdir()
        if entry.is_dir()
    )


def rescue_tmp_refs(repo: Path) -> str:
    return git(
        repo, "for-each-ref", "--format=%(refname)", "refs/sase/rescue-tmp"
    ).stdout.strip()


def _push_off_branch_tag(tmp_path: Path, remote: Path, tag: str = "v1.0") -> None:
    """Push *tag* pointing at a commit that is on no remote branch."""
    work = tmp_path / f"off-branch-{tag}"
    subprocess.run(
        ["git", "clone", str(remote), str(work)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(work, "config", "user.email", "test@test.com")
    git(work, "config", "user.name", "Test")
    git(work, "config", "commit.gpgsign", "false")
    git(work, "checkout", "-b", "tmp-release")
    commit_file(work, "release.txt", "off-branch release\n", "release bump")
    git(work, "tag", "-a", tag, "-m", f"release {tag}")
    git(work, "push", "origin", f"refs/tags/{tag}")


def seed_clone_with_off_branch_tag(
    tmp_path: Path, tag: str = "v1.0"
) -> tuple[Path, Path, Path]:
    """Return (workspace, clone, remote) whose clone has an off-branch upstream tag."""
    workspace, clone, remote = seed_remote_clone(tmp_path)
    _push_off_branch_tag(tmp_path, remote, tag)
    shutil.rmtree(clone)
    subprocess.run(
        ["git", "clone", str(remote), str(clone)],
        check=True,
        capture_output=True,
        text=True,
    )
    git(clone, "config", "user.email", "test@test.com")
    git(clone, "config", "user.name", "Test")
    git(clone, "config", "commit.gpgsign", "false")
    return workspace, clone, remote
