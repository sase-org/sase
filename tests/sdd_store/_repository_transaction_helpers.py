"""Shared repository-transaction test setup helpers."""

from __future__ import annotations

from pathlib import Path
import subprocess

from tests.sdd_store._helpers import (
    clone,
    commit_all,
    git,
    init_bare_repo,
)


def build_diverged_clones(
    tmp_path: Path,
    *,
    relative_path: str = "plans/shared.md",
    base: str = "base\n",
    local: str = "local\n",
    remote_text: str = "remote\n",
) -> tuple[Path, Path, Path]:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    left = tmp_path / "left"
    right = tmp_path / "right"
    init_bare_repo(remote)
    clone(remote, seed)
    target = seed / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(base, encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, left)
    clone(remote, right)

    (left / relative_path).write_text(local, encoding="utf-8")
    commit_all(left, "local change")
    (right / relative_path).write_text(remote_text, encoding="utf-8")
    commit_all(right, "remote change")
    git(["push"], right)
    return remote, left, right


def snapshot(repo: Path) -> tuple[str, str, str]:
    return (
        git(["symbolic-ref", "--short", "HEAD"], repo).stdout,
        git(["rev-parse", "HEAD"], repo).stdout,
        git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            repo,
        ).stdout,
    )


def run_git(
    repo_root: Path,
    args: list[str],
    *,
    op: str,
    network: bool = False,
) -> subprocess.CompletedProcess[str]:
    del op, network
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
